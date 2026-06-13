"""Tests for intent routing.

Focused on Phase 1, item 1: an unmatched query is forwarded to Claude via
`asyncio.to_thread`, so the (synchronous) SDK call runs off the event loop.
We stub `ask_claude` so nothing hits the network and assert the result flows
back through the await.
"""
import asyncio

import pytest

import intent_recognition
import claude_integration
import query_logger


def test_unmatched_query_is_forwarded_to_claude(monkeypatch):
    monkeypatch.setattr(query_logger, "log_query", lambda *a, **k: None)
    monkeypatch.setattr(
        claude_integration, "ask_claude",
        lambda text, source="voice": f"CLAUDE:{text}",
    )

    result = asyncio.run(intent_recognition.classify_intent("tell me about kerf width", source="api"))
    assert result == "CLAUDE:tell me about kerf width"


@pytest.mark.parametrize("phrase", [
    "stop alarm", "please stop timer", "turn off alarm",
    "stop the timer", "cancel the timer",
])
def test_alarm_phrases_reach_the_alarm_handler(monkeypatch, phrase):
    # Previously these were swallowed by STOP_TRIGGERS ("stop") and never ran.
    monkeypatch.setattr(query_logger, "log_query", lambda *a, **k: None)
    monkeypatch.setattr(intent_recognition.timer, "stop_alarm", lambda: "ALARM_STOPPED")
    result = asyncio.run(intent_recognition.classify_intent(phrase, source="api"))
    assert result == "ALARM_STOPPED"


def test_bare_stop_is_a_dismiss_not_the_alarm(monkeypatch):
    monkeypatch.setattr(query_logger, "log_query", lambda *a, **k: None)
    cleared = {"called": False}
    monkeypatch.setattr(intent_recognition.claude_integration, "clear_history",
                        lambda src: cleared.__setitem__("called", True))

    def _fail():
        raise AssertionError("alarm handler must not run for a bare 'stop'")
    monkeypatch.setattr(intent_recognition.timer, "stop_alarm", _fail)

    result = asyncio.run(intent_recognition.classify_intent("stop", source="api"))
    assert result == "Got it."
    assert cleared["called"] is True
