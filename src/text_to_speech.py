import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import numpy as np
import sounddevice as sd
from piper import PiperVoice
from config.settings import TTS_MODEL_PATH, AUDIO_OUTPUT_SD_DEVICE
from tts_formatter import format_for_speech

logger = logging.getLogger(__name__)

# Load model once at startup — this is the expensive step (~1.3s), so we do it here
logger.info(f"Loading Piper TTS model: {TTS_MODEL_PATH}")
_voice = PiperVoice.load(TTS_MODEL_PATH)
logger.info("Piper TTS model loaded")

_interrupt_flag = False


def interrupt():
    """Stop current speech immediately"""
    global _interrupt_flag
    _interrupt_flag = True
    sd.stop()
    logger.info("TTS interrupted")


def synthesize_to_wav(text):
    """
    Synthesize text and return WAV bytes (used by API server for base64 audio responses).
    Reuses the already-loaded voice model.
    """
    import io, wave
    formatted_text = format_for_speech(text)
    chunks = list(_voice.synthesize(formatted_text))
    if not chunks:
        return b''

    audio = np.concatenate([c.audio_int16_array for c in chunks])
    sample_rate = chunks[0].sample_rate

    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())
    buf.seek(0)
    return buf.read()


def speak(text, check_interrupt_callback=None):
    """
    Synthesize text and play it via sounddevice.
    Model is pre-loaded so synthesis starts immediately (~100-500ms vs ~1.7s with subprocess).
    """
    global _interrupt_flag
    _interrupt_flag = False

    logger.info(f"Speaking: {text}")

    formatted_text = format_for_speech(text)
    logger.info(f"Formatted for TTS: {formatted_text}")

    chunks = list(_voice.synthesize(formatted_text))
    if not chunks or _interrupt_flag:
        return

    audio = np.concatenate([c.audio_int16_array for c in chunks])
    sample_rate = chunks[0].sample_rate

    sd.play(audio, samplerate=sample_rate, device=AUDIO_OUTPUT_SD_DEVICE)
    sd.wait()
