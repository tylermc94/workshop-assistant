"""Shared pytest setup for the Forge test suite.

The app is launched as `python src/main.py` (so `src/` lands on sys.path and
bare imports like `import budget_tracker` work) from the project root (so
`config.*` imports work). We reproduce both here so tests can import the same
modules without a packaging change.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

for path in (ROOT, SRC):
    if path not in sys.path:
        sys.path.insert(0, path)
