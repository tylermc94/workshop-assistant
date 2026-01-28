import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import asyncio
from word2number import w2n
import subprocess
from config.settings import TIMER_ALARM_SOUND, AUDIO_OUTPUT_DEVICE, TIMER_ALARM_REPEATS

from config.logging_config import setup_logging
setup_logging()
import logging
logger = logging.getLogger(__name__)

# Global to track alarm process
alarm_process = None

async def start_timer(duration_seconds):
    """Run a timer for the specified duration"""
    logger.info(f"Timer started for {duration_seconds} seconds")
    await asyncio.sleep(duration_seconds)
    logger.info("Timer finished!")
    
    # Play alarm multiple times (suppress output)
    for _ in range(TIMER_ALARM_REPEATS):
        subprocess.run([
            'aplay', 
            '-D', f'plughw:{AUDIO_OUTPUT_DEVICE},0',
            TIMER_ALARM_SOUND
        ], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

def stop_alarm():
    """Stop the alarm if it's playing"""
    global alarm_process
    
    if alarm_process is not None:
        alarm_process.terminate()  # Stop the process
        alarm_process = None
        logger.info("Alarm stopped")
        return "Alarm stopped"
    else:
        return "No alarm is playing"

def parse_time_expression(expression):
    """
    Parses a time expression in natural language and converts it to seconds.
    
    Args:
        expression (str): The time expression in natural language (e.g., "2 minutes and 30 seconds").
        
    Returns:
        int: The total time in seconds.
    """
    time_units = {
        'second': 1,
        'seconds': 1,
        'minute': 60,
        'minutes': 60,
        'hour': 3600,
        'hours': 3600,
        'day': 86400,
        'days': 86400
    }
    
    total_seconds = 0
    parts = expression.replace('and', ',').split(',')
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        words = part.split()
        if len(words) < 2:
            continue
        
        try:
            number = w2n.word_to_num(' '.join(words[:-1]))
            unit = words[-1].lower()
            
            if unit in time_units:
                total_seconds += number * time_units[unit]
        except ValueError:
            continue
    
    return total_seconds

def format_seconds_to_readable(seconds):
    """
    Converts seconds into a human-readable format.
    Args:
        seconds (int): The total time in seconds.
    Returns:
        str: The time in a human-readable format (e.g., "2 minutes and 30 seconds").
    """
    intervals = (
        ('day', 86400),
        ('hour', 3600),
        ('minute', 60),
        ('second', 1),
    )
    
    result = []
    
    for name, count in intervals:
        value = seconds // count
        if value:
            seconds -= value * count
            if value == 1:
                result.append(f"{value} {name}")
            else:
                result.append(f"{value} {name}s")
    
    return ' and '.join(result) if result else '0 seconds'

async def set_timer(text):
    duration_seconds = parse_time_expression(text)
    if duration_seconds > 0:
        asyncio.create_task(start_timer(duration_seconds))
        readable_time = format_seconds_to_readable(duration_seconds)
        return f"Timer set for {readable_time}."
    else:
        return "Could not parse a valid time duration from the input."