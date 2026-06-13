"""Tests for budget schema + vault spend tracking (Phase 3, items 4 & 5).

record_usage writes to BUDGET_FILE, so each test points it at a temp file to
avoid touching the real logs/budget.json.
"""
import budget_tracker


def test_empty_budget_has_canonical_shape():
    eb = budget_tracker.empty_budget()
    assert set(eb) == {"total_cost", "total_input_tokens", "total_output_tokens"}
    assert eb["total_cost"] == 0.0
    # A fresh tracker write must use the same keys (no schema drift).
    assert set(eb) == set(budget_tracker._EMPTY_BUDGET)


def test_record_message_accumulates_usage(monkeypatch, tmp_path):
    monkeypatch.setattr(budget_tracker, "BUDGET_FILE", str(tmp_path / "budget.json"))

    class FakeUsage:
        input_tokens = 1000
        output_tokens = 500

    class FakeMessage:
        usage = FakeUsage()

    budget_tracker.record_message(FakeMessage())

    data = budget_tracker._load()
    assert data["total_input_tokens"] == 1000
    assert data["total_output_tokens"] == 500
    assert data["total_cost"] > 0


def test_record_message_never_raises_on_bad_object(monkeypatch, tmp_path):
    monkeypatch.setattr(budget_tracker, "BUDGET_FILE", str(tmp_path / "budget.json"))
    # No .usage attribute — must be swallowed, not propagated into the vault flow.
    budget_tracker.record_message(object())
