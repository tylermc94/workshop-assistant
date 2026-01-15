import sys
import os
import sounddevice as sd
import struct
import pvporcupine
import numpy as np
from scipy import signal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.secrets import PORCUPINE_ACCESS_KEY

# Get the absolute path to the model file
base_dir = os.path.dirname(os.path.dirname(__file__))
model_path = os.path.join(base_dir, 'models', 'Hey-Forge_en_raspberry-pi_v4_0_0.ppn')

porcupine = pvporcupine.create(
    access_key=PORCUPINE_ACCESS_KEY,
    keyword_paths=[model_path],
    #keywords=['porcupine'],  # Built-in wake word
    sensitivities= [0.9],  # Sensitivity between 0 and 1
)

# Porcupine wants 16000 Hz
SAMPLE_RATE = porcupine.sample_rate
FRAME_LENGTH = porcupine.frame_length

# Scarlett runs at 48000 Hz
SCARLETT_RATE = 48000
samples_needed = int(FRAME_LENGTH * SCARLETT_RATE / SAMPLE_RATE)

AUDIO_DEVICE = 1  # Scarlett

print(f"Porcupine sample rate: {SAMPLE_RATE}")
print(f"Frame length: {FRAME_LENGTH}")
print(f"Scarlett sample rate: {SCARLETT_RATE}")
print(f"Samples needed from Scarlett: {samples_needed}")

# Capture audio and detect wake word
while True:
    # Record from Scarlett at 48000 Hz
    audio_frame = sd.rec(
        samples_needed,  # More samples because higher rate
        samplerate=SCARLETT_RATE,  # Scarlett's native rate
        channels=1,
        dtype='int16',
        device=AUDIO_DEVICE
    )
    sd.wait()

    # Resample from 48000 to 16000 for Porcupine
    audio_resampled = signal.resample(audio_frame.flatten(), FRAME_LENGTH)
    audio_list = audio_resampled.astype('int16').tolist()
    
    # Feed to Porcupine
    keyword_index = porcupine.process(audio_list)
    
    if keyword_index >= 0:
        print("Wake word detected!")