"""Versioned prompt files. Bump ``PROMPT_VERSION`` whenever a file changes."""

from pathlib import Path

PROMPT_VERSION = "ana_v1"
PROMPTS_DIR = Path(__file__).parent


def load(name: str) -> str:
    """Read ``<name>.md`` from this directory."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
