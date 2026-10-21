"""The reservation gate. One total function answers "may this session reserve this slot now?".

No work-authorization or sentiment value appears here: they are not booking gates."""

from datetime import datetime
from hashlib import sha256

from cafe_norte.domain.contracts import (
    BookingRefusal,
    Confirmation,
    InterviewSlot,
    SessionState,
    SlotTarget,
)
from cafe_norte.domain.result import Err, Ok, Result


def slot_offerable(
    state: SessionState, slot: InterviewSlot, *, now: datetime
) -> BookingRefusal | None:
    """Why this slot may not be offered or booked to this session now, if anything: wrong
    store, already started, or taken. Shared by the read-back and the reservation."""
    if slot.config_id != state.config_id:
        return "slot_other_store"
    if slot.starts_at_utc <= now:
        return "slot_in_past"
    if slot.status != "available":
        return "slot_unavailable"
    return None


def reservation_allowed(
    state: SessionState,
    slot: InterviewSlot,
    confirmation: Confirmation | None,
    *,
    now: datetime,
) -> Result[SlotTarget, BookingRefusal]:
    """Check the five conditions, in this order: active session; brief confirmed at the current
    revision; explicit intent; a fully delivered, affirmed slot confirmation for this slot and
    this brief revision; a future, available slot of this store; no booking yet."""
    revision = state.candidate.revision
    if state.lifecycle != "active":
        return Err("session_not_active")
    if state.brief_confirmed_revision != revision:
        return Err("brief_not_confirmed")
    if state.schedule_intent is None:
        return Err("no_schedule_intent")
    if confirmation is None:
        return Err("confirmation_missing")
    if not confirmation.fully_delivered:
        return Err("confirmation_not_delivered")
    target = confirmation.target
    if (
        not isinstance(target, SlotTarget)
        or target.slot_id != slot.slot_id
        or target.brief_revision != revision
        or confirmation.status != "confirmed"
    ):
        return Err("confirmation_mismatch")
    refusal = slot_offerable(state, slot, now=now)
    if refusal is not None:
        return Err(refusal)
    if state.booking is not None:
        return Err("already_booked")
    return Ok(target)


def idempotency_key(state: SessionState, confirmation: Confirmation) -> str:
    """Server-generated key binding session and confirmation; a retry reuses it."""
    return sha256(f"{state.session_id}:{confirmation.confirmation_id}".encode()).hexdigest()
