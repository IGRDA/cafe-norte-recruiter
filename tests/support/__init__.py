"""Shared test support: paths, builders, harnesses and Hypothesis strategies. Test modules
import from here and never from each other (``tests/unit/test_architecture.py``)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
