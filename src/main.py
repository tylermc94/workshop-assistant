import asyncio
import wake_word
import speech_to_text
import intent_recognition
from config.settings import USE_DYNAMIC_RECORDING

async def main():
    if USE_DYNAMIC_RECORDING:
        transcribe = speech_to_text.transcribe_speech_dynamic
    else:
        transcribe = speech_to_text.transcribe_speech
    
    while True:
        print("Listening for wake word...")
        await asyncio.to_thread(wake_word.listen_for_wake_word)
        print("Wake word detected! Speak now...")
        text = await asyncio.to_thread(transcribe)
        print(f"You said: {text}")
        intent = await intent_recognition.classify_intent(text)
        print(f"Intent: {intent}")

asyncio.run(main())