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
