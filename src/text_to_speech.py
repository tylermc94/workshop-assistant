import sys
import os
import subprocess
import wave
import tempfile
import numpy as np
from piper import PiperVoice

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import AUDIO_OUTPUT_DEVICE, TTS_MODEL_PATH

# Load TTS voice model
voice = PiperVoice.load(TTS_MODEL_PATH)

def synthesize_speech(text):
    """Convert text to audio using Piper TTS"""
    audio_data = []
    sample_rate = None
    
    for chunk in voice.synthesize(text):
        audio_data.append(chunk.audio_int16_bytes)
        if sample_rate is None:
            sample_rate = chunk.sample_rate
    
    # Combine chunks and convert to numpy array
    audio_bytes = b''.join(audio_data)
    audio = np.frombuffer(audio_bytes, dtype=np.int16)
    
    return audio, sample_rate

def speak(text):
    """Synthesize and play text as speech"""
    audio, sample_rate = synthesize_speech(text)
    
    # Create temporary wav file
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        with wave.open(tmp.name, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio.tobytes())
        
        # Play with aplay to specific device
        subprocess.run(['aplay', '-D', f'plughw:{AUDIO_OUTPUT_DEVICE},0', tmp.name])
        
        # Clean up temp file
        os.unlink(tmp.name)