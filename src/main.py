import wake_word
import speech_to_text

while True:
    print("Listening for wake word...")
    wake_word.listen_for_wake_word()
    
    print("Wake word detected! Speak now...")
    #text = speech_to_text.transcribe_speech() # Use fixed duration transcription
    text = speech_to_text.transcribe_speech_dynamic() # Use dynamic transcription until silence
    
    print(f"You said: {text}")