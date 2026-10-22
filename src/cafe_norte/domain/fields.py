"""Transitions of one collected field. Total functions over ``FieldState[T]``.

Laws (pinned by tests/unit/test_field_algebra.py):

* ``capture`` always yields ``Captured`` with the given value, whatever the previous state, so
  a correction after confirmation drops the stale confirmation.
* ``confirm`` promotes ``Captured``, preserving value and evidence; ``Confirmed`` is unchanged.
* ``value_of`` is ``None`` exactly for ``Unset``, ``Unknown`` and ``Declined``.
"""

from typing import TypeVar

from cafe_norte.domain.contracts import (
    Captured,
    ConfirmationId,
    Confirmed,
    Declined,
    Evidence,
    FieldError,
    FieldState,
    TurnId,
    Unknown,
)
from cafe_norte.domain.result import Err, Ok, Result

T = TypeVar("T")


def capture[T](field: FieldState[T], value: T, evidence: Evidence) -> Captured[T]:
    """Record a value the candidate just supplied. Any earlier confirmation is void."""
    return Captured(value=value, evidence=evidence)


def confirm[T](
    field: FieldState[T], confirmation_id: ConfirmationId
) -> Result[Confirmed[T], FieldError]:
    """Promote a captured value the candidate has just confirmed as read back."""
    if isinstance(field, Captured):
        return Ok(
            Confirmed(value=field.value, evidence=field.evidence, confirmation_id=confirmation_id)
        )
    if isinstance(field, Confirmed):
        return Ok(field)
    return Err(FieldError(field=None, reason="not_captured", detail=field.status))


def mark_unknown[T](field: FieldState[T], attempts: int) -> Unknown:
    """Give up after the clarification budget; the brief shows the gap rather than a guess."""
    return Unknown(attempts=attempts)


def decline[T](field: FieldState[T], source_turn_id: TurnId) -> Declined:
    """The candidate refused to answer; recorded, never asked again."""
    return Declined(source_turn_id=source_turn_id)


def value_of[T](field: FieldState[T]) -> T | None:
    if isinstance(field, Captured | Confirmed):
        return field.value
    return None
