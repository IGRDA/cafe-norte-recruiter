"""Whole-record operations: apply a patch, find what is still unfinished, render the brief."""

from datetime import date

from cafe_norte.domain.contracts import (
    CandidateFieldName,
    CandidatePatch,
    CandidateRecord,
    Evidence,
    FieldError,
    StoreConfiguration,
)
from cafe_norte.domain.result import Result
from cafe_norte.errors import Language


def validate_patch(
    patch: CandidatePatch, configuration: StoreConfiguration, today: date
) -> Result[CandidatePatch, FieldError]:
    """Normalize and check a proposed patch against the fixed configuration.

    Phones become E.164 or fail with ``invalid_format``; shift names must exist in the store;
    start dates in the past fail with ``past_date``. Returns the normalized patch. Never
    touches fields the server owns."""
    raise NotImplementedError


def apply_patch(
    record: CandidateRecord, patch: CandidatePatch, evidence: Evidence
) -> CandidateRecord:
    """Apply an already validated patch: capture supplied values, mark declined/unknown ones,
    append the note, increment ``revision``. Fields the patch does not mention are untouched."""
    raise NotImplementedError


def unfinished_fields(record: CandidateRecord) -> tuple[CandidateFieldName, ...]:
    """Requested fields still ``Unset``, in the order Ana should ask about them."""
    raise NotImplementedError


def ready_for_brief(record: CandidateRecord) -> bool:
    """Every requested field is captured, confirmed, unknown or declined."""
    raise NotImplementedError


def render_brief(
    record: CandidateRecord, configuration: StoreConfiguration, language: Language
) -> str:
    """Deterministic factual brief in the candidate's language. Unknown and declined fields
    stay visible. This is the text a brief confirmation presents, and the fallback when the
    narrative summary fails."""
    raise NotImplementedError
