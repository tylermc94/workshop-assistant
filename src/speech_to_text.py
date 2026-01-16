import sys
import os
import sounddevice as sd
from vosk import Model, KaldiRecognizer
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import AUDIO_DEVICE, SCARLETT_SAMPLE_RATE, RECORDING_DURATION,  VOSK_MODEL

# Initialize Vosk
base_dir = os.path.dirname(os.path.dirname(__file__))
model_file_path = os.path.join(base_dir, VOSK_MODEL)
model = Model(model_file_path)
recognizer = KaldiRecognizer(model, SCARLETT_SAMPLE_RATE)  # Scarlett's sample rate


def transcribe_speech(device=AUDIO_DEVICE, sample_rate=SCARLETT_SAMPLE_RATE, duration=RECORDING_DURATION):
    """Record audio and transcribe it"""
    recognizer = KaldiRecognizer(model, sample_rate)
    
    print("Listening...")
    audio_data = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype='int16',
        device=device
    )
    sd.wait()
    
    # Process audio
    audio_bytes = audio_data.tobytes()
    recognizer.AcceptWaveform(audio_bytes)
    result = json.loads(recognizer.Result())
    
    return result.get('text', '')

# Get the result
result = json.loads(recognizer.Result())
text = result.get('text', '')
print(f"You said: {text}")