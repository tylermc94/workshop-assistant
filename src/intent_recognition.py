def classify_intent(text):
    text_lower = text.lower()
    
    calculator_triggers = ["what is", "calculate", "how much is"]
    calendar_triggers = ["what time is it"]
    home_assistant_triggers = ["turn on", "turn off"]
    
    if any(trigger in text_lower for trigger in calculator_triggers):
        return "calculator"
    if any(trigger in text_lower for trigger in calendar_triggers):
        return "calendar"
    if any(trigger in text_lower for trigger in home_assistant_triggers):
        return "Home Assistant"
    else:
        return "unknown"
    
