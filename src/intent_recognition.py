import asyncio
import skills.timer as timer
import skills.calculator as calculator
import skills.calendar as calendar
import skills.home_assistant as home_assistant
import claude_integration
import query_logger
import logging

logger = logging.getLogger(__name__)

# Define triggers at module level
CALENDAR_TRIGGERS = ["what time is it", "what's the time", "what's the date", "what day is it"]
CALCULATOR_TRIGGERS = ["what is", "what's", "calculate", "how much is"]
HOME_ASSISTANT_TRIGGERS = ["turn on", "turn off"]
TIMER_TRIGGERS = ["set a timer for", "timer for", "start a timer"]
ALARM_TRIGGERS = ["stop alarm", "stop timer", "turn off alarm", "stop"]
STOP_TRIGGERS = ["thank you", "thanks", "stop", "never mind", "nevermind", "that's all", "cancel"]  # Add this

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
    
    # Check for stop/acknowledgment commands first (highest priority)
    if any(trigger in text_lower for trigger in STOP_TRIGGERS):
        result = "Got it."
        query_logger.log_query(text, "local_stop", result)
        return result
    
    # Try local skills
    
    # Check calendar BEFORE calculator (more specific)
    if any(trigger in text_lower for trigger in CALENDAR_TRIGGERS):
        result = calendar.calendar_query(text)
        query_logger.log_query(text, "local_calendar", result)
        return result
    
    # Calculator checks after (less specific)
    elif any(trigger in text_lower for trigger in CALCULATOR_TRIGGERS):
        clean_text = strip_trigger(text, CALCULATOR_TRIGGERS)
        try:
            result = calculator.calculate(clean_text)
            query_logger.log_query(text, "local_calculator", str(result))
            return str(result)
        except ValueError as e:
            # Calculator failed, let Claude try
            logger.info(f"Calculator failed: {e}, forwarding to Claude")
            result = claude_integration.ask_claude(text)
            query_logger.log_query(text, "claude_fallback_calc", result, error=str(e))
            return result
    
    elif any(trigger in text_lower for trigger in TIMER_TRIGGERS):
        clean_text = strip_trigger(text, TIMER_TRIGGERS)
        result = await timer.set_timer(clean_text)
        query_logger.log_query(text, "local_timer", result)
        return result

    elif any(trigger in text_lower for trigger in HOME_ASSISTANT_TRIGGERS):
        result = "Home Assistant"
        query_logger.log_query(text, "local_home_assistant", result)
        return result
    
    elif any(trigger in text_lower for trigger in ALARM_TRIGGERS):
        result = timer.stop_alarm()
        query_logger.log_query(text, "local_alarm", result)
        return result
    
    # No local skill matched - ask Claude
    else:
        logger.info(f"No local skill matched, forwarding to Claude: {text}")
        result = claude_integration.ask_claude(text)
        query_logger.log_query(text, "claude", result)
        return result