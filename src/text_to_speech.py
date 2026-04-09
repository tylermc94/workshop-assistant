import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import subprocess
import logging
import io
import wave
import numpy as np
from piper import PiperVoice
from config.settings import TTS_MODEL_PATH, AUDIO_OUTPUT_DEVICE
from tts_formatter import format_for_speech

logger = logging.getLogger(__name__)

# Load model once at startup — avoids ~1.7s subprocess overhead per call
logger.info(f"Loading Piper TTS model: {TTS_MODEL_PATH}")
_voice = PiperVoice.load(TTS_MODEL_PATH)
logger.info("Piper TTS model loaded")

_interrupt_flag = False
_audio_process = None


def interrupt():
    """Stop current speech immediately"""
    global _interrupt_flag, _audio_process
    _interrupt_flag = True
    if _audio_process:
        _audio_process.kill()
        logger.info("TTS interrupted")


def synthesize_to_wav(text):
    """
    Synthesize text and return WAV bytes (used by API server for base64 audio responses).
    """
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
    Synthesize text with the pre-loaded Piper model and stream to aplay.
    Piper yields one AudioChunk per sentence, so aplay starts playing the
    first sentence while subsequent sentences are still being synthesized.
    """
    global _interrupt_flag, _audio_process
    _interrupt_flag = False

    logger.info(f"Speaking: {text}")

    formatted_text = format_for_speech(text)
    logger.info(f"Formatted for TTS: {formatted_text}")

    sample_rate = _voice.config.sample_rate

    _audio_process = subprocess.Popen(
        ['aplay', '-r', str(sample_rate), '-f', 'S16_LE', '-t', 'raw',
         '-D', f'plughw:{AUDIO_OUTPUT_DEVICE},0'],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    try:
        for chunk in _voice.synthesize(formatted_text):
            if _interrupt_flag:
                break
            _audio_process.stdin.write(chunk.audio_int16_bytes)
        _audio_process.stdin.close()
        _audio_process.wait(timeout=60)
    except BrokenPipeError:
        pass  # Interrupted mid-stream
    except subprocess.TimeoutExpired:
        _audio_process.kill()
        logger.warning("TTS playback timeout")
    except Exception as e:
        logger.error(f"TTS playback error: {e}")

    _audio_process = None
