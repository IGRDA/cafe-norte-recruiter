"""What a candidate's words say about which interview slot they mean (D41). Pure."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.domain.slot_choice import LAST, SlotWords, read_slot_words


def words(text: str) -> SlotWords:
    return read_slot_words(text)


# ---- position, weekday, day of the month ---------------------------------------------------------


def test_a_weekday_alone_is_only_a_weekday() -> None:
    w = words("El viernes.")
    assert w.weekdays == {4} and not (w.positions or w.days or w.times or w.offsets or w.part)
    assert w.rest == "" and not w.negated


@pytest.mark.parametrize(
    ("text", "position"),
    [
        ("el primero", 1),
        ("La segunda.", 2),
        ("el tercero me va bien", 3),
        ("el último", LAST),
        ("the first one", 1),
        ("the second one, please", 2),
        ("the last one", LAST),
    ],
)
def test_an_ordinal_is_a_position_and_never_a_day_or_an_hour(text: str, position: int) -> None:
    w = words(text)
    assert w.positions == {position}
    assert not (w.days or w.times or w.weekdays)


@pytest.mark.parametrize(
    ("text", "day"),
    [
        ("el 23", 23),
        ("el veintitrés", 23),
        ("treinta y uno", 31),
        ("the 23rd", 23),
        ("the twenty-third", 23),
        ("el primero de noviembre", 1),
        ("the first of November", 1),
        ("el 1º", 1),
        ("the fourth", 4),
    ],
)
def test_a_number_without_a_clock_cue_is_a_day_of_the_month(text: str, day: int) -> None:
    w = words(text)
    assert w.days == {day} and not (w.times or w.positions)


def test_a_number_outside_a_month_is_left_unread() -> None:
    w = words("el 45")
    assert not w.days and w.rest == "45"


# ---- clock times ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "time"),
    [
        ("a las diez y media", (10, 30)),
        ("las diez y cuarto", (10, 15)),
        ("a las once menos cuarto", (10, 45)),
        ("a las diez en punto", (10, 0)),
        ("10:30", (10, 30)),
        ("a las 10.30", (10, 30)),
        ("a las 17:00", (17, 0)),
        ("a las cinco", (5, None)),
        ("a las 5", (5, None)),
        ("17h", (17, None)),
        ("at half past ten", (10, 30)),
        ("quarter past ten", (10, 15)),
        ("quarter to eleven", (10, 45)),
        ("at ten thirty", (10, 30)),
        ("ten o'clock", (10, 0)),
        ("at 5", (5, None)),
        ("a la una", (1, None)),
    ],
)
def test_a_clock_time_in_either_language(text: str, time: tuple[int, int | None]) -> None:
    w = words(text)
    assert w.times == {time} and not (w.days or w.positions), w


@pytest.mark.parametrize(
    ("text", "time", "part"),
    [
        ("a las cinco de la tarde", (5, None), "afternoon"),
        ("5 pm", (5, None), "afternoon"),
        ("10:30 am", (10, 30), "morning"),
        ("las diez de la mañana", (10, None), "morning"),
    ],
)
def test_a_time_with_its_part_of_day(text: str, time: tuple[int, int | None], part: str) -> None:
    w = words(text)
    assert w.times == {time} and w.part == part


# ---- relative days and parts of the day ----------------------------------------------------------


def test_manana_is_tomorrow_but_por_la_manana_is_the_morning() -> None:
    assert words("mañana").offsets == {1} and words("mañana").part is None
    assert words("por la mañana").part == "morning" and not words("por la mañana").offsets
    both = words("mañana por la tarde")
    assert both.offsets == {1} and both.part == "afternoon"
    assert words("tomorrow morning").offsets == {1}
    assert words("tomorrow morning").part == "morning"


@pytest.mark.parametrize(
    ("text", "offset"),
    [("hoy", 0), ("today", 0), ("pasado mañana", 2), ("the day after tomorrow", 2)],
)
def test_relative_days(text: str, offset: int) -> None:
    assert words(text).offsets == {offset}


# ---- the hosted call, and what Ana says ----------------------------------------------------------


def test_the_hosted_answer_has_a_weekday_a_day_and_a_time() -> None:
    w = words("El viernes, veintitrés, a las diez y media.")
    assert w.weekdays == {4} and w.days == {23} and w.times == {(10, 30)}
    assert w.rest == ""


@pytest.mark.parametrize(
    "text",
    ["jueves 22 de octubre de 2026 a las 10:30", "Thursday 22 October 2026 at 10:30"],
)
def test_the_slot_as_ana_says_it_is_understood_and_the_year_is_not_a_day(text: str) -> None:
    w = words(text)
    assert w.weekdays == {3} and w.days == {22} and w.times == {(10, 30)}
    assert w.rest == ""


def test_a_plain_yes_has_no_slot_words_and_keeps_its_words() -> None:
    w = words("Exacto, sí.")
    assert not (w.positions or w.weekdays or w.days or w.offsets or w.times or w.part)
    assert w.rest == "exacto si"


def test_a_yes_with_the_slot_restated_leaves_the_yes_in_the_rest() -> None:
    assert words("Sí, el viernes a las diez y media").rest == "si"
    assert words("Yes, the 23rd at ten thirty, please").rest == "yes"


@pytest.mark.parametrize(
    "text",
    ["no, el viernes no", "ninguno me va bien", "not on Friday", "otro día", "none of them"],
)
def test_a_refusal_is_flagged(text: str) -> None:
    assert words(text).negated


# ---- properties ----------------------------------------------------------------------------------

FILLERS = ["eh", "pues", "bueno", "mm", "ok", "um"]


@given(st.text(max_size=80))
def test_any_text_is_read_without_error(text: str) -> None:
    w = read_slot_words(text)
    assert all(1 <= d <= 31 for d in w.days)
    assert all(0 <= h <= 23 and (m is None or 0 <= m <= 59) for h, m in w.times)


@given(st.lists(st.sampled_from(FILLERS), min_size=1, max_size=4))
def test_filler_words_say_nothing_about_a_slot(fillers: list[str]) -> None:
    w = read_slot_words(" ".join(fillers))
    assert not (w.positions or w.weekdays or w.days or w.offsets or w.times or w.part or w.negated)
