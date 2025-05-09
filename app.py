import pvporcupine
import pyaudio
import wave
import requests
import os
import array
import logging
import time


from dotenv import load_dotenv
load_dotenv()

# === Konfiguration ===
WAKEWORD_PATH = os.environ.get("PORC_WAKEWORD_PATH")
BACKEND_URL = os.getenv("BACKEND_URL", os.environ.get("GROCYAI_API_URL")+":"+os.environ.get("GROCYAI_API_PORT") + "/upload-audio")
AUDIO_FILENAME = "wake_audio.wav"
DURATION = 5  # Sekunden Aufnahme nach Wakeword

# === Setup Logging ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

def send_tts_to_homeassistant(text: str, player: str, speaker: str = "Mimi"):
    webhook_id = ""
    url =  os.environ.get("HA_WEBHOOK")


    payload = {
        "text": text,
        "player": player,
        "speaker": speaker
    }

    try:
        res = requests.post(url, json=payload, timeout=5)
        res.raise_for_status()
        print("✅ TTS erfolgreich an Home Assistant gesendet.")
    except Exception as e:
        print(f"❌ Fehler beim Senden an HA Webhook: {e}")


def record_audio(filename: str, duration: int, pa, sample_rate, frame_length):
    logging.info(f"🎙 Starte Aufnahme für {duration} Sekunden...")
    stream = pa.open(
        rate=sample_rate,
        channels=1,
        format=pyaudio.paInt16,
        input=True,
        frames_per_buffer=frame_length
    )
    frames = []
    for _ in range(0, int(sample_rate / frame_length * duration)):
        data = stream.read(frame_length, exception_on_overflow=False)
        frames.append(data)

    stream.stop_stream()
    stream.close()

    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
        wf.setframerate(sample_rate)
        wf.writeframes(b''.join(frames))
    logging.info("✅ Aufnahme abgeschlossen")

def send_to_backend(filename: str):
    with open(filename, 'rb') as f:
        files = {'audio': (filename, f, 'audio/wav')}
        try:
            res = requests.post(BACKEND_URL, files=files, timeout=30)
            res.raise_for_status()
            reply = res.json().get("reply")
            logging.info(f"🤖 Antwort: {reply}")

            send_tts_to_homeassistant(
                text=reply,
                player=os.environ.get("HA_WEBHOOK_PLAYER"),
                speaker="Mila"
            )
        except Exception as e:
            logging.error(f"❌ Fehler beim Senden an Backend: {e}")

def main():
    logging.info("🔊 Initialisiere Wakeword-Engine...")
    porcupine = pvporcupine.create(os.environ.get("PORC_API_KEY"), keyword_paths=[WAKEWORD_PATH], model_path=os.environ.get("PORC_MODEL_PATH"))
    pa = pyaudio.PyAudio()

    while True:
        try:
            logging.info("🟢 Warte auf Wakeword...")
            stream = pa.open(
                rate=porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=porcupine.frame_length
            )

            while True:
                pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
                pcm = array.array("h", pcm)
                if porcupine.process(pcm) >= 0:
                    logging.info("🎉 Wakeword erkannt!")
                    stream.stop_stream()
                    stream.close()
                    record_audio(AUDIO_FILENAME, DURATION, pa, porcupine.sample_rate, porcupine.frame_length)
                    send_to_backend(AUDIO_FILENAME)
                    break

        except Exception as e:
            logging.error(f"❌ Fehler in Hauptloop: {e}")
            time.sleep(1)  # kurz warten und dann neu versuchen

    porcupine.delete()
    pa.terminate()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("🛑 Beendet durch Benutzer")