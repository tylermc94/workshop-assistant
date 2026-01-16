import wake_word
import speech_to_text

while True:
    print("Listening for wake word...")
    wake_word.listen_for_wake_word()
    
    print("Wake word detected! Speak now...")
    text = speech_to_text.transcribe_speech_dynamic()
    
    print(f"You said: {text}")