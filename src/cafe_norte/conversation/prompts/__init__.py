"""Versioned prompt files. Bump ``PROMPT_VERSION`` whenever a file changes."""

from pathlib import Path

PROMPT_VERSION = "ana_v6"
PROMPTS_DIR = Path(__file__).parent


def load(name: str) -> str:
    """Read ``<name>.md`` from this directory."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def table(name: str) -> dict[str, str]:
    """``key: sentence`` lines of ``<name>.md``; comment and blank lines are skipped."""
    rows: dict[str, str] = {}
    for line in load(name).splitlines():
        if not line.strip() or line.startswith("#") or ": " not in line:
            continue
        key, _, value = line.partition(": ")
        if " " in key:
            continue  # prose, not a row
        rows[key.strip()] = value.strip()
    return rows
