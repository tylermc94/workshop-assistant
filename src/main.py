import os
os.environ['ORT_LOGGING_LEVEL'] = '3'

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from config.logging_config import setup_logging

setup_logging()

import wake_word
import speech_to_text
import intent_recognition
import text_to_speech
import logging
from config.settings import USE_DYNAMIC_RECORDING

logger = logging.getLogger(__name__)

# Flag to track wake word detection
wake_word_detected_during_speech = False

def check_for_interrupt():
    """Check if wake word was detected (for interrupting TTS)"""
    global wake_word_detected_during_speech
    return wake_word_detected_during_speech

async def main():
    global wake_word_detected_during_speech
    
    if USE_DYNAMIC_RECORDING:
        transcribe = speech_to_text.transcribe_speech_dynamic
    else:
        transcribe = speech_to_text.transcribe_speech
    
    while True:
        wake_word_detected_during_speech = False
        
        print("Listening for wake word...")
        await asyncio.to_thread(wake_word.listen_for_wake_word)
        
        print("Wake word detected! Speak now...")
        logger.info("Wake word detected")
        
        text = await asyncio.to_thread(transcribe)
        logger.info(f"Transcribed text: {text}")
        
        print(f"You said: {text}")
        print("Thinking...")
        
        result = await intent_recognition.classify_intent(text)
        logger.info(f"Intent recognition result: {result}")
        
        print(f'"{result}"')
        
        # Start listening for wake word in background while speaking
        async def listen_during_speech():
            global wake_word_detected_during_speech
            await asyncio.to_thread(wake_word.listen_for_wake_word)
            wake_word_detected_during_speech = True
            logger.info("Wake word detected during speech - interrupting")
        
        listen_task = asyncio.create_task(listen_during_speech())
        
        # Speak with interrupt checking
        await asyncio.to_thread(text_to_speech.speak, result, check_for_interrupt)
        
        # Cancel wake word listening if speech finished naturally
        if not wake_word_detected_during_speech:
            listen_task.cancel()
            try:
                await listen_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Response spoken")

asyncio.run(main())