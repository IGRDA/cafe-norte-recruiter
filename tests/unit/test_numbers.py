"""A number the model saves must be in the candidate's own words, as digits or spoken."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.domain.numbers import mentions_number, plain, spelled
from cafe_norte.errors import Language
from tests.support.strategies import languages


@pytest.mark.parametrize(
    ("text", "n"),
    [
        ("Unas 35 horas", 35),
        ("treinta y cinco horas a la semana", 35),
        ("Treinta y cinco", 35),
        ("veinte", 20),
        ("Veintidós horas", 22),
        ("about thirty-five hours", 35),
        ("twenty hours", 20),
        ("40h", 40),
        ("cuarenta", 40),
    ],
)
def test_a_number_said_in_digits_or_words_is_found(text: str, n: int) -> None:
    assert mentions_number(text, n)


@pytest.mark.parametrize(
    ("text", "n"),
    [
        ("Por la mañana.", 35),  # the hosted call: 35 was the store's contract, never said
        ("Unas 30 horas", 35),
        ("treinta horas", 35),
        ("135 euros", 35),  # a number inside another number is not the number
        ("cinco días", 35),
    ],
)
def test_a_number_not_said_is_not_found(text: str, n: int) -> None:
    assert not mentions_number(text, n)


@given(st.integers(min_value=1, max_value=99), languages)
def test_every_number_is_found_in_its_own_spelling(n: int, language: Language) -> None:
    assert mentions_number(f"Pues {spelled(n, language)} más o menos", n)
    assert mentions_number(f"unas {n} horas", n)


@given(st.integers(min_value=0, max_value=99), languages)
def test_spelling_covers_zero_to_ninety_nine_in_both_languages(n: int, language: Language) -> None:
    assert mentions_number(spelled(n, language), n)


@given(st.integers(min_value=0, max_value=999), st.integers(min_value=0, max_value=9))
def test_a_digit_glued_to_a_number_makes_another_number(n: int, digit: int) -> None:
    assert not mentions_number(f"unas {n}{digit} horas", n)
    assert not mentions_number(f"unas {digit}{n} horas", n) or str(n).startswith("0")


@given(st.integers(min_value=1, max_value=9), languages)
def test_a_tens_word_never_mentions_the_number_with_its_unit(unit: int, language: Language) -> None:
    for tens in (20, 30, 40, 50):
        assert not mentions_number(spelled(tens + unit, language), tens)


@given(st.text(max_size=40))
def test_plain_is_idempotent(text: str) -> None:
    assert plain(plain(text)) == plain(text)
