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


class _Block:
    def __init__(self, type, text=None):
        self.type = type
        self.text = text


class _Usage:
    input_tokens = 10
    output_tokens = 5


class _Msg:
    def __init__(self, blocks, stop_reason="end_turn"):
        self.content = blocks
        self.stop_reason = stop_reason
        self.usage = _Usage()
        self.model = "claude-sonnet-4-6"


def _stub_common(monkeypatch):
    monkeypatch.setattr(claude_integration.budget_tracker, "is_limit_reached", lambda: False)
    monkeypatch.setattr(claude_integration.budget_tracker, "record_usage",
                        lambda *a, **k: {"warning": False, "limit_reached": False, "total_cost": 0})
    monkeypatch.setattr(claude_integration, "log_query", lambda q: None)
    claude_integration._history["api"].clear()


def test_ask_claude_returns_last_text_block_and_no_tools_by_default(monkeypatch):
    _stub_common(monkeypatch)
    monkeypatch.setattr(claude_integration, "WEB_SEARCH_ENABLED", False)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _Msg([_Block("text", "the answer")])

    monkeypatch.setattr(claude_integration.client.messages, "create", fake_create)
    out = claude_integration.ask_claude("hi", source="api")
    assert out == "the answer"
    assert "tools" not in captured  # web search off by default


def test_ask_claude_adds_web_search_tool_when_enabled(monkeypatch):
    _stub_common(monkeypatch)
    monkeypatch.setattr(claude_integration, "WEB_SEARCH_ENABLED", True)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _Msg([_Block("server_tool_use"), _Block("text", "looked it up")])

    monkeypatch.setattr(claude_integration.client.messages, "create", fake_create)
    out = claude_integration.ask_claude("what's new", source="api")
    assert out == "looked it up"  # last text block, past the tool-use block
    assert captured["tools"][0]["type"] == "web_search_20260209"


def test_ask_claude_resumes_on_pause_turn(monkeypatch):
    _stub_common(monkeypatch)
    monkeypatch.setattr(claude_integration, "WEB_SEARCH_ENABLED", True)
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _Msg([_Block("text", "searching")], stop_reason="pause_turn")
        return _Msg([_Block("text", "final answer")], stop_reason="end_turn")

    monkeypatch.setattr(claude_integration.client.messages, "create", fake_create)
    out = claude_integration.ask_claude("who won last night", source="api")
    assert out == "final answer"
    assert len(calls) == 2  # resumed exactly once after pause_turn


def test_ask_claude_blocks_when_budget_limit_reached(monkeypatch):
    monkeypatch.setattr(claude_integration.budget_tracker, "is_limit_reached", lambda: True)

    # If the SDK were called, this would raise — proving the limit short-circuits first.
    def should_not_run(*args, **kwargs):
        raise AssertionError("Claude was called despite the budget limit")

    monkeypatch.setattr(claude_integration.client.messages, "create", should_not_run)

    reply = claude_integration.ask_claude("anything", source="api")
    assert "budget" in reply.lower()
