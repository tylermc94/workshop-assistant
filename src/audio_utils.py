import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import wave
import io
import base64
import tempfile
import subprocess
import logging
from config.settings import TTS_MODEL_PATH
from tts_formatter import format_for_speech

logger = logging.getLogger(__name__)

def wav_bytes_to_numpy(wav_bytes, target_sample_rate=48000):
    """
    Convert WAV bytes to numpy array for STT processing.

    Args:
        wav_bytes (bytes): WAV file content as bytes
        target_sample_rate (int): Target sample rate (default: 48000 for Scarlett)

    Returns:
        numpy.ndarray: Audio data as numpy array (int16, mono)
    """
    # Create a BytesIO object from the bytes
    wav_io = io.BytesIO(wav_bytes)

    # Open with wave module
    with wave.open(wav_io, 'rb') as wav_file:
        # Get audio properties
        frames = wav_file.getnframes()
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()

        logger.info(f"Input WAV: {frames} frames, {sample_rate}Hz, {channels}ch, {sample_width}bytes/sample")

        # Read raw audio data
        audio_bytes = wav_file.readframes(frames)

    # Convert to numpy array based on sample width
    if sample_width == 1:
        audio_array = np.frombuffer(audio_bytes, dtype=np.uint8)
        # Convert to int16 range
        audio_array = (audio_array.astype(np.int16) - 128) * 256
    elif sample_width == 2:
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
    elif sample_width == 4:
        audio_array = np.frombuffer(audio_bytes, dtype=np.int32)
        # Convert to int16 range
        audio_array = (audio_array / 65536).astype(np.int16)
    else:
        raise ValueError(f"Unsupported sample width: {sample_width}")

    # Handle stereo to mono conversion
    if channels == 2:
        # Convert stereo to mono by averaging channels
        audio_array = audio_array.reshape(-1, 2)
        audio_array = np.mean(audio_array, axis=1).astype(np.int16)
    elif channels > 2:
        # Take first channel for multi-channel audio
        audio_array = audio_array[::channels]

    # Resample if necessary (simple approach - for production might want to use librosa)
    if sample_rate != target_sample_rate:
        logger.warning(f"Sample rate mismatch: {sample_rate}Hz -> {target_sample_rate}Hz. Simple resampling applied.")
        # Simple linear resampling (not ideal but functional)
        old_length = len(audio_array)
        new_length = int(old_length * target_sample_rate / sample_rate)
        indices = np.linspace(0, old_length - 1, new_length)
        audio_array = np.interp(indices, np.arange(old_length), audio_array.astype(float)).astype(np.int16)

    logger.info(f"Processed audio: {len(audio_array)} samples at {target_sample_rate}Hz")
    return audio_array


def text_to_audio_base64(text):
    """
    Convert text to speech and return as base64-encoded WAV.

    Args:
        text (str): Text to convert to speech

    Returns:
        str: Base64-encoded WAV file content
    """
    logger.info(f"Converting text to speech: {text[:50]}...")

    # Format for better TTS pronunciation
    formatted_text = format_for_speech(text)
    logger.debug(f"Formatted for TTS: {formatted_text}")

    # Generate speech using Piper
    piper_process = subprocess.Popen(
        ['piper', '--model', TTS_MODEL_PATH, '--output-raw'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )

    raw_audio_data, _ = piper_process.communicate(input=formatted_text.encode('utf-8'))

    if piper_process.returncode != 0:
        logger.error("Piper TTS failed")
        raise RuntimeError("TTS generation failed")

    # Convert raw audio to WAV format
    # Piper outputs 22050Hz, 16-bit mono raw audio
    wav_bytes = raw_audio_to_wav(raw_audio_data, sample_rate=22050)

    # Encode as base64
    base64_audio = base64.b64encode(wav_bytes).decode('utf-8')

    logger.info(f"Generated TTS audio: {len(wav_bytes)} bytes WAV -> {len(base64_audio)} bytes base64")
    return base64_audio


def raw_audio_to_wav(raw_audio_data, sample_rate=22050, channels=1, sample_width=2):
    """
    Convert raw audio data to WAV format.

    Args:
        raw_audio_data (bytes): Raw audio data
        sample_rate (int): Sample rate (default: 22050 for Piper)
        channels (int): Number of channels (default: 1 for mono)
        sample_width (int): Sample width in bytes (default: 2 for 16-bit)

    Returns:
        bytes: WAV file content as bytes
    """
    # Create WAV file in memory
    wav_buffer = io.BytesIO()

    with wave.open(wav_buffer, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(raw_audio_data)

    wav_buffer.seek(0)
    return wav_buffer.read()