"""Versioned prompt files. Bump ``PROMPT_VERSION`` when model instructions or spoken text change."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from cafe_norte.errors import TABLED, Language

PROMPT_VERSION = "ana_v26"
PROMPTS_DIR = Path(__file__).parent


# Template files worded in a language without reviewed texts (``conversation/wording.py``):
# filled once per process, read like the files. Until a file is worded it reads as English.
_WORDED: dict[tuple[str, Language], str] = {}


def use_worded(name: str, language: Language, text: str) -> None:
    _WORDED[(name, language)] = text


def load(name: str, language: Language | None = None) -> str:
    """Read ``<name>.<language>.md`` for candidate-facing text, ``<name>.md`` otherwise. A
    language without reviewed texts reads its worded copy, or English until it has one."""
    if language is not None and language not in TABLED:
        worded = _WORDED.get((name, language))
        if worded is not None:
            return worded
        language = "en"
    stem = name if language is None else f"{name}.{language}"
    return (PROMPTS_DIR / f"{stem}.md").read_text(encoding="utf-8")


class LanguageInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    native: str
    english: str
    names: tuple[str, ...]
    rtl: bool


def language_line(language: Language) -> str:
    """The system message's closing line: which language every reply is in. One template
    for every language, in English, naming the language natively too."""
    info = languages()[language]
    return load("language").strip().format(english=info.english, native=info.native)


def languages() -> dict[Language, LanguageInfo]:
    """``languages.yaml``: what the prompt, the patterns and the page know about each one."""
    raw = yaml.safe_load((PROMPTS_DIR / "languages.yaml").read_text("utf-8"))
    return {code: LanguageInfo.model_validate(info) for code, info in raw.items()}


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
