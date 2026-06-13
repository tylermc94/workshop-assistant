"""Regression tests for the ingress route_content dispatch (Phase 1, item 3).

The bug these guard: route_content used to pass a project-name *string* to
forge_capture helpers that expect a Path (upsert_section) or a dict
(write_new_project / write_project_task). We stub Claude's action decision and
the write helpers so nothing touches the network or the real vault, then assert
the helpers are called with the correct argument *types*.
"""
from pathlib import Path

import pytest

import ingress_processor
import forge_capture


def test_append_research_passes_a_path_to_upsert_section(monkeypatch, tmp_path):
    monkeypatch.setattr(forge_capture, "call_claude", lambda *a, **k: '{"action": "append_research"}')
    monkeypatch.setattr(forge_capture, "find_project_file", lambda name: tmp_path / f"{name}.md")

    captured = {}
    monkeypatch.setattr(
        forge_capture, "upsert_section",
        lambda filepath, header, content: captured.update(filepath=filepath, header=header),
    )

    desc, _ = ingress_processor.route_content(Path("note.md"), "body", "MyProject", ["MyProject"], [])

    assert isinstance(captured["filepath"], Path)
    assert captured["header"].startswith("## Research")
    assert "append_research" in desc


def test_create_subproject_passes_a_dict_to_write_new_project(monkeypatch, tmp_path):
    monkeypatch.setattr(forge_capture, "call_claude", lambda *a, **k: '{"action": "create_subproject"}')

    captured = {}
    def fake_write_new_project(result):
        captured["result"] = result
        return tmp_path / "new.md"
    monkeypatch.setattr(forge_capture, "write_new_project", fake_write_new_project)

    desc, _ = ingress_processor.route_content(Path("Idea.md"), "body", "Parent", ["Parent"], [])

    assert isinstance(captured["result"], dict)
    assert captured["result"]["title"] == "Idea"
    assert "create_subproject" in desc


def test_add_tasks_passes_dicts_to_write_project_task(monkeypatch):
    monkeypatch.setattr(forge_capture, "call_claude", lambda *a, **k: '{"action": "add_tasks"}')
    monkeypatch.setattr(forge_capture, "find_project_file", lambda name: None)

    calls = []
    monkeypatch.setattr(
        forge_capture, "write_project_task",
        lambda result, projects, areas: calls.append((result, projects, areas)),
    )

    content = "- [ ] first task\n- [ ] second task"
    desc, _ = ingress_processor.route_content(Path("tasks.md"), content, "Proj", ["Proj"], ["AreaA"])

    assert len(calls) == 2
    result0, projects0, areas0 = calls[0]
    assert isinstance(result0, dict)
    assert result0["target"] == "Proj"
    assert "title" in result0
    assert projects0 == ["Proj"]
    assert areas0 == ["AreaA"]
