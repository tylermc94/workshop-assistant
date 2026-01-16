import sys
import os
import sounddevice as sd
from vosk import Model, KaldiRecognizer
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import AUDIO_DEVICE, SCARLETT_SAMPLE_RATE, RECORDING_DURATION, VOSK_MODEL, SILENCE_THRESHOLD, CHUNK_SIZE

SILENCE_DURATION = 0

# Initialize Vosk
base_dir = os.path.dirname(os.path.dirname(__file__))
model_file_path = os.path.join(base_dir, VOSK_MODEL)
model = Model(model_file_path)

def transcribe_speech(device=AUDIO_DEVICE, sample_rate=SCARLETT_SAMPLE_RATE, duration=RECORDING_DURATION):
    """Record audio and transcribe it"""

    global SILENCE_DURATION
    
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

def transcribe_speech_dynamic(device=AUDIO_DEVICE, sample_rate=SCARLETT_SAMPLE_RATE):
    """Record until user stops speaking"""

    global SILENCE_DURATION

    recognizer = KaldiRecognizer(model, sample_rate)
    
    print("Listening...")
    
    with sd.InputStream(samplerate=sample_rate, channels=1, 
                        dtype='int16', device=device) as stream:
        
        while True:
            audio_chunk, overflowed = stream.read(CHUNK_SIZE)
            
            if recognizer.AcceptWaveform(audio_chunk.tobytes()):
                # Got final result - speech segment ended
                result = json.loads(recognizer.Result())
                if result.get('text'):
                    return result['text']
                    
            else:
                # Partial result - still speaking
                partial = json.loads(recognizer.PartialResult())
                if partial.get('partial'):
                    # User is speaking, reset silence counter
                    SILENCE_DURATION = 0
                    print(f"Partial: {partial['partial']}")  # Optional: show what you're saying
                else:
                    # Silence detected
                    SILENCE_DURATION += 0.1
                    
                    if SILENCE_DURATION >= SILENCE_THRESHOLD:
                        # User stopped talking
                        final = json.loads(recognizer.FinalResult())
                        return final.get('text', '')