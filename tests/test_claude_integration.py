"""Tests for the ANSWER-path Claude call error handling.

These stub the Anthropic SDK client so nothing hits the network. They check
that each API error type maps to its own friendly spoken message (Phase 1,
item 2) and that the budget hard-limit short-circuit works.
"""
import httpx
import anthropic
import pytest

import claude_integration


_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _response(status):
    return httpx.Response(status, request=_REQUEST)


# (exception instance, substring expected in the spoken reply)
ERROR_CASES = [
    (anthropic.AuthenticationError("bad key", response=_response(401), body=None), "authenticate"),
    (anthropic.NotFoundError("no model", response=_response(404), body=None), "isn't available"),
    (anthropic.RateLimitError("slow down", response=_response(429), body=None), "busy"),
    (anthropic.APIConnectionError(message="conn", request=_REQUEST), "couldn't reach Claude"),
    (anthropic.APIError("generic", request=_REQUEST, body=None), "couldn't reach Claude"),
]


@pytest.mark.parametrize("exc, expected", ERROR_CASES)
def test_ask_claude_maps_each_error_to_its_own_message(monkeypatch, exc, expected):
    monkeypatch.setattr(claude_integration.budget_tracker, "is_limit_reached", lambda: False)

    def boom(*args, **kwargs):
        raise exc

    monkeypatch.setattr(claude_integration.client.messages, "create", boom)

    reply = claude_integration.ask_claude("anything", source="api")
    assert expected in reply


def test_ask_claude_blocks_when_budget_limit_reached(monkeypatch):
    monkeypatch.setattr(claude_integration.budget_tracker, "is_limit_reached", lambda: True)

    # If the SDK were called, this would raise — proving the limit short-circuits first.
    def should_not_run(*args, **kwargs):
        raise AssertionError("Claude was called despite the budget limit")

    monkeypatch.setattr(claude_integration.client.messages, "create", should_not_run)

    reply = claude_integration.ask_claude("anything", source="api")
    assert "budget" in reply.lower()
