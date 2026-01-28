import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from config.logging_config import setup_logging

# Set up logging first thing
setup_logging()

import wake_word
import speech_to_text
import intent_recognition
import text_to_speech
import logging
from config.settings import USE_DYNAMIC_RECORDING

logger = logging.getLogger(__name__)

async def main():
    if USE_DYNAMIC_RECORDING:
        transcribe = speech_to_text.transcribe_speech_dynamic
    else:
        transcribe = speech_to_text.transcribe_speech
    
    while True:
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
        text_to_speech.speak(result)
        logger.info("Response spoken")

asyncio.run(main())