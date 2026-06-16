"""Tests for the vault path-safety guard (Phase 1, item 4).

_safe_path must reject any path that resolves outside the vault root. The key
case is a *sibling* directory like "second-brain-notes": the old str.startswith
check wrongly accepted it; is_relative_to correctly rejects it.
"""
import pytest

import second_brain_agent as agent
from config import settings


def test_vault_path_and_model_come_from_settings():
    # Guards against re-introducing hardcoded copies of the path / model id.
    assert str(agent.VAULT) == settings.VAULT_PATH
    assert agent.MODEL == settings.SECOND_BRAIN_MODEL


# --- git pull skipped on read-only QUERY (Phase 3, item 3) ----------------

class _Block:
    def __init__(self, type, text=None):
        self.type = type
        self.text = text


class _FakeResponse:
    """A Claude response with no tool calls, so the agent loop returns at once."""
    def __init__(self):
        self.content = [_Block("text", "the answer")]
        self.stop_reason = "end_turn"
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()


def _patch_agent_io(monkeypatch):
    pulls = {"count": 0}
    monkeypatch.setattr(agent, "_git_pull", lambda: pulls.__setitem__("count", pulls["count"] + 1))
    monkeypatch.setattr(agent, "_git_push", lambda: None)
    monkeypatch.setattr(agent.budget_tracker, "record_message", lambda m: None)
    monkeypatch.setattr(agent.client.messages, "create", lambda **k: _FakeResponse())
    return pulls


def test_query_skips_git_pull(monkeypatch):
    pulls = _patch_agent_io(monkeypatch)
    agent._run_agent_loop("what's in my vault", "QUERY")
    assert pulls["count"] == 0


def test_capture_does_git_pull(monkeypatch):
    pulls = _patch_agent_io(monkeypatch)
    agent._run_agent_loop("add a note about oak", "CAPTURE")
    assert pulls["count"] == 1


# --- run() degrades gracefully on failure (Phase 3, item 6) ---------------

def test_run_returns_spoken_fallback_on_error(monkeypatch):
    import forge_state

    def _boom(transcript, intent):
        raise RuntimeError("vault unreachable")
    monkeypatch.setattr(agent, "_run_agent_loop_with_push", _boom)

    result = agent.run("add a note", "CAPTURE")
    assert "trouble" in result.lower()
    assert forge_state.state["second_brain_status"] == "error"


def test_safe_path_accepts_paths_inside_the_vault():
    resolved = agent._safe_path("Projects/Active/note.md")
    assert resolved.is_relative_to(agent.VAULT.resolve())


@pytest.mark.parametrize("bad_path", [
    "../etc/passwd",            # classic traversal
    "../second-brain-notes/x",  # sibling dir — the startswith bug
    "/etc/passwd",              # absolute path outside the vault
])
def test_safe_path_rejects_paths_outside_the_vault(bad_path):
    with pytest.raises(ValueError):
        agent._safe_path(bad_path)
