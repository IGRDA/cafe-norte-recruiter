"""Going over a cut read-back: its short parts (D39)."""

from datetime import date

import pytest

from cafe_norte.conversation.brief import field_readback, render_brief
from cafe_norte.conversation.prompt import split_sentences
from cafe_norte.conversation.readback import (
    PART_CHARACTERS,
    PART_SENTENCES,
    current_saying,
    review_parts,
)
from cafe_norte.domain.contracts import (
    BriefTarget,
    Confirmation,
    ConfirmationId,
    ConfirmationTarget,
    FieldTarget,
    ReviewInParts,
    ReviewOffered,
    ReviewWaived,
    SlotId,
    SlotTarget,
    TurnId,
)
from cafe_norte.errors import Language
from tests.test_brief import CONFIG, record

LUCIA = record(
    name="Lucía Marín",
    interest="yes",
    work_authorization="yes",
    availability_days=frozenset({"mon", "tue", "thu"}),
    availability_shifts=frozenset({"morning"}),
    hours_per_week=30,
    earliest_start_date=date(2026, 10, 26),
    experience="dos años en una cafetería",
    contact_phone="+34612345678",
)
SLOT_ES = (
    "He apuntado la entrevista en Café Norte Chamberí el jueves 22 de octubre de 2026 a las "
    "10:30, hora de Madrid. ¿Te la reservo?"
)


def sentences(text: str) -> list[str]:
    complete, rest = split_sentences(text + " ")
    return complete + ([rest.strip()] if rest.strip() else [])


def test_the_brief_is_gone_over_in_short_parts_each_ending_with_the_check() -> None:
    assert review_parts(render_brief(LUCIA, CONFIG, "es"), "es") == (
        "Te llamas Lucía Marín. Te interesa el puesto. ¿Está bien?",
        "Tienes permiso de trabajo. Puedes trabajar lunes, martes y jueves, en turno de Mañana, "
        "unas 30 horas a la semana. ¿Está bien?",
        "Podrías empezar el lunes 26 de octubre de 2026. Experiencia: dos años en una cafetería. "
        "¿Está bien?",
        "Tu teléfono es el +34 612 345 678. ¿Está bien?",
    )


def test_a_one_sentence_read_back_is_one_part() -> None:
    phone = field_readback("contact_phone", "+34612345678", "es")
    assert review_parts(phone, "es") == ("He apuntado el teléfono +34 612 345 678. ¿Está bien?",)
    assert len(review_parts(SLOT_ES, "es")) == 1
    date_en = field_readback("earliest_start_date", date(2026, 11, 2), "en")
    assert review_parts(date_en, "en") == (
        "I have that you could start on Monday 2 November 2026. Is that right?",
    )


@pytest.mark.parametrize(
    ("text", "language"),
    [
        (render_brief(LUCIA, CONFIG, "es"), "es"),
        (render_brief(LUCIA, CONFIG, "en"), "en"),
        (render_brief(LUCIA, CONFIG, "es", followup=True), "es"),
        (
            render_brief(record(name="Ane", unknown=frozenset({"hours_per_week"})), CONFIG, "es"),
            "es",
        ),
        (field_readback("earliest_start_date", date(2026, 11, 2), "es"), "es"),
        (SLOT_ES, "es"),
    ],
)
def test_parts_cover_every_fact_in_order_and_each_is_short(text: str, language: Language) -> None:
    """Nothing of the read-back is lost or reordered; the intro and the closing question are
    replaced by the short check after each part."""
    parts = review_parts(text, language)
    check = sentences(parts[0])[-1]
    bodies = [sentences(part)[:-1] for part in parts]
    assert all(sentences(part)[-1] == check for part in parts)
    whole = sentences(text)
    facts = whole[1:-1] if len(whole) > 2 else whole[:-1]  # the brief opens with an intro
    assert [s for body in bodies for s in body] == facts
    for body in bodies:
        assert 1 <= len(body) <= PART_SENTENCES
        assert len(body) == 1 or len(" ".join(body)) <= PART_CHARACTERS


# ---- the review of a cut read-back (D39) ----------------------------------------------------

T1, T2, T3 = TurnId("t1"), TurnId("t2"), TurnId("t3")
BRIEF = render_brief(LUCIA, CONFIG, "es")
FIELD = FieldTarget(field="contact_phone", revision=3)
BRIEF_TARGET = BriefTarget(revision=3)
SLOT = SlotTarget(slot_id=SlotId("slot-1"), brief_revision=3)


def said(
    review: str | None = None,
    *,
    heard: bool = False,
    part: int = 0,
    target: ConfirmationTarget = BRIEF_TARGET,
) -> Confirmation:
    """A read-back presented in T1 and, if reviewed, moved in T2."""
    stage = {
        None: None,
        "offered": ReviewOffered(turn_id=T2),
        "in_parts": ReviewInParts(part=part, parts=4, turn_id=T2),
        "waived": ReviewWaived(turn_id=T2),
    }[review]
    return Confirmation(
        confirmation_id=ConfirmationId("c1"),
        target=target,
        presentation_text=BRIEF,
        presented_turn_id=T1,
        fully_delivered=heard,
        review=stage,
    )


def test_the_current_saying_is_the_part_under_review_or_the_whole_text() -> None:
    parts = review_parts(BRIEF, "es")
    assert current_saying(said(), "es") == BRIEF
    assert current_saying(said("offered"), "es") == BRIEF
    assert current_saying(said("in_parts", part=2), "es") == parts[2]
    assert current_saying(said("waived"), "es") == BRIEF
