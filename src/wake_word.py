import sys
import os
import sounddevice as sd
import struct
import pvporcupine

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.secrets import PORCUPINE_ACCESS_KEY

# Get the absolute path to the model file
base_dir = os.path.dirname(os.path.dirname(__file__))  # Gets project root
model_path = os.path.join(base_dir, 'models', 'Hey-Forge_en_raspberry-pi_v4_0_0.ppn')

porcupine = pvporcupine.create(
    access_key=PORCUPINE_ACCESS_KEY,
    keyword_paths=[model_path]
)

SAMPLE_RATE = porcupine.sample_rate
FRAME_LENGTH = porcupine.frame_length

# Capture audio and detect wake word
while True:
    print("Listening...")
    # Record one frame of audio
    # Porcupine expects mono audio (1 channel) as int16
    AUDIO_DEVICE = 2

    audio_frame = sd.rec(
        FRAME_LENGTH, 
        samplerate=SAMPLE_RATE, 
        channels=1,
        dtype='int16',
        device=AUDIO_DEVICE
    )
    sd.wait()  # Wait for recording to finish

    # Convert to the format Porcupine expects (flat list)
    audio_frame = audio_frame.flatten().tolist()
    
    # Feed to Porcupine
    keyword_index = porcupine.process(audio_frame)
    
    # If wake word detected (returns >= 0)
    if keyword_index >= 0:
        print("Wake word detected!")