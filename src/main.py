import os
os.environ['ORT_LOGGING_LEVEL'] = '3'

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import threading
from config.logging_config import setup_logging

setup_logging()

import wake_word
import speech_to_text
import intent_recognition
import text_to_speech
import logging
from config.settings import USE_DYNAMIC_RECORDING, API_ENABLED

logger = logging.getLogger(__name__)

STOP_COMMANDS = {"stop", "enough", "quiet", "silence", "cancel", "that's enough", "shut up"}

def is_stop_command(text):
    text_lower = text.lower().strip()
    return any(cmd in text_lower for cmd in STOP_COMMANDS)

async def voice_pipeline():
    """Main voice pipeline loop"""
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

        if not text.strip():
            logger.info("Empty transcription, ignoring")
            continue

        print(f"You said: {text}")
        print("Thinking...")

        result = await intent_recognition.classify_intent(text, source="voice")
        logger.info(f"Intent recognition result: {result}")

        print(f'"{result}"')

        # Run TTS and wake word listener concurrently so "Hey Forge, stop" can interrupt
        stop_event = threading.Event()
        speak_task = asyncio.create_task(asyncio.to_thread(text_to_speech.speak, result))
        interrupt_task = asyncio.create_task(
            asyncio.to_thread(wake_word.listen_for_wake_word_stoppable, stop_event)
        )

        done, pending = await asyncio.wait(
            [speak_task, interrupt_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        if interrupt_task in done and not interrupt_task.cancelled() and interrupt_task.result():
            # Wake word detected while speaking — stop TTS immediately
            text_to_speech.interrupt()
            # Wait for speak thread to exit cleanly before touching the mic
            await asyncio.gather(*pending, return_exceptions=True)
            logger.info("TTS interrupted by wake word during playback")

            # Listen for the stop/continue command
            print("Interrupted - listening for command...")
            stop_text = await asyncio.to_thread(speech_to_text.transcribe_short)
            logger.info(f"Post-interrupt command: '{stop_text}'")

            if is_stop_command(stop_text):
                logger.info("Stop command confirmed — returning to wake word listen")
                continue

            # Not a stop word — treat as a new query
            if stop_text.strip():
                print(f"New query after interrupt: {stop_text}")
                new_result = await intent_recognition.classify_intent(stop_text, source="voice")
                logger.info(f"New intent result: {new_result}")
                print(f'"{new_result}"')
                await asyncio.to_thread(text_to_speech.speak, new_result)
        else:
            # TTS finished naturally — signal the wake word listener and wait for it to exit
            stop_event.set()
            await asyncio.gather(*pending, return_exceptions=True)
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