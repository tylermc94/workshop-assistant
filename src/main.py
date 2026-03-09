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
from config.settings import USE_DYNAMIC_RECORDING, API_ENABLED

logger = logging.getLogger(__name__)

# Flag to track wake word detection
wake_word_detected_during_speech = False

def check_for_interrupt():
    """Check if wake word was detected (for interrupting TTS)"""
    global wake_word_detected_during_speech
    return wake_word_detected_during_speech

async def voice_pipeline():
    """Main voice pipeline loop"""
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

        result = await intent_recognition.classify_intent(text, source="voice")
        logger.info(f"Intent recognition result: {result}")

        print(f'"{result}"')

        # Simple speak without interrupt checking (for now)
        await asyncio.to_thread(text_to_speech.speak, result)

        logger.info("Response spoken")


async def main():
    """Main entry point - run voice pipeline and API server concurrently"""
    tasks = []

    # Always run voice pipeline
    tasks.append(asyncio.create_task(voice_pipeline()))
    logger.info("Started voice pipeline")

    # Conditionally start API server
    if API_ENABLED:
        from api_server import start_api_server
        tasks.append(asyncio.create_task(start_api_server()))
        logger.info("Starting API server")
    else:
        logger.info("API server disabled in config")

    # Run all tasks concurrently
    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("Shutting down Workshop Forge...")
        # Cancel all tasks
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

asyncio.run(main())