"""The deterministic brief and the one-line field read-backs."""

from datetime import date
from typing import get_args

import pytest

from cafe_norte.conversation import prompts
from cafe_norte.conversation.brief import field_readback, render_brief
from cafe_norte.domain.contracts import YearMonth
from cafe_norte.errors import TABLED, Language
from tests.support.builders import CONFIG, record


def test_the_s01_record_renders_as_short_spoken_sentences() -> None:
    lucia = record(
        name="Lucía Marín",
        interest="yes",
        work_authorization="yes",
        availability_days=frozenset({"mon", "tue", "thu"}),
        availability_shifts=frozenset({"morning"}),
        hours_per_week=30,
        earliest_start_date=date(2026, 10, 26),
        experience="dos años en una cafetería",
    )
    assert render_brief(lucia, CONFIG, "es") == (
        "Te resumo lo que tengo. Te llamas Lucía Marín. Me has dicho que te interesa el puesto. "
        "Me has dicho que tienes permiso de trabajo. Puedes trabajar lunes, martes y jueves, "
        "en turno de Mañana, "
        "unas 30 horas a la semana. Podrías empezar el lunes 26 de octubre de 2026. "
        "Experiencia: dos años en una cafetería. ¿Es todo correcto?"
    )


def test_unknown_and_declined_fields_stay_visible_and_optional_phone_is_omitted() -> None:
    gaps = record(
        name="Ane",
        interest="unsure",
        work_authorization="unsure",
        availability_days=frozenset({"sat"}),
        availability_shifts=frozenset({"afternoon"}),
        unknown=frozenset({"hours_per_week"}),
        declined=frozenset({"earliest_start_date", "experience"}),
    )
    text = render_brief(gaps, CONFIG, "es")
    assert "No tienes claro si te interesa." in text
    assert "No tienes claro si tienes permiso de trabajo." in text
    assert "Horas a la semana: no lo sabes." in text
    assert "Fecha de inicio: prefieres no decirlo." in text
    assert "Experiencia: prefieres no decirlo." in text
    assert "teléfono" not in text.lower()
    assert text.endswith("¿Es todo correcto?")


def test_an_experience_ending_in_a_period_does_not_double_it() -> None:
    text = render_brief(record(name="Ane", experience="He trabajado dos años."), CONFIG, "es")
    assert "Experiencia: He trabajado dos años." in text and ".." not in text


def test_field_readbacks_for_phone_and_date() -> None:
    assert field_readback("contact_phone", "+34612345678", "es") == (
        "He apuntado el teléfono +34 612 345 678. ¿Es correcto?"
    )
    assert field_readback("earliest_start_date", date(2026, 10, 26), "es") == (
        "He apuntado que podrías empezar el lunes 26 de octubre de 2026. ¿Es correcto?"
    )


def test_the_brief_and_read_backs_in_english_use_the_english_labels_and_date() -> None:
    lucy = record(
        name="Lucy Martin",
        interest="yes",
        work_authorization="unsure",
        availability_days=frozenset({"mon", "tue", "thu"}),
        availability_shifts=frozenset({"morning"}),
        hours_per_week=30,
        earliest_start_date=date(2026, 10, 26),
        declined=frozenset({"experience"}),
    )
    assert render_brief(lucy, CONFIG, "en") == (
        "Here is what I have. Your name is Lucy Martin. You said you are interested in the role. "
        "You are not sure whether you have permission to work. You can work Monday, Tuesday "
        "and Thursday, on the Morning shift, about 30 hours a week. You could start on "
        "Monday 26 October 2026. Experience: you would rather not say. Is all of that correct?"
    )
    assert field_readback("earliest_start_date", date(2026, 10, 26), "en") == (
        "I have that you could start on Monday 26 October 2026. Is that correct?"
    )


@pytest.mark.parametrize("name", ["brief", "voice", "controls"])
def test_every_language_has_the_same_sentence_keys(name: str) -> None:
    keys = {language: set(prompts.table(name, language)) for language in TABLED}
    assert keys["en"] == keys["es"]


@pytest.mark.parametrize("name", ["opening", "resume"])
@pytest.mark.parametrize("language", get_args(Language))
def test_every_language_has_a_text(name: str, language: Language) -> None:
    """A tabled language its own; any other the English one, for the model to word."""
    assert prompts.load(name, language).strip()


def test_a_requested_follow_up_is_stated_just_before_the_question() -> None:
    ane = record(name="Ane")
    with_followup = render_brief(ane, CONFIG, "es", followup=True)
    assert with_followup.endswith(
        "Has pedido que una persona del equipo se ponga en contacto contigo. ¿Es todo correcto?"
    )
    assert "persona del equipo" not in render_brief(ane, CONFIG, "es")


def test_a_month_only_start_is_read_back_as_the_month() -> None:
    assert field_readback("earliest_start_date", YearMonth(year=2027, month=1), "es") == (
        "He apuntado que podrías empezar en enero de 2027. ¿Es correcto?"
    )
    assert field_readback("earliest_start_date", YearMonth(year=2027, month=1), "en") == (
        "I have that you could start in January 2027. Is that correct?"
    )


@pytest.mark.parametrize("language", get_args(Language))
def test_the_closing_line_names_the_language_in_english_and_natively(language: Language) -> None:
    """One template for every language: no per-language prompt file to forget."""
    info = prompts.languages()[language]
    line = prompts.language_line(language)
    assert info.english in line and info.native in line and "{" not in line
