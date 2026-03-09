import json
import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    BUDGET_FILE,
    BUDGET_WARNING_THRESHOLD,
    BUDGET_HARD_LIMIT,
    CLAUDE_INPUT_PRICE_PER_MTOK,
    CLAUDE_OUTPUT_PRICE_PER_MTOK,
)

logger = logging.getLogger(__name__)

# Session-level flag — resets on service restart
_warning_spoken = False

_EMPTY_BUDGET = {
    "total_cost": 0.0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
}


def _load() -> dict:
    if not os.path.exists(BUDGET_FILE):
        return dict(_EMPTY_BUDGET)
    try:
        with open(BUDGET_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load budget file: {e}")
        return dict(_EMPTY_BUDGET)


def _save(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(BUDGET_FILE), exist_ok=True)
        with open(BUDGET_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        logger.error(f"Failed to save budget file: {e}")


def is_limit_reached() -> bool:
    return _load()["total_cost"] >= BUDGET_HARD_LIMIT


def record_usage(input_tokens: int, output_tokens: int) -> dict:
    """
    Add token usage to the running total and persist it.
    Returns a dict with current totals and status flags.
    """
    global _warning_spoken

    cost = (input_tokens / 1_000_000) * CLAUDE_INPUT_PRICE_PER_MTOK + \
           (output_tokens / 1_000_000) * CLAUDE_OUTPUT_PRICE_PER_MTOK

    data = _load()
    data["total_cost"] += cost
    data["total_input_tokens"] += input_tokens
    data["total_output_tokens"] += output_tokens
    _save(data)

    total = data["total_cost"]
    logger.info(f"Budget: ${total:.4f} / ${BUDGET_HARD_LIMIT:.2f} (this call: ${cost:.4f})")

    limit_reached = total >= BUDGET_HARD_LIMIT
    warning = not _warning_spoken and total >= BUDGET_WARNING_THRESHOLD

    if warning:
        _warning_spoken = True
        logger.warning(f"Budget warning threshold (${BUDGET_WARNING_THRESHOLD}) reached: ${total:.4f}")

    if limit_reached:
        logger.error(f"Budget hard limit (${BUDGET_HARD_LIMIT}) reached: ${total:.4f}")

    return {
        "total_cost": total,
        "warning": warning,
        "limit_reached": limit_reached,
    }
