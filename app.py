import subprocess

import pvporcupine
import pyaudio
import wave
import requests
import os
import array
import logging
import time
import board
import neopixel
import threading
import RPi.GPIO as GPIO
from pydub import AudioSegment
from pydub.effects import normalize
from dotenv import load_dotenv
load_dotenv()

PIXEL_PIN = board.D18
BUTTON_PIN=4


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

# === WS2812 LED Setup ===
NUM_PIXELS = 3
pixels = neopixel.NeoPixel(PIXEL_PIN, NUM_PIXELS, brightness=0.8, auto_write=True)

def led(state):
    if state == "idle":
        pixels.fill((0, 50, 0))       # grün
    elif state == "listening":
        pixels.fill((255, 165, 0))    # orange
    elif state == "responding":
        pixels.fill((0, 0, 255))      # blau
    elif state == "error":
        for _ in range(3):
            pixels.fill((255, 0, 0))  # rot blinken
            time.sleep(0.3)
            pixels.fill((0, 0, 0))
            time.sleep(0.2)
    elif state == "startup":
        for i in range(0, 255, 5):
            pixels.fill((i, 0, 255 - i))  # Farbverlauf lila → blau
            time.sleep(0.01)
        pixels.fill((0, 0, 0))
    elif state == "shutdown":
        for i in range(3):
            pixels.fill((255, 255, 255))
            time.sleep(0.1)
            pixels.fill((0, 0, 0))
            time.sleep(0.1)

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

def normalize_audio(file_path: str):
    try:
        audio = AudioSegment.from_wav(file_path)
        louder_audio = normalize(audio)
        louder_audio.export(file_path, format="wav")
        print(f"🔊 Audio normalisiert: {file_path}")
    except Exception as e:
        print(f"❌ Fehler bei Audio-Normalisierung: {e}")


def record_audio(filename: str, duration: int, pa, sample_rate, frame_length):
    logging.info(f"🎙 Starte Aufnahme für {duration} Sekunden...")
    led("listening")
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
    time.sleep(0.1)
    logging.info("✅ Aufnahme abgeschlossen")

button_pressed = threading.Event()
def button_callback(channel):
    logging.error(f"CB: Button pressed!")
    button_pressed.set()

def init_gpio():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    try:
        GPIO.add_event_detect(BUTTON_PIN, GPIO.RISING, callback=button_callback, bouncetime=300)
    except RuntimeError as e:
        logging.error(f"⚠️ GPIO-Fehler: {e}")


def send_to_backend(filename: str):
    led("responding")
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
def reduce_noise(input_path: str, output_path: str):
    noise_sample = "noise_sample.wav"
    noise_profile = "noise.prof"

    try:
        # 1. Extract noise sample (first 0.5s)
        subprocess.run([
            "sox", input_path, noise_sample, "trim", "0", "0.5"
        ], check=True)

        # 2. Generate noise profile
        subprocess.run([
            "sox", noise_sample, "-n", "noiseprof", noise_profile
        ], check=True)

        # 3. Apply noise reduction
        subprocess.run([
            "sox", input_path, output_path, "noisered", noise_profile, "0.21"
        ], check=True)

        print(f"✅ Noise reduced and saved to {output_path}")

    except subprocess.CalledProcessError as e:
        print(f"❌ SoX command failed: {e}")

    # Cleanup (optional)
    os.remove(noise_sample)
    os.remove(noise_profile)

def main():
    logging.info("🔊 Initialisiere Wakeword-Engine...")
    led("startup")
    porcupine = pvporcupine.create(os.environ.get("PORC_API_KEY"), keyword_paths=[WAKEWORD_PATH], model_path=os.environ.get("PORC_MODEL_PATH"))
    pa = pyaudio.PyAudio()
    init_gpio()

    while True:
        try:
            logging.info("🟢 Warte auf Wakeword...")
            led("idle")
            stream = pa.open(
                rate=porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=porcupine.frame_length
            )

            try:
                while True:
                    pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
                    pcm = array.array("h", pcm)

                    if porcupine.process(pcm) >= 0:
                        logging.info("🎉 Wakeword erkannt!")
                        break

                    if button_pressed.is_set():
                        logging.info("🔘 Knopf gedrückt!")
                        button_pressed.clear()
                        break

            finally:
                stream.stop_stream()
                stream.close()

            # Danach Aufnahme und Senden
            record_audio(AUDIO_FILENAME, DURATION, pa, porcupine.sample_rate, porcupine.frame_length)
            reduce_noise(AUDIO_FILENAME, "clean_" + AUDIO_FILENAME)
            normalize_audio("clean_" + AUDIO_FILENAME)
            send_to_backend("clean_" + AUDIO_FILENAME)

        except Exception as e:
            logging.error(f"❌ Fehler in Hauptloop: {e}")
            led("error")
            time.sleep(1)  # kurz warten und dann neu versuchen

    porcupine.delete()
    pa.terminate()
    pixels.fill((0, 0, 0))
    GPIO.cleanup()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("🛑 Beendet durch Benutzer")
        GPIO.cleanup()
        led("shutdown")