import asyncio
import skills.timer as timer
import skills.calculator as calculator

# Define triggers at module level
CALCULATOR_TRIGGERS = ["what is", "calculate", "how much is"]
CALENDAR_TRIGGERS = ["what time is it"]
HOME_ASSISTANT_TRIGGERS = ["turn on", "turn off"]
TIMER_TRIGGERS = ["set a timer", "timer for", "start a timer"]

def strip_trigger(text, triggers):
    """Remove trigger phrase from text"""
    text_lower = text.lower()
    for trigger in triggers:
        if trigger in text_lower:
            text_lower = text_lower.replace(trigger, "").strip()
            break
    return text_lower

async def classify_intent(text):
    text_lower = text.lower()
    
    if any(trigger in text_lower for trigger in TIMER_TRIGGERS):
        clean_text = strip_trigger(text, TIMER_TRIGGERS)
        result = await timer.set_timer(clean_text)
        return result
    if any(trigger in text_lower for trigger in CALCULATOR_TRIGGERS):
        clean_text = strip_trigger(text, CALCULATOR_TRIGGERS)
        result = calculator.calculate(clean_text)
        return result
    if any(trigger in text_lower for trigger in CALENDAR_TRIGGERS):
        return "calendar"
    if any(trigger in text_lower for trigger in HOME_ASSISTANT_TRIGGERS):
        return "Home Assistant"
    else:
        return "unknown"