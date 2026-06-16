import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import asyncio
from word2number import w2n
from config.settings import TIMER_ALARM_SOUND, TIMER_ALARM_REPEATS
from audio_devices import resolve_output_device

from config.logging_config import setup_logging
setup_logging()
import logging
logger = logging.getLogger(__name__)

# Module state. Only one timer/alarm is tracked at a time (matches prior behavior).
_alarm_process = None   # the running aplay subprocess while the alarm is sounding
_alarm_stop = False     # set by stop_alarm() to break the repeat loop
_timer_task = None      # the pending asyncio timer task (before it rings)


async def start_timer(duration_seconds):
    """Wait the duration, then sound the alarm.

    Both phases are interruptible by stop_alarm(): a pending timer can be
    cancelled before it rings, and a sounding alarm can be silenced. Playback
    uses a non-blocking subprocess so it never freezes the event loop (the old
    blocking subprocess.run inside this async task did).
    """
    global _alarm_process, _alarm_stop, _timer_task
    logger.info(f"Timer started for {duration_seconds} seconds")
    try:
        await asyncio.sleep(duration_seconds)
    except asyncio.CancelledError:
        logger.info("Timer cancelled before it rang")
        raise

    logger.info("Timer finished — sounding alarm")
    _alarm_stop = False
    output_device = resolve_output_device()
    try:
        for _ in range(TIMER_ALARM_REPEATS):
            if _alarm_stop:
                break
            proc = await asyncio.create_subprocess_exec(
                'aplay', '-D', output_device, TIMER_ALARM_SOUND,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            _alarm_process = proc  # exposed so stop_alarm() can terminate it
            await proc.wait()      # await the local handle, not the global
    except asyncio.CancelledError:
        logger.info("Alarm playback cancelled")
    finally:
        _alarm_process = None
        _timer_task = None


def stop_alarm():
    """Silence a ringing alarm, or cancel a pending timer if it hasn't rung yet."""
    global _alarm_process, _alarm_stop, _timer_task

    if _alarm_process is not None:
        _alarm_stop = True  # break the repeat loop so it doesn't re-arm
        try:
            _alarm_process.terminate()
        except ProcessLookupError:
            pass  # already finished
        _alarm_process = None
        logger.info("Alarm stopped")
        return "Alarm stopped."

    if _timer_task is not None and not _timer_task.done():
        _timer_task.cancel()
        _timer_task = None
        logger.info("Timer cancelled")
        return "Timer cancelled."

    return "No timer or alarm is active."

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
    global _timer_task
    duration_seconds = parse_time_expression(text)
    if duration_seconds > 0:
        # Track the task so stop_alarm() can cancel a pending timer.
        _timer_task = asyncio.create_task(start_timer(duration_seconds))
        readable_time = format_seconds_to_readable(duration_seconds)
        return f"Timer set for {readable_time}."
    else:
        return "Could not parse a valid time duration from the input."