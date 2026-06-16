"""Tests for the timer skill (Phase 4: alarm-stop bug + timer cancellation).

Covers the pure parse/format helpers and the three stop_alarm states:
silence a ringing alarm, cancel a pending timer, or report nothing active.
"""
import asyncio
import contextlib

import skills.timer as timer


# --- pure helpers ---------------------------------------------------------

def test_parse_time_expression():
    assert timer.parse_time_expression("two minutes and thirty seconds") == 150
    assert timer.parse_time_expression("1 hour") == 3600
    assert timer.parse_time_expression("gibberish") == 0


def test_format_seconds_to_readable():
    assert timer.format_seconds_to_readable(150) == "2 minutes and 30 seconds"
    assert timer.format_seconds_to_readable(3600) == "1 hour"
    assert timer.format_seconds_to_readable(0) == "0 seconds"


# --- stop_alarm state machine --------------------------------------------

def test_stop_alarm_when_nothing_active():
    timer._alarm_process = None
    timer._timer_task = None
    assert timer.stop_alarm() == "No timer or alarm is active."


def test_stop_alarm_silences_ringing_alarm():
    class FakeProc:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

    fake = FakeProc()
    timer._alarm_process = fake
    timer._timer_task = None

    assert timer.stop_alarm() == "Alarm stopped."
    assert fake.terminated is True
    assert timer._alarm_process is None


def test_stop_alarm_cancels_pending_timer():
    async def run():
        timer._alarm_process = None
        msg = await timer.set_timer("ten minutes")
        assert "Timer set" in msg
        task = timer._timer_task
        assert task is not None and not task.done()

        assert timer.stop_alarm() == "Timer cancelled."

        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert task.cancelled()

    asyncio.run(run())
