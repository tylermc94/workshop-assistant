import sys
import os
import time
import logging
import sounddevice as sd
import struct
import pvporcupine
import numpy as np
from scipy import signal

logger = logging.getLogger(__name__)

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.secrets import PORCUPINE_ACCESS_KEY
from config.settings import WAKE_WORD_MODEL, WAKE_WORD_SENSITIVITY, SCARLETT_SAMPLE_RATE
from audio_devices import resolve_input_device

# Get the absolute path to the model file
base_dir = os.path.dirname(os.path.dirname(__file__))
model_path = os.path.join(base_dir, WAKE_WORD_MODEL)

porcupine = pvporcupine.create(
    access_key=PORCUPINE_ACCESS_KEY,
    keyword_paths=[model_path],
    #keywords=['porcupine'],  # Built-in wake word
    sensitivities= [WAKE_WORD_SENSITIVITY],  # Sensitivity between 0 and 1
)

# Porcupine wants 16000 Hz
SAMPLE_RATE = porcupine.sample_rate
FRAME_LENGTH = porcupine.frame_length

# Scarlett runs at 48000 Hz
samples_needed = int(FRAME_LENGTH * SCARLETT_SAMPLE_RATE / SAMPLE_RATE)

#print(f"Porcupine sample rate: {SAMPLE_RATE}")
#print(f"Frame length: {FRAME_LENGTH}")
#print(f"Scarlett sample rate: {SCARLETT_SAMPLE_RATE}")
#print(f"Samples needed from Scarlett: {samples_needed}")

# Capture audio and detect wake word
def listen_for_wake_word():
    """Listen until wake word is detected, then return."""
    device = resolve_input_device()
    while True:
        try:
            with sd.InputStream(
                samplerate=SCARLETT_SAMPLE_RATE,
                channels=1,
                dtype='int16',
                device=device,
                blocksize=samples_needed,
            ) as stream:
                while True:
                    audio_frame, _ = stream.read(samples_needed)
                    audio_resampled = signal.resample(audio_frame.flatten(), FRAME_LENGTH)
                    keyword_index = porcupine.process(audio_resampled.astype('int16').tolist())
                    if keyword_index >= 0:
                        return
        except Exception as e:
            logger.warning(f"Wake word listener audio error: {e} — retrying in 1s")
            time.sleep(1)
            # Re-resolve in case a USB re-plug changed the device index.
            device = resolve_input_device()
            logger.warning(f"Re-resolved wake word input device to index {device} after audio error")


def listen_for_wake_word_stoppable(stop_event):
    """Listen for wake word, returning True if detected or False if stop_event is set."""
    device = resolve_input_device()
    while not stop_event.is_set():
        try:
            with sd.InputStream(
                samplerate=SCARLETT_SAMPLE_RATE,
                channels=1,
                dtype='int16',
                device=device,
                blocksize=samples_needed,
            ) as stream:
                while not stop_event.is_set():
                    audio_frame, _ = stream.read(samples_needed)
                    if stop_event.is_set():
                        return False
                    audio_resampled = signal.resample(audio_frame.flatten(), FRAME_LENGTH)
                    keyword_index = porcupine.process(audio_resampled.astype('int16').tolist())
                    if keyword_index >= 0:
                        return True
        except Exception as e:
            if stop_event.is_set():
                return False
            logger.warning(f"Stoppable wake word listener audio error: {e} — retrying in 1s")
            time.sleep(1)
            # Re-resolve in case a USB re-plug changed the device index.
            device = resolve_input_device()
            logger.warning(f"Re-resolved wake word input device to index {device} after audio error")
    return False