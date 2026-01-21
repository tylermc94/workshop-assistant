import asyncio
import skills.timer as timer
import skills.calculator as calculator
import skills.calendar as calendar
import skills.home_assistant as home_assistant

# Define triggers at module level
CALENDAR_TRIGGERS = ["what time is it", "what's the time", "what's the date", "what day is it"]
CALCULATOR_TRIGGERS = ["what is", "what's", "calculate", "how much is"]
HOME_ASSISTANT_TRIGGERS = ["turn on", "turn off"]
TIMER_TRIGGERS = ["set a timer", "timer for", "start a timer"]
ALARM_TRIGGERS = ["stop alarm", "stop timer", "turn off alarm"]

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
    
    # Check calendar BEFORE calculator (more specific)
    if any(trigger in text_lower for trigger in CALENDAR_TRIGGERS):
        result = calendar.calendar_query(text)
        return result
    
    # Calculator checks after (less specific)
    if any(trigger in text_lower for trigger in CALCULATOR_TRIGGERS):
        clean_text = strip_trigger(text, CALCULATOR_TRIGGERS)
        try:
            result = calculator.calculate(clean_text)
            return str(result)
        except ValueError as e:
            return "Sorry, I couldn't calculate that. Try rephrasing your question."
    
    if any(trigger in text_lower for trigger in TIMER_TRIGGERS):
        clean_text = strip_trigger(text, TIMER_TRIGGERS)
        result = await timer.set_timer(clean_text)
        return result

    if any(trigger in text_lower for trigger in HOME_ASSISTANT_TRIGGERS):
        return "Home Assistant"
    
    if any(trigger in text_lower for trigger in ALARM_TRIGGERS):
        result = timer.stop_alarm()
        return result
    else:
        return "Sorry, I didn't understand that."