import pvporcupine
import pyaudio
import wave
import requests
import os
import array


from dotenv import load_dotenv
load_dotenv()

# === Konfiguration ===
WAKEWORD_PATH = os.environ.get("PORC_WAKEWORD_PATH")
BACKEND_URL = os.getenv("BACKEND_URL", os.environ.get("GROCYAI_API_URL")+":"+os.environ.get("GROCYAI_API_PORT") + "/upload-audio")
AUDIO_FILENAME = "wake_audio.wav"
DURATION = 5  # Sekunden Aufnahme nach Wakeword

# === Wakeword initialisieren ===
porcupine = pvporcupine.create(os.environ.get("PORC_API_KEY"), keyword_paths=[WAKEWORD_PATH], model_path=os.environ.get("PORC_MODEL_PATH"))


pa = pyaudio.PyAudio()
usb_index = None
for i in range(pa.get_device_count()):
    info = pa.get_device_info_by_index(i)
    if "USB" in info["name"] and info["maxInputChannels"] > 0:
        usb_index = i
        break

print("Using device #" + str(usb_index))

info = pa.get_device_info_by_index(usb_index)
print(f"Supported sample rate(s) for {info['name']}:")
print(info)


stream = pa.open(
    rate=porcupine.sample_rate,
    channels=1,
    format=pyaudio.paInt16,
    input=True,
    #input_device_index=usb_index,
    frames_per_buffer=porcupine.frame_length
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


def record_audio(filename: str, duration: int):
    frames = []
    print(f"🎙 Aufnahme gestartet ({duration}s)...")
    for _ in range(0, int(porcupine.sample_rate / porcupine.frame_length * duration)):
        data = stream.read(porcupine.frame_length, exception_on_overflow=False)
        frames.append(data)

    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
        wf.setframerate(porcupine.sample_rate)
        wf.writeframes(b''.join(frames))
    print("✅ Aufnahme beendet")

def send_to_backend(filename: str):
    with open(filename, 'rb') as f:
        files = {'audio': (filename, f, 'audio/wav')}
        try:
            res = requests.post(BACKEND_URL, files=files, timeout=30)
            res.raise_for_status()
            print("🤖 Antwort vom Backend:", res.json().get("reply"))

            send_tts_to_homeassistant(
                text=res.json().get("reply"),
                player=os.environ.get("HA_WEBHOOK_PLAYER"),
                speaker="Mila"
            )
        except Exception as e:
            print("❌ Fehler beim Senden an Backend:", e)

try:
    print("🔊 Bereit – warte auf Wakeword ...")
    while True:
        pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
        pcm = array.array("h", pcm)  # int16 PCM
        if porcupine.process(pcm) >= 0:
            print("🎉 Wakeword erkannt!")
            record_audio(AUDIO_FILENAME, DURATION)
            send_to_backend(AUDIO_FILENAME)
            print("⏳ Warte erneut auf Wakeword...")

except KeyboardInterrupt:
    print("🛑 Beende...")
finally:
    stream.stop_stream()
    stream.close()
    pa.terminate()
    porcupine.delete()
