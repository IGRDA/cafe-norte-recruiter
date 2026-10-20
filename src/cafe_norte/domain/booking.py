"""The reservation gate. One total function answers "may this session reserve this slot now?".

No work-authorization or sentiment value appears here: they are not booking gates."""

from datetime import datetime

from cafe_norte.domain.contracts import (
    BookingRefusal,
    Confirmation,
    InterviewSlot,
    SessionState,
    SlotTarget,
)
from cafe_norte.domain.result import Result


def reservation_allowed(
    state: SessionState,
    slot: InterviewSlot,
    confirmation: Confirmation | None,
    *,
    schedule_intent: bool,
    now: datetime,
) -> Result[SlotTarget, BookingRefusal]:
    """Check the five conditions, in this order: active session; brief confirmed at the current
    revision; explicit intent; a fully delivered, affirmed slot confirmation for this slot and
    this brief revision; a future, available slot of this store; no booking yet."""
    raise NotImplementedError


def idempotency_key(state: SessionState, confirmation: Confirmation) -> str:
    """Server-generated key binding session and confirmation; a retry reuses it."""
    raise NotImplementedError
