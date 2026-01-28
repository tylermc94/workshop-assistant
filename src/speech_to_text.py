import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sounddevice as sd
import numpy as np
import logging

from config.settings import (
    STT_ENGINE,
    SCARLETT_SAMPLE_RATE, 
    RECORDING_DURATION,
    AUDIO_INPUT_DEVICE,
    # Vosk settings
    VOSK_MODEL_PATH,
    # Whisper settings
    WHISPER_MODEL_SIZE,
    WHISPER_COMPUTE_TYPE,
    DYNAMIC_SILENCE_THRESHOLD,
    DYNAMIC_MAX_DURATION,
    DYNAMIC_CHUNK_SIZE,
    DYNAMIC_ENERGY_THRESHOLD
)

logger = logging.getLogger(__name__)

# Initialize the appropriate STT engine based on settings
if STT_ENGINE == "vosk":
    import vosk
    import json
    
    logger.info(f"Loading Vosk model from {VOSK_MODEL_PATH}")
    vosk_model = vosk.Model(VOSK_MODEL_PATH)
    recognizer = vosk.KaldiRecognizer(vosk_model, SCARLETT_SAMPLE_RATE)
    logger.info("Vosk model loaded successfully")
    
elif STT_ENGINE == "whisper":
    from faster_whisper import WhisperModel
    
    logger.info(f"Loading Whisper model: {WHISPER_MODEL_SIZE}")
    whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type=WHISPER_COMPUTE_TYPE)
    logger.info("Whisper model loaded successfully")
    
else:
    raise ValueError(f"Unknown STT_ENGINE: {STT_ENGINE}. Must be 'vosk' or 'whisper'")


def transcribe_speech():
    """
    Records audio and transcribes it using the configured STT engine.
    Returns the transcribed text as a string.
    """
    logger.info("Recording audio...")
    #print("Listening...")
    
    # Record audio
    audio = sd.rec(
        int(RECORDING_DURATION * SCARLETT_SAMPLE_RATE),
        samplerate=SCARLETT_SAMPLE_RATE,
        channels=1,
        dtype='int16',
        device=AUDIO_INPUT_DEVICE
    )
    sd.wait()
    
    logger.info("Recording complete, transcribing...")
    
    if STT_ENGINE == "vosk":
        return _transcribe_with_vosk(audio)
    elif STT_ENGINE == "whisper":
        return _transcribe_with_whisper(audio)


def _transcribe_with_vosk(audio):
    """Transcribe audio using Vosk"""
    recognizer.AcceptWaveform(audio.tobytes())
    result = json.loads(recognizer.FinalResult())
    text = result.get("text", "")
    logger.info(f"Vosk transcription: {text}")
    return text


def _transcribe_with_whisper(audio):
    """Transcribe audio using Whisper"""
    import tempfile
    import wave
    
    # Whisper needs a file, so create temp WAV
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        with wave.open(tmp.name, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(SCARLETT_SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        
        # Transcribe
        segments, info = whisper_model.transcribe(tmp.name, beam_size=5)
        
        # Combine all segments into single text
        text = " ".join([segment.text for segment in segments]).strip()
        
        # Remove punctuation (Whisper adds periods, commas, etc.)
        text = text.rstrip('.,!?;:')
        
        # Cleanup
        os.unlink(tmp.name)
        
    logger.info(f"Whisper transcription: {text}")
    return text

def transcribe_speech_dynamic():
    """
    Records audio dynamically, stopping when silence is detected.
    Returns the transcribed text as a string.
    """
    logger.info("Starting dynamic recording...")
    #print("Listening...")
    
    audio_buffer = []
    silence_duration = 0
    total_duration = 0
    chunk_duration = DYNAMIC_CHUNK_SIZE / SCARLETT_SAMPLE_RATE  # Time per chunk in seconds
    
    # Start streaming audio
    with sd.InputStream(
        samplerate=SCARLETT_SAMPLE_RATE,
        channels=1,
        dtype='int16',
        device=AUDIO_INPUT_DEVICE,
        blocksize=DYNAMIC_CHUNK_SIZE
    ) as stream:
        
        while True:
            # Read one chunk
            chunk, overflowed = stream.read(DYNAMIC_CHUNK_SIZE)
            
            if overflowed:
                logger.warning("Audio buffer overflow - some audio may be lost")
            
            # Add chunk to buffer
            audio_buffer.append(chunk)
            total_duration += chunk_duration
            
            # Calculate energy (loudness) of this chunk
            energy = np.abs(chunk).mean()
            
            # Check if this chunk is silence
            if energy < DYNAMIC_ENERGY_THRESHOLD:
                silence_duration += chunk_duration
                logger.debug(f"Silence detected: {silence_duration:.2f}s")
            else:
                # Reset silence counter if we hear sound
                silence_duration = 0
            
            # Stop conditions
            if silence_duration >= DYNAMIC_SILENCE_THRESHOLD:
                logger.info(f"Silence threshold reached ({DYNAMIC_SILENCE_THRESHOLD}s)")
                break
            
            if total_duration >= DYNAMIC_MAX_DURATION:
                logger.warning(f"Max recording duration reached ({DYNAMIC_MAX_DURATION}s)")
                break
    
    # Combine all chunks into single audio array
    audio = np.concatenate(audio_buffer)
    
    logger.info(f"Recording complete: {total_duration:.2f}s total, transcribing...")
    
    # Transcribe with appropriate engine
    if STT_ENGINE == "vosk":
        return _transcribe_with_vosk(audio)
    elif STT_ENGINE == "whisper":
        return _transcribe_with_whisper(audio)