"""Fast synchronous controls and the asynchronous classifier adapter."""

import re
import unicodedata
from typing import Literal

from cafe_norte.domain.contracts import Signal, TurnId
from cafe_norte.errors import Language
from cafe_norte.model.contracts import Model

Control = Literal["stop", "human", "switch_es", "switch_en"]

# An explicit request names the language with a request word around it; a bare borrowed word
# ("Starbucks", "I studied English") never matches. Matched on lower-case text without accents.
_EN = r"english(?![\w-])"
_ES = r"(?:spanish|espanol|castellano)(?![\w-])"
_REQUESTS: tuple[tuple[Control, re.Pattern[str]], ...] = (
    (
        "switch_en",
        re.compile(
            rf"\b(?:(?:in|into|to|speak) {_EN}|{_EN},? please|en ingles\b"
            r"|hablar? ingles\b|ingles,? por favor)"
        ),
    ),
    (
        "switch_es",
        re.compile(rf"\b(?:(?:in|into|to|speak|en|hablar?) {_ES}|{_ES},? (?:please|por favor))"),
    ),
)
_SWITCHES: dict[Control, Language] = {"switch_es": "es", "switch_en": "en"}


def explicit_controls(text: str) -> frozenset[Control]:
    """Pattern-based detection of explicit requests. Pure, no model. Language switches only
    for now; stop and human requests arrive with the frustration stage."""
    plain = "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    )
    return frozenset(control for control, pattern in _REQUESTS if pattern.search(plain))


def requested_language(controls: frozenset[Control], current: Language) -> Language:
    """The language asked for when exactly one switch was requested; ``current`` otherwise."""
    asked = {_SWITCHES[c] for c in controls if c in _SWITCHES}
    return asked.pop() if len(asked) == 1 else current


class ModelSignalAnalyzer:
    """Small classifier call, off the critical path; stale results never override a newer
    explicit preference."""

    def __init__(self, model: Model) -> None:
        raise NotImplementedError

    async def analyze(self, turn_id: TurnId, text: str, language: Language) -> Signal:
        raise NotImplementedError
