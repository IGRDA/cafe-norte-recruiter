"""What a candidate's words say about which interview slot they mean (D41). Pure."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from cafe_norte.conversation.brief import slot_time
from cafe_norte.domain.calendar import interview_slots
from cafe_norte.domain.numbers import spelled
from cafe_norte.domain.slot_choice import (
    LAST,
    Ambiguous,
    Chosen,
    NoMatch,
    NotAChoice,
    SlotChoice,
    SlotWords,
    choose_slot,
    read_slot_words,
)
from cafe_norte.errors import Language
from tests.support.builders import CONFIG

WEEKDAY_NAMES: dict[Language, list[str]] = {
    "es": "lunes martes miércoles jueves viernes sábado domingo".split(),
    "en": "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split(),
}


def words(text: str) -> SlotWords:
    return read_slot_words(text)


# ---- position, weekday, day of the month ---------------------------------------------------------


def test_a_weekday_alone_is_only_a_weekday() -> None:
    w = words("El viernes.")
    assert w.weekdays == {4} and not (w.positions or w.days or w.times or w.offsets or w.part)
    assert w.rest == ""


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


def test_esta_manana_is_this_morning_never_tomorrow() -> None:
    for text in ("esta mañana", "this morning"):
        assert words(text).offsets == {0} and words(text).part == "morning"
    assert words("esta tarde").offsets == {0} and words("esta tarde").part == "afternoon"


def test_a_m_and_p_m_with_points() -> None:
    w = words("10:30 a.m.")
    assert w.times == {(10, 30)} and w.part == "morning" and w.rest == ""


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
    assert not (w.positions or w.weekdays or w.days or w.offsets or w.times or w.part)


# ---- choosing among the slots offered ------------------------------------------------------------

MADRID = ZoneInfo("Europe/Madrid")
TODAY = date(2026, 10, 20)  # a Tuesday
TUE_17 = datetime(2026, 10, 20, 17, 0)
WED_1030 = datetime(2026, 10, 21, 10, 30)
WED_17 = datetime(2026, 10, 21, 17, 0)
FRI_1030 = datetime(2026, 10, 23, 10, 30)
FRI_17 = datetime(2026, 10, 23, 17, 0)
OFFER = (TUE_17, WED_1030, WED_17)
FRIDAYS = (FRI_1030, FRI_17)


def choose(text: str, offered: Sequence[datetime], shortlist: tuple[int, ...] = ()) -> SlotChoice:
    return choose_slot(read_slot_words(text), offered, today=TODAY, shortlist=shortlist)


def matched(choice: SlotChoice) -> set[int]:
    if isinstance(choice, Chosen):
        return {choice.index}
    if isinstance(choice, Ambiguous):
        return set(choice.indices)
    return set()


@pytest.mark.parametrize(
    ("text", "offered", "index"),
    [
        ("el primero", OFFER, 0),
        ("the last one", OFFER, 2),
        ("el martes", OFFER, 0),
        ("hoy", OFFER, 0),
        ("mañana por la tarde", OFFER, 2),
        ("el miércoles a las diez y media", OFFER, 1),
        ("a las diez y media", OFFER, 1),
        ("el 21 a las cinco", OFFER, 2),  # five o'clock is 17:00 for an interview
        ("el viernes, veintitrés, a las diez y media", FRIDAYS, 0),
        ("Friday at 5 pm", FRIDAYS, 1),
    ],
)
def test_words_that_fit_exactly_one_offered_slot_choose_it(
    text: str, offered: tuple[datetime, ...], index: int
) -> None:
    assert choose(text, offered) == Chosen(index=index)


def test_a_day_with_two_slots_is_ambiguous_and_the_time_then_narrows_it() -> None:
    assert choose("El viernes.", FRIDAYS) == Ambiguous(indices=(0, 1))
    assert choose("el miércoles", OFFER) == Ambiguous(indices=(1, 2))
    # Asked which one, the candidate says only the time; both Wednesday and Tuesday have one
    # at 17:00, but the shortlist is Wednesday's.
    assert choose("a las cinco", OFFER) == Ambiguous(indices=(0, 2))
    assert choose("a las cinco", OFFER, shortlist=(1, 2)) == Chosen(index=2)


def test_a_shortlist_the_words_leave_entirely_is_dropped() -> None:
    assert choose("el martes", OFFER, shortlist=(1, 2)) == Chosen(index=0)


def test_a_day_not_offered_is_no_match_with_that_day_inside_the_horizon() -> None:
    assert choose("el sábado", OFFER) == NoMatch(day=date(2026, 10, 24))
    assert choose("el 23", OFFER) == NoMatch(day=date(2026, 10, 23))
    assert choose("pasado mañana", OFFER) == NoMatch(day=date(2026, 10, 22))


def test_no_match_without_a_day_names_none() -> None:
    assert choose("a las ocho", OFFER) == NoMatch(day=None)
    assert choose("el tercero", FRIDAYS) == NoMatch(day=None)


def test_a_day_beyond_the_horizon_is_no_match_without_a_day() -> None:
    assert choose("el 15", OFFER) == NoMatch(day=None)


def test_a_month_is_kept_so_a_weekday_of_another_month_names_no_day() -> None:
    """ "El martes de noviembre" once offered Tuesday 27 October: the month was thrown away."""
    assert read_slot_words("el martes de noviembre").months == frozenset({11})
    assert choose("el martes de noviembre", OFFER) == NoMatch(day=None)
    assert choose("el sábado 24 de octubre", OFFER) == NoMatch(day=date(2026, 10, 24))


@pytest.mark.parametrize(
    "text",
    [
        "Exacto, sí.",
        "¿Dónde está la tienda?",
        "no, el viernes no",
        "ninguno me va bien",
        "not on Friday",
        "otro día",
        "none of them",
    ],
)
def test_no_slot_words_or_a_refusal_is_not_a_choice(text: str) -> None:
    assert choose(text, FRIDAYS) == NotAChoice()


@pytest.mark.parametrize(
    "text",
    [
        "¿La entrevista dura treinta minutos?",
        "Tengo dos preguntas.",
        "¿El sueldo es el mismo por la mañana?",
        "¿Es presencial el martes?",
        "Is it in person on Tuesday?",
    ],
)
def test_a_question_that_happens_to_hold_a_slot_word_is_not_a_choice(text: str) -> None:
    """Only an answer all about the slot is the runtime's (as a plain yes is, D35); anything
    more is the model's, which can answer it."""
    assert choose(text, OFFER) == NotAChoice()


@pytest.mark.parametrize(
    ("text", "index"),
    [
        ("El primero me va bien.", 0),
        ("Mejor el miércoles por la tarde, gracias.", 2),
        ("Vale, el martes.", 0),
        ("That works, the second one please.", 1),
        ("I'd prefer Wednesday morning.", 1),
        # S02 live, 22 October 2026: the slot said back word for word looped in English.
        ("I can do Wednesday 21 October 2026 at 17:00.", 2),
        ("I could go with Wednesday at 10:30.", 1),
        ("Podría el miércoles a las 17:00.", 2),
        ("I can make it at 10:30 on Wednesday, that works for me!", 1),
        ("Ya he confirmado la reserva para el miércoles a las 10:30.", 1),
        ("Please book Wednesday at 17:00.", 2),
    ],
)
def test_the_talk_around_a_choice_keeps_it_a_choice(text: str, index: int) -> None:
    assert choose(text, OFFER) == Chosen(index=index)


def test_asking_for_another_day_is_a_choice_of_that_day() -> None:
    assert choose("¿Tienes algo el sábado?", OFFER) == NoMatch(day=date(2026, 10, 24))


# The calendar the stores really offer, seen from any instant in a month: what Ana can say.
instants = st.datetimes(
    min_value=datetime(2026, 10, 1), max_value=datetime(2026, 11, 1), timezones=st.just(UTC)
)


@st.composite
def offers(draw: st.DrawFn) -> tuple[datetime, tuple[datetime, ...]]:
    """An instant and up to three distinct slots of the real calendar after it, in order,
    in local time."""
    after = draw(instants)
    calendar = [s.starts_at_utc for s in interview_slots(CONFIG, after=after)]
    assume(calendar)
    picked = draw(st.lists(st.sampled_from(calendar), min_size=1, max_size=3, unique=True))
    return after, tuple(sorted(t.astimezone(MADRID).replace(tzinfo=None) for t in picked))


@given(offers(), st.data(), st.sampled_from(["es", "en"]))
def test_any_slot_said_back_as_ana_says_it_is_chosen(
    offer: tuple[datetime, tuple[datetime, ...]], data: st.DataObject, language: Language
) -> None:
    after, offered = offer
    index = data.draw(st.integers(0, len(offered) - 1))
    said = slot_time(offered[index].replace(tzinfo=MADRID), CONFIG, language)
    today = after.astimezone(MADRID).date()
    choice = choose_slot(read_slot_words(said), offered, today=today)
    assert choice == Chosen(index=index), said


@given(offers(), st.data(), st.sampled_from(["es", "en"]))
def test_a_weekday_and_a_spoken_hour_keep_the_slot_meant_among_the_matches(
    offer: tuple[datetime, tuple[datetime, ...]], data: st.DataObject, language: Language
) -> None:
    after, offered = offer
    index = data.draw(st.integers(0, len(offered) - 1))
    slot = offered[index]
    weekday = WEEKDAY_NAMES[language][slot.weekday()]
    hour = spelled(slot.hour % 12 or 12, language)
    half = {"es": " y media", "en": " thirty"}[language] if slot.minute == 30 else ""
    said = {"es": f"el {weekday} a las {hour}{half}", "en": f"{weekday} at {hour}{half}"}[language]
    today = after.astimezone(MADRID).date()
    assert index in matched(choose_slot(read_slot_words(said), offered, today=today)), said


@given(offers(), st.data())
def test_an_ordinal_chooses_that_position(
    offer: tuple[datetime, tuple[datetime, ...]], data: st.DataObject
) -> None:
    _, offered = offer
    index = data.draw(st.integers(0, len(offered) - 1))
    ordinal = ["el primero", "el segundo", "el tercero"][index]
    assert choose(ordinal, offered) == Chosen(index=index)
    assert choose("el último", offered) == Chosen(index=len(offered) - 1)


# One phrase per kind of feature: values of one kind are a union ("el martes o el viernes"),
# kinds intersect, so only a phrase of a new kind can narrow a choice.
PHRASES_BY_KIND = {
    "position": ["el primero", "the second one"],
    "weekday": ["el viernes", "el martes", "on Wednesday"],
    "time": ["a las diez y media", "a las cinco"],
    "part": ["por la tarde"],
    "offset": ["mañana"],
    "day": ["el 23"],
}
SLOT_PHRASES = [phrase for phrases in PHRASES_BY_KIND.values() for phrase in phrases]


@st.composite
def phrases_of_distinct_kinds(draw: st.DrawFn) -> list[str]:
    kinds = draw(
        st.lists(st.sampled_from(sorted(PHRASES_BY_KIND)), min_size=1, max_size=3, unique=True)
    )
    return [draw(st.sampled_from(PHRASES_BY_KIND[kind])) for kind in kinds]


@given(offers(), phrases_of_distinct_kinds(), st.lists(st.integers(0, 2), max_size=2))
def test_a_choice_never_leaves_the_offer_and_a_new_kind_of_word_never_widens_it(
    offer: tuple[datetime, tuple[datetime, ...]],
    phrases: list[str],
    shortlist: list[int],
) -> None:
    after, offered = offer
    today = after.astimezone(MADRID).date()
    narrow = tuple(sorted({i for i in shortlist if i < len(offered)}))
    choice = choose_slot(read_slot_words(" ".join(phrases)), offered, today=today, shortlist=narrow)
    if isinstance(choice, Chosen):
        assert 0 <= choice.index < len(offered)
    if isinstance(choice, Ambiguous):
        assert len(choice.indices) >= 2 and set(choice.indices) <= set(range(len(offered)))
    fewer = choose_slot(read_slot_words(phrases[0]), offered, today=today)
    more = choose_slot(read_slot_words(" ".join(phrases)), offered, today=today)
    assert matched(more) <= matched(fewer)


@given(offers(), st.sampled_from(SLOT_PHRASES), st.lists(st.sampled_from(FILLERS), max_size=3))
def test_fillers_and_negations_around_a_choice(
    offer: tuple[datetime, tuple[datetime, ...]], phrase: str, fillers: list[str]
) -> None:
    after, offered = offer
    today = after.astimezone(MADRID).date()
    plain_choice = choose_slot(read_slot_words(phrase), offered, today=today)
    padded = choose_slot(read_slot_words(" ".join([*fillers, phrase])), offered, today=today)
    assert padded == plain_choice
    refused = choose_slot(read_slot_words(f"no, {phrase} no"), offered, today=today)
    assert refused == NotAChoice()
