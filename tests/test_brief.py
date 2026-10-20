"""The deterministic brief and the one-line field read-backs."""

from datetime import date

from cafe_norte.conversation.brief import field_readback, render_brief_es
from cafe_norte.domain.candidate import apply_patch
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import (
    CandidatePatch,
    CandidateRecord,
    ConfigId,
    Evidence,
    TurnId,
)
from tests.support import CONFIG_DIR

CONFIG = load_configurations(CONFIG_DIR)[ConfigId("chamberi_barista_v1")]
EVIDENCE = Evidence(source_turn_id=TurnId("t"), text="…")


def record(**fields: object) -> CandidateRecord:
    return apply_patch(CandidateRecord(), CandidatePatch(**fields), EVIDENCE)


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
    assert render_brief_es(lucia, CONFIG) == (
        "Te resumo lo que tengo. Te llamas Lucía Marín. Te interesa el puesto. "
        "Tienes permiso de trabajo. Puedes trabajar lunes, martes y jueves, en turno de Mañana, "
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
    text = render_brief_es(gaps, CONFIG)
    assert "No tienes claro si te interesa." in text
    assert "No tienes claro si tienes permiso de trabajo." in text
    assert "Horas a la semana: no lo sabes." in text
    assert "Fecha de inicio: prefieres no decirlo." in text
    assert "Experiencia: prefieres no decirlo." in text
    assert "teléfono" not in text.lower()
    assert text.endswith("¿Es todo correcto?")


def test_an_experience_ending_in_a_period_does_not_double_it() -> None:
    text = render_brief_es(record(name="Ane", experience="He trabajado dos años."), CONFIG)
    assert "Experiencia: He trabajado dos años." in text and ".." not in text


def test_field_readbacks_for_phone_and_date() -> None:
    assert field_readback("contact_phone", "+34612345678", CONFIG) == (
        "He apuntado el teléfono +34 612 345 678. ¿Es correcto?"
    )
    assert field_readback("earliest_start_date", date(2026, 10, 26), CONFIG) == (
        "He apuntado que podrías empezar el lunes 26 de octubre de 2026. ¿Es correcto?"
    )
