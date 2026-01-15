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
    keyword_paths=[model_path],
    #keywords=['porcupine']  # Built-in wake word
    sensitivities= [0.9]  # Sensitivity between 0 and 1
)

SAMPLE_RATE = porcupine.sample_rate
FRAME_LENGTH = porcupine.frame_length

print(f"Porcupine sample rate: {porcupine.sample_rate}")
print(f"Frame length: {porcupine.frame_length}")
print(f"Model loaded from: {model_path}")

# Capture audio and detect wake word
while True:
    #print("Listening...")
    # Record one frame of audio
    # Porcupine expects mono audio (1 channel) as int16
    AUDIO_DEVICE = 1

    audio_frame = sd.rec(
        FRAME_LENGTH, 
        samplerate=SAMPLE_RATE, 
        channels=1,
        dtype='int16',
        device=AUDIO_DEVICE
    )
    sd.wait()  # Wait for recording to finish

    # Check audio level
    audio_array = audio_frame.flatten()
    max_level = max(abs(audio_array))
    #print(f"Audio level: {max_level}")  # Should spike when you talk
    
    audio_list = audio_array.tolist()
    # Convert to the format Porcupine expects (flat list)
    audio_frame = audio_frame.flatten().tolist()
    
    # Feed to Porcupine
    keyword_index = porcupine.process(audio_frame)
    
    # If wake word detected (returns >= 0)
    if keyword_index >= 0:
        print("Wake word detected!")