"""Patch validation and application on the whole record."""

from datetime import date
from typing import get_args

from hypothesis import assume, given

from cafe_norte.domain.candidate import (
    apply_patch,
    changed_fields,
    ready_for_brief,
    said_in,
    unfinished_fields,
    validate_patch,
)
from cafe_norte.domain.contracts import (
    CandidateFieldName,
    CandidatePatch,
    CandidateRecord,
    Captured,
    Declined,
    Evidence,
    TurnId,
    Unknown,
)
from cafe_norte.domain.fields import value_of
from cafe_norte.domain.result import Err, Ok
from tests.support.builders import CONFIG
from tests.support.strategies import candidate_records, patches

TODAY = date(2026, 10, 20)
EVIDENCE = Evidence(source_turn_id=TurnId("t1"), text="me llamo Lucía")


def test_a_valid_patch_passes_unchanged() -> None:
    patch = CandidatePatch(name="Lucía", hours_per_week=30)
    assert validate_patch(patch, CONFIG, TODAY, evidence_text="Lucía, 30 horas") == Ok(patch)


def test_phones_are_normalized_to_e164_or_refused() -> None:
    ok = validate_patch(
        CandidatePatch(contact_phone="612 34 56 78"), CONFIG, TODAY, evidence_text=""
    )
    assert isinstance(ok, Ok) and ok.value.contact_phone == "+34612345678"
    bad = validate_patch(CandidatePatch(contact_phone="12"), CONFIG, TODAY, evidence_text="")
    assert isinstance(bad, Err) and bad.error.reason == "invalid_format"


def test_unknown_shifts_and_past_dates_are_refused() -> None:
    shifts = validate_patch(
        CandidatePatch(availability_shifts=frozenset({"night"})), CONFIG, TODAY, evidence_text=""
    )
    assert isinstance(shifts, Err) and shifts.error.reason == "unknown_shift"
    assert shifts.error.detail == "night"
    past = validate_patch(
        CandidatePatch(earliest_start_date=date(2026, 1, 1)), CONFIG, TODAY, evidence_text=""
    )
    assert isinstance(past, Err) and past.error.reason == "past_date"
    today = validate_patch(
        CandidatePatch(earliest_start_date=TODAY), CONFIG, TODAY, evidence_text=""
    )
    assert isinstance(today, Ok)


def test_apply_captures_values_marks_declined_and_unknown_and_bumps_revision() -> None:
    record = CandidateRecord()
    patch = CandidatePatch(
        name="Lucía",
        declined=frozenset({"contact_phone"}),
        unknown=frozenset({"hours_per_week"}),
        note="solo mañanas",
    )
    updated = apply_patch(record, patch, EVIDENCE)
    assert updated.revision == 1
    assert updated.name == Captured[str](value="Lucía", evidence=EVIDENCE)
    assert updated.contact_phone == Declined(source_turn_id=TurnId("t1"))
    assert updated.hours_per_week == Unknown(attempts=1)
    assert updated.notes == ("solo mañanas",)
    assert updated.interest.status == "unset"
    # A second unknown attempt counts up; the record stays a valid frozen model.
    again = apply_patch(updated, CandidatePatch(unknown=frozenset({"hours_per_week"})), EVIDENCE)
    assert again.hours_per_week == Unknown(attempts=2) and again.revision == 2
    assert CandidateRecord.model_validate_json(again.model_dump_json()) == again


def test_a_note_alone_does_not_bump_the_revision() -> None:
    record = apply_patch(CandidateRecord(), CandidatePatch(name="Lucía"), EVIDENCE)
    noted = apply_patch(record, CandidatePatch(note="quiere entrevista"), EVIDENCE)
    assert noted.revision == record.revision == 1
    assert noted.notes == ("quiere entrevista",)


def test_changed_and_unfinished_fields() -> None:
    patch = CandidatePatch(name="Lucía", declined=frozenset({"experience"}))
    assert changed_fields(patch) == ("name", "experience")
    record = apply_patch(CandidateRecord(), patch, EVIDENCE)
    assert unfinished_fields(record) == (
        "interest",
        "work_authorization",
        "availability_days",
        "availability_shifts",
        "hours_per_week",
        "earliest_start_date",
    )
    assert not ready_for_brief(record)
    everything = CandidatePatch(unknown=frozenset(unfinished_fields(record)))
    assert ready_for_brief(apply_patch(record, everything, EVIDENCE))


def test_hours_need_their_number_in_the_candidates_words() -> None:
    """The hosted call of 21 October: "Por la mañana" was saved with 35 hours, the store's
    contract, which the candidate never said."""
    invented = CandidatePatch(availability_shifts=frozenset({"morning"}), hours_per_week=35)
    refused = validate_patch(invented, CONFIG, TODAY, evidence_text="Por la mañana.")
    assert isinstance(refused, Err) and refused.error.field == "hours_per_week"
    assert refused.error.reason == "not_in_evidence"
    said = validate_patch(invented, CONFIG, TODAY, evidence_text="Por la mañana, unas 35 horas")
    assert isinstance(said, Ok)


# ---- evidence is the candidate's own words (D46) -------------------------------------------------

SAID = (
    (TurnId("t1"), "Me llamo Lucía Marín."),
    (TurnId("t2"), "Sí, tengo permiso de trabajo."),
    (TurnId("t3"), "Puedo lunes y jueves."),
)


def test_evidence_found_in_one_message_is_that_whole_message() -> None:
    assert said_in("lucia marin", SAID) == (TurnId("t1"), "Me llamo Lucía Marín.")
    assert said_in("Puedo lunes y jueves.", SAID) == (TurnId("t3"), "Puedo lunes y jueves.")


def test_the_latest_message_that_holds_it_wins() -> None:
    said = (*SAID, (TurnId("t4"), "Perdona: me llamo Lucía Marín Sanz."))
    assert said_in("me llamo Lucía Marín", said) == (TurnId("t4"), said[-1][1])


def test_sentences_from_several_messages_are_evidence_kept_as_the_latest_message() -> None:
    """The model batches facts and joins the messages they came from; every sentence was said,
    so the save stands, and the evidence kept is one whole message (a live S02 run of
    22 October 2026 ran out of tool rounds while each batch was refused)."""
    stitched = "Me llamo Lucía Marín. Sí, tengo permiso de trabajo."
    assert said_in(stitched, SAID) == (TurnId("t2"), "Sí, tengo permiso de trabajo.")
    commas = "Me llamo Lucía Marín, tengo permiso de trabajo, puedo lunes y jueves"
    assert said_in(commas, SAID) == (TurnId("t3"), "Puedo lunes y jueves.")


def test_words_never_said_are_not_evidence() -> None:
    """Live S01 (22 October 2026): the model cited "no tengo experiencia previa", which the
    candidate never said."""
    assert said_in("no tengo experiencia previa", SAID) is None
    assert said_in("Me llamo Lucía Marín. No tengo experiencia previa.", SAID) is None
    assert said_in("Marí", SAID) is None  # whole words only
    assert said_in(" ¿? ", SAID) is None


# ---- laws of apply_patch -------------------------------------------------------------------------


@given(candidate_records(), patches())
def test_a_patch_bumps_the_revision_exactly_when_it_changes_a_fact(
    record: CandidateRecord, patch: CandidatePatch
) -> None:
    after = apply_patch(record, patch, EVIDENCE)

    assert after.revision == record.revision + (1 if changed_fields(patch) else 0)


@given(candidate_records(), patches())
def test_a_patch_touches_only_the_fields_it_names_and_appends_its_note(
    record: CandidateRecord, patch: CandidatePatch
) -> None:
    after = apply_patch(record, patch, EVIDENCE)

    named = set(changed_fields(patch))
    for name in set(get_args(CandidateFieldName)) - named:
        assert getattr(after, name) == getattr(record, name)
    for name in named:
        expected = (
            "declined" if name in patch.declined else "unknown" if name in patch.unknown else None
        )
        if expected is None:
            assert value_of(getattr(after, name)) == getattr(patch, name)
        else:
            assert getattr(after, name).status == expected
    assert after.notes == record.notes + ((patch.note,) if patch.note is not None else ())


@given(candidate_records(), patches(), patches())
def test_patches_on_different_fields_commute(
    record: CandidateRecord, first: CandidatePatch, second: CandidatePatch
) -> None:
    assume(not set(changed_fields(first)) & set(changed_fields(second)))
    first, second = (
        first.model_copy(update={"note": None}),
        second.model_copy(update={"note": None}),
    )

    one_way = apply_patch(apply_patch(record, first, EVIDENCE), second, EVIDENCE)
    other_way = apply_patch(apply_patch(record, second, EVIDENCE), first, EVIDENCE)

    assert one_way == other_way
