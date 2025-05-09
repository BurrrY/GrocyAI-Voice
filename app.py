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
BACKEND_URL = os.getenv("BACKEND_URL", os.environ.get("GROCYAI_API_URL") + "/chat")
AUDIO_FILENAME = "wake_audio.wav"
DURATION = 5  # Sekunden Aufnahme nach Wakeword

# === Wakeword initialisieren ===
porcupine = pvporcupine.create(os.environ.get("PORC_API_KEY"), keyword_paths=[WAKEWORD_PATH], model_path=os.environ.get("PORC_MODEL_PATH"))
pa = pyaudio.PyAudio()
stream = pa.open(
    rate=porcupine.sample_rate,
    channels=1,
    format=pyaudio.paInt16,
    input=True,
    frames_per_buffer=porcupine.frame_length
)

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
        except Exception as e:
            print("❌ Fehler beim Senden an Backend:", e)

try:
    print("🔊 Bereit – warte auf Wakeword ...")
    while True:
        pcm = stream.read(porcupine.frame_length)
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
