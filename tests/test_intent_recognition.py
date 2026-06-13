"""Tests for intent routing.

Focused on Phase 1, item 1: an unmatched query is forwarded to Claude via
`asyncio.to_thread`, so the (synchronous) SDK call runs off the event loop.
We stub `ask_claude` so nothing hits the network and assert the result flows
back through the await.
"""
import asyncio

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
