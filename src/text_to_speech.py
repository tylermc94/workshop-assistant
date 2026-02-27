import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import subprocess
import logging
import threading
from config.settings import TTS_MODEL_PATH, AUDIO_OUTPUT_DEVICE
from tts_formatter import format_for_speech

logger = logging.getLogger(__name__)

# Global flag for interruption
_interrupt_flag = False
_audio_process = None

def interrupt():
    """Signal to interrupt current speech"""
    global _interrupt_flag, _audio_process
    _interrupt_flag = True
    if _audio_process:
        _audio_process.kill()
        logger.info("TTS interrupted by user")

def speak(text, check_interrupt_callback=None):
    """
    Convert text to speech using Piper TTS
    
    Args:
        text: Text to speak
        check_interrupt_callback: Optional function to check if we should interrupt
    """
    global _interrupt_flag, _audio_process
    _interrupt_flag = False
    
    logger.info(f"Speaking: {text}")
    
    # Format for better TTS pronunciation
    formatted_text = format_for_speech(text)
    logger.info(f"Formatted for TTS: {formatted_text}")
    
    # Generate speech
    piper_process = subprocess.Popen(
        ['piper', '--model', TTS_MODEL_PATH, '--output-raw'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )
    
    audio_data, _ = piper_process.communicate(input=formatted_text.encode('utf-8'))
    
    if _interrupt_flag:
        logger.info("TTS interrupted before playback")
        return
    
    # Play audio (can be interrupted)
    _audio_process = subprocess.Popen(
        ['aplay', '-r', '22050', '-f', 'S16_LE', '-t', 'raw', '-D', f'plughw:{AUDIO_OUTPUT_DEVICE},0'],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    # If callback provided, monitor for interrupt
    if check_interrupt_callback:
        def monitor_interrupt():
            while _audio_process.poll() is None:  # While audio still playing
                if check_interrupt_callback():
                    interrupt()
                    break
        
        monitor_thread = threading.Thread(target=monitor_interrupt, daemon=True)
        monitor_thread.start()
    
    # Send audio data
    try:
        _audio_process.communicate(input=audio_data, timeout=30)
    except subprocess.TimeoutExpired:
        _audio_process.kill()
        logger.warning("TTS playback timeout")
    except Exception as e:
        logger.error(f"TTS playback error: {e}")
    
    _audio_process = None