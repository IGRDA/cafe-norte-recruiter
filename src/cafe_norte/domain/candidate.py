"""Whole-record operations: apply a patch, find what is still unfinished, render the brief."""

from datetime import date

import phonenumbers

from cafe_norte.domain.contracts import (
    REQUESTED_FIELDS,
    CandidateFieldName,
    CandidatePatch,
    CandidateRecord,
    Evidence,
    FieldError,
    FieldState,
    StoreConfiguration,
    Unknown,
)
from cafe_norte.domain.fields import capture, decline, mark_unknown
from cafe_norte.domain.numbers import mentions_number
from cafe_norte.domain.result import Err, Ok, Result

VALUE_FIELDS: tuple[CandidateFieldName, ...] = (
    "name",
    "contact_phone",
    "interest",
    "work_authorization",
    "availability_days",
    "availability_shifts",
    "hours_per_week",
    "earliest_start_date",
    "experience",
)


def validate_patch(
    patch: CandidatePatch, configuration: StoreConfiguration, today: date, *, evidence_text: str
) -> Result[CandidatePatch, FieldError]:
    """Normalize and check a proposed patch against the fixed configuration and the words it
    is saved with.

    Phones become E.164 or fail with ``invalid_format``; shift names must exist in the store;
    start dates in the past fail with ``past_date``; hours must appear in ``evidence_text``
    (``not_in_evidence``), so a number the candidate never said is never saved. Returns the
    normalized patch. Never touches fields the server owns."""
    if patch.hours_per_week is not None and not mentions_number(
        evidence_text, patch.hours_per_week
    ):
        return Err(
            FieldError(
                field="hours_per_week",
                reason="not_in_evidence",
                detail="the candidate's words do not say this number",
            )
        )
    updates: dict[str, object] = {}
    if patch.contact_phone is not None:
        try:
            parsed = phonenumbers.parse(patch.contact_phone, "ES")
        except phonenumbers.NumberParseException:
            return Err(FieldError(field="contact_phone", reason="invalid_format"))
        if not phonenumbers.is_valid_number(parsed):
            return Err(FieldError(field="contact_phone", reason="invalid_format"))
        updates["contact_phone"] = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.E164
        )
    if patch.availability_shifts is not None:
        known = {shift.shift_id for shift in configuration.shifts}
        unknown = sorted(patch.availability_shifts - known)
        if unknown:
            return Err(
                FieldError(
                    field="availability_shifts", reason="unknown_shift", detail=",".join(unknown)
                )
            )
    if patch.earliest_start_date is not None and patch.earliest_start_date < today:
        return Err(FieldError(field="earliest_start_date", reason="past_date"))
    return Ok(patch.model_copy(update=updates))


def apply_patch(
    record: CandidateRecord, patch: CandidatePatch, evidence: Evidence
) -> CandidateRecord:
    """Apply an already validated patch: capture supplied values, mark declined/unknown ones,
    append the note, increment ``revision``. Fields the patch does not mention are untouched."""
    updates: dict[str, object] = {}
    for name in VALUE_FIELDS:
        value = getattr(patch, name)
        if value is not None:
            updates[name] = capture(_field(record, name), value, evidence).model_dump()
    for name in sorted(patch.declined):
        updates[name] = decline(_field(record, name), evidence.source_turn_id).model_dump()
    for name in sorted(patch.unknown):
        current = _field(record, name)
        attempts = current.attempts + 1 if isinstance(current, Unknown) else 1
        updates[name] = mark_unknown(current, attempts).model_dump()
    if patch.note is not None:
        updates["notes"] = (*record.notes, patch.note)
    if changed_fields(patch):
        updates["revision"] = record.revision + 1  # a note alone is not a new version of the facts
    # Re-validated so each field is the parametrized ``Captured[T]`` the record declares.
    return CandidateRecord.model_validate({**record.model_dump(), **updates})


def changed_fields(patch: CandidatePatch) -> tuple[CandidateFieldName, ...]:
    """Every field a patch mentions, as values, declined or unknown, in record order."""
    return tuple(
        name
        for name in VALUE_FIELDS
        if getattr(patch, name) is not None or name in patch.declined or name in patch.unknown
    )


def unfinished_fields(record: CandidateRecord) -> tuple[CandidateFieldName, ...]:
    """Requested fields still ``Unset``, in the order Ana should ask about them."""
    return tuple(name for name in REQUESTED_FIELDS if _field(record, name).status == "unset")


def ready_for_brief(record: CandidateRecord) -> bool:
    """Every requested field is captured, confirmed, unknown or declined."""
    return not unfinished_fields(record)


def _field(record: CandidateRecord, name: CandidateFieldName) -> FieldState[object]:
    state: FieldState[object] = getattr(record, name)
    return state
