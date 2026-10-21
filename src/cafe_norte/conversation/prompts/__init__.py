"""Versioned prompt files. Bump ``PROMPT_VERSION`` whenever a file changes."""

from pathlib import Path

from cafe_norte.errors import Language

PROMPT_VERSION = "ana_v11"
PROMPTS_DIR = Path(__file__).parent


def load(name: str, language: Language | None = None) -> str:
    """Read ``<name>.<language>.md`` for candidate-facing text, ``<name>.md`` otherwise."""
    stem = name if language is None else f"{name}.{language}"
    return (PROMPTS_DIR / f"{stem}.md").read_text(encoding="utf-8")


def table(name: str, language: Language) -> dict[str, str]:
    """``key: sentence`` lines of ``<name>.<language>.md``; comment and blank lines are skipped."""
    rows: dict[str, str] = {}
    for line in load(name, language).splitlines():
        if not line.strip() or line.startswith("#") or ": " not in line:
            continue
        key, _, value = line.partition(": ")
        if " " in key:
            continue  # prose, not a row
        rows[key.strip()] = value.strip()
    return rows
