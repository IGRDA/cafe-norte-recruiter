"""The candidate's answer to the slot offer (D41): which tool the words call, decided from the
session, the words and the day. Pure; the runtime runs what it returns, through the tools the
model would call, so a model that does not copy the slot id cannot leave the choice looping."""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from cafe_norte.conversation.brief import slot_time
from cafe_norte.conversation.readback import RuntimeCall
from cafe_norte.conversation.signals import answer_to_readback
from cafe_norte.domain.contracts import (
    SessionState,
    SlotId,
    SlotOffer,
    SlotTarget,
    StoreConfiguration,
    TurnId,
)
from cafe_norte.domain.slot_choice import Ambiguous, Chosen, NoMatch, choose_slot, read_slot_words


@dataclass(frozen=True)
class Shortlist:
    """Words that fit more than one offered slot: keep these, and tell the model to ask."""

    slot_ids: tuple[SlotId, ...]
    note: str


def slot_answer(
    state: SessionState,
    text: str,
    *,
    by_button: bool,
    turn_id: TurnId,
    configuration: StoreConfiguration,
    now: datetime,
) -> RuntimeCall | Shortlist | None:
    """One slot that fits is read back, or reserved when it is the slot already read back,
    heard, and the words say yes; several are a shortlist; words that fit nothing offered are
    offered again, for the day they name. ``None``: no open offer, or the words are not a
    choice, and they are the model's."""
    offer = open_offer(state, by_button=by_button)
    if offer is None:
        return None
    zone = ZoneInfo(configuration.timezone)
    ids = [slot.slot_id for slot in offer.slots]
    words = read_slot_words(text)
    choice = choose_slot(
        words,
        [slot.starts_at_utc.astimezone(zone).replace(tzinfo=None) for slot in offer.slots],
        today=now.astimezone(zone).date(),
        shortlist=tuple(i for i, slot_id in enumerate(ids) if slot_id in offer.shortlist),
    )
    match choice:
        case Chosen(index=index) if heard_read_back_of(state, ids[index], turn_id):
            if answer_to_readback(words.rest) != "affirm":
                return None  # the slot said again without a yes: the model's to read
            return "reserve_interview", {"slot_id": ids[index]}
        case Chosen(index=index):
            return "present_confirmation", {"target": "slot", "slot_id": ids[index]}
        case NoMatch(day=day):
            intent = state.schedule_intent
            arguments = {"evidence_text": intent.text if intent else text}
            if day is not None:
                arguments["date_preference"] = day.isoformat()
            return "list_interview_slots", arguments
        case Ambiguous(indices=indices):
            options = "; ".join(
                f"{i + 1}: "
                + slot_time(offer.slots[i].starts_at_utc, configuration, state.language)
                for i in indices
            )
            return Shortlist(
                slot_ids=tuple(ids[i] for i in indices),
                note=(
                    f"The candidate's words fit more than one offered slot ({options}). Ask in "
                    "one short sentence which of these they prefer; the system reads it back."
                ),
            )
        case _:
            return None  # NotAChoice: the words are the model's


def open_offer(state: SessionState, *, by_button: bool) -> SlotOffer | None:
    """The offer a spoken answer may choose from: there is one, nothing is booked, the session
    is live, and no field or brief read-back is waiting for its own answer. A button press
    answers a read-back, never an offer."""
    offer = state.slot_offer
    pending = state.pending_confirmation
    waiting = (
        pending is not None
        and pending.status == "pending"
        and not isinstance(pending.target, SlotTarget)
    )
    if (
        by_button
        or offer is None
        or not offer.slots
        or state.booking is not None
        or state.lifecycle != "active"
        or waiting
    ):
        return None
    return offer


def heard_read_back_of(state: SessionState, slot_id: SlotId, turn_id: TurnId) -> bool:
    """That very slot was read back in an earlier turn and heard to the end: naming it again is
    an answer to "¿Te la reservo?", not a new choice."""
    pending = state.pending_confirmation
    return (
        pending is not None
        and pending.status == "pending"
        and isinstance(pending.target, SlotTarget)
        and pending.target.slot_id == slot_id
        and pending.fully_delivered
        and pending.presented_turn_id != turn_id
    )
