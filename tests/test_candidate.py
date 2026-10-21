"""Patch validation and application on the whole record."""

from datetime import date

from cafe_norte.domain.candidate import (
    apply_patch,
    changed_fields,
    ready_for_brief,
    unfinished_fields,
    validate_patch,
)
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import (
    CandidatePatch,
    CandidateRecord,
    Captured,
    ConfigId,
    Declined,
    Evidence,
    TurnId,
    Unknown,
)
from cafe_norte.domain.result import Err, Ok
from tests.support import CONFIG_DIR

CONFIG = load_configurations(CONFIG_DIR)[ConfigId("chamberi_barista_v1")]
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
