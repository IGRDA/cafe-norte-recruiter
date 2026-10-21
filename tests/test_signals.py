"""The synchronous controls: explicit language requests, matched without a model."""

import pytest

from cafe_norte.conversation.signals import Control, explicit_controls, requested_language
from cafe_norte.errors import Language


@pytest.mark.parametrize(
    "text",
    [
        "Can we continue in English?",
        "Could you switch to English, please?",
        "English please",
        "I'd rather speak English",
        "¿Podemos hablar en inglés?",
        "Mejor en ingles",
        "Inglés, por favor",
    ],
)
def test_explicit_requests_for_english(text: str) -> None:
    assert explicit_controls(text) == {"switch_en"}


@pytest.mark.parametrize(
    "text",
    [
        "Can we go back to Spanish?",
        "In Spanish, please",
        "Mejor en español",
        "En castellano, por favor",
        "¿Puedes hablar español?",
    ],
)
def test_explicit_requests_for_spanish(text: str) -> None:
    assert explicit_controls(text) == {"switch_es"}


@pytest.mark.parametrize(
    "text",
    [
        "Trabajé en Starbucks.",
        "I studied English at school.",
        "Hablo inglés y francés.",
        "I worked in an English-speaking café.",
        "Okay",
        "Sí, me viene bien el turno de closing.",
        "",
    ],
)
def test_a_borrowed_word_or_a_mention_is_not_a_request(text: str) -> None:
    assert explicit_controls(text) == frozenset()


@pytest.mark.parametrize(
    ("controls", "current", "expected"),
    [
        (frozenset(), "es", "es"),
        (frozenset({"switch_en"}), "es", "en"),
        (frozenset({"switch_en"}), "en", "en"),
        (frozenset({"switch_es"}), "en", "es"),
        (frozenset({"switch_es", "switch_en"}), "es", "es"),  # ambiguous: no change
        (frozenset({"stop"}), "en", "en"),
    ],
)
def test_requested_language(
    controls: frozenset[Control], current: Language, expected: Language
) -> None:
    assert requested_language(controls, current) == expected
