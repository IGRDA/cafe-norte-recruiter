"""Handlers for the interview: the offer, the slot read-back, the reservation."""

from datetime import UTC, datetime

import pytest

from cafe_norte.conversation.contracts import StateUpdated, ToolContext
from cafe_norte.conversation.handlers import (
    UpdateCandidateHandler,
)
from cafe_norte.domain.contracts import (
    Confirmation,
    ConfirmationId,
    Evidence,
    SessionId,
    SlotId,
    SlotTarget,
    TurnId,
)
from cafe_norte.errors import ServiceError
from cafe_norte.persistence.seed import seed_calendar
from tests.support.builders import CONFIGS, NOW, SID
from tests.support.tools import SLOT, Interview, World, args, context


async def test_slots_come_after_the_confirmed_brief_and_record_the_intent() -> None:
    w = Interview()
    await w.open()
    await seed_calendar(w.store, CONFIGS, now=NOW)
    early = await w.slots(context(), args("list_interview_slots", evidence_text="Sí, quiero."))
    assert not early.ok and early.summary == "brief_not_confirmed"
    assert (await w.current()).schedule_intent is None
    await w.present(context("t1"), args("present_confirmation", target="brief"))
    await w.deliver()
    await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    outcome = await w.slots(
        context("t3"), args("list_interview_slots", evidence_text="Sí, quiero.")
    )
    assert outcome.ok and outcome.summary == "offered:3"
    assert outcome.spoken.startswith(
        "Tengo estos huecos para la entrevista en Café Norte Chamberí:"
    )
    assert "miércoles 21 de octubre de 2026 a las 10:30" in outcome.spoken
    assert outcome.spoken.endswith("¿Cuál te viene mejor?")
    assert (
        f"2: slot_id={SLOT}" in outcome.model_text and "present_confirmation" in outcome.model_text
    )
    state = await w.current()
    assert state.schedule_intent == Evidence(source_turn_id=TurnId("t3"), text="Sí, quiero.")
    assert state.brief_confirmed_revision == 1 and state.candidate.revision == 1


async def test_a_date_preference_narrows_the_offer_when_it_can() -> None:
    w = await Interview().ready()
    outcome = await w.slots(
        context("t3"),
        args("list_interview_slots", evidence_text="El jueves.", date_preference="2026-10-22"),
    )
    assert outcome.ok and outcome.summary == "offered:2"
    assert "jueves 22 de octubre" in outcome.spoken and "miércoles" not in outcome.spoken
    none = await w.slots(
        context("t3"),
        args(
            "list_interview_slots", evidence_text="El año que viene.", date_preference="2027-01-01"
        ),
    )
    assert none.ok and none.summary == "offered:3"  # no match: the first three are offered


async def test_the_offer_is_remembered_in_the_order_it_was_spoken() -> None:
    """The runtime matches "el primero" or "el miércoles" against it (D41)."""
    w = await (await Interview().ready()).offered()
    offer = (await w.current()).slot_offer
    assert offer is not None and offer.shortlist == ()
    assert [s.slot_id for s in offer.slots] == [
        "chamberi_barista_v1-2026-10-20-1700",
        SLOT,
        "chamberi_barista_v1-2026-10-21-1700",
    ]
    assert offer.slots[1].starts_at_utc == datetime(2026, 10, 21, 8, 30, tzinfo=UTC)


async def test_offering_again_keeps_the_first_words_that_asked_for_an_interview() -> None:
    """A second offer (the runtime's, for another day) replaces the slots, not the evidence."""
    w = await (await Interview().ready()).offered()
    await w.slots(
        context("t5"),
        args("list_interview_slots", evidence_text="El jueves.", date_preference="2026-10-22"),
    )
    state = await w.current()
    assert state.schedule_intent == Evidence(source_turn_id=TurnId("t3"), text="Sí, quiero.")
    assert state.slot_offer is not None
    assert [s.slot_id for s in state.slot_offer.slots] == [
        "chamberi_barista_v1-2026-10-22-1030",
        "chamberi_barista_v1-2026-10-22-1700",
    ]


async def test_presenting_a_slot_clears_the_shortlist() -> None:
    w = await (await Interview().ready()).offered()
    state = await w.current()
    assert state.slot_offer is not None
    narrowed = state.slot_offer.model_copy(update={"shortlist": (SlotId(SLOT),)})
    async with w.store.transaction() as tx:
        await w.store.sessions.save(
            tx,
            state.model_copy(update={"slot_offer": narrowed}),
            expected_revision=state.candidate.revision,
        )
    await w.read_back()
    offer = (await w.current()).slot_offer
    assert offer is not None and offer.shortlist == () and len(offer.slots) == 3


async def test_the_slot_read_back_needs_an_offer_and_a_known_future_slot_of_this_store() -> None:
    w = await Interview().ready()
    no_offer = await w.present(
        context("t3"), args("present_confirmation", target="slot", slot_id=SLOT)
    )
    assert not no_offer.ok and no_offer.summary == "slot_not_offerable:no_offer"
    await w.offered()
    unknown = await w.present(
        context("t4"), args("present_confirmation", target="slot", slot_id="x")
    )
    assert not unknown.ok and unknown.summary == "slot_not_offerable:slot_unavailable"
    other = await w.present(
        context("t4"),
        args(
            "present_confirmation", target="slot", slot_id="arganzuela_barista_v1-2026-10-21-1030"
        ),
    )
    assert not other.ok and other.summary == "slot_not_offerable:slot_other_store"
    outcome = await w.present(
        context("t4"), args("present_confirmation", target="slot", slot_id=SLOT)
    )
    assert outcome.ok and outcome.summary == "presented:slot"
    assert outcome.spoken == (
        "He apuntado la entrevista en Café Norte Chamberí el miércoles 21 de octubre de 2026 "
        "a las 10:30, hora de Madrid. ¿Te la reservo?"
    )
    pending = (await w.current()).pending_confirmation
    assert pending is not None and pending.target == SlotTarget(
        slot_id=SlotId(SLOT), brief_revision=1
    )
    again = await w.present(
        context("t4"), args("present_confirmation", target="slot", slot_id=SLOT)
    )
    assert (
        again.ok
        and again.summary == "already_pending:slot"
        and "reserve_interview" in again.model_text
    )


async def test_reserve_needs_that_slot_read_back_and_the_candidates_own_answer() -> None:
    w = await (await Interview().ready()).offered()
    nothing = await w.reserve(context("t4"), args("reserve_interview", slot_id=SLOT))
    assert not nothing.ok and nothing.summary == "confirmation_mismatch"
    await w.read_back()
    other = await w.reserve(
        context("t5"), args("reserve_interview", slot_id="chamberi_barista_v1-2026-10-21-1700")
    )
    assert not other.ok and other.summary == "confirmation_mismatch"
    same_turn = await w.reserve(context("t4"), args("reserve_interview", slot_id=SLOT))
    assert not same_turn.ok and same_turn.summary == "confirmation_refused:same_turn"
    assert same_turn.idle and not nothing.idle and not other.idle
    assert (await w.current()).booking is None


async def test_reserving_commits_calendar_and_session_together_and_only_then_announces() -> None:
    w = await (await Interview().ready()).offered()
    await w.read_back()
    outcome = await w.reserve(context("t5"), args("reserve_interview", slot_id=SLOT))
    assert outcome.ok and outcome.summary == "reserved"
    assert "miércoles 21 de octubre de 2026 a las 10:30" in outcome.model_text
    assert "simulated" in outcome.model_text and "end_session" in outcome.model_text
    state = await w.current()
    booking = state.booking
    assert booking is not None and booking.slot_id == SLOT and booking.simulated is True
    assert booking.starts_at_utc == datetime(2026, 10, 21, 8, 30, tzinfo=UTC)
    assert booking.committed_at == NOW
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"
    assert booking.confirmation_id == state.pending_confirmation.confirmation_id
    assert isinstance(outcome.events[0], StateUpdated) and outcome.events[0].booking == booking
    taken = await w.store.calendar.get(SlotId(SLOT))
    assert taken is not None and taken.status == "reserved"
    assert await w.store.calendar.booking_by_key(booking.idempotency_key) == booking
    done = await w.end(context("t6"), args("end_session", reason="candidate_done"))
    assert done.ok and done.summary == "ended:completed:reserved"


async def test_a_second_reserve_call_is_refused_and_a_taken_slot_offers_fresh_ones() -> None:
    w = await (await Interview().ready()).offered()
    await w.read_back()
    await w.reserve(context("t5"), args("reserve_interview", slot_id=SLOT))
    twice = await w.reserve(context("t6"), args("reserve_interview", slot_id=SLOT))
    assert not twice.ok and twice.summary == "confirmation_refused:already_answered"
    more = await w.slots(context("t6"), args("list_interview_slots", evidence_text="Otro."))
    assert not more.ok and more.summary == "already_booked"
    # Another session took the slot between the read-back and the yes.
    rival = await (await Interview().ready()).offered()
    await rival.read_back()
    async with rival.store.transaction() as tx:
        await rival.store.calendar.reserve(
            tx, SlotId(SLOT), SessionId("someone-else"), full_confirmation(), "their-key"
        )
    lost = await rival.reserve(context("t5"), args("reserve_interview", slot_id=SLOT))
    assert not lost.ok and lost.summary == "booking_refused:slot_unavailable"
    assert "list_interview_slots" in lost.model_text
    assert (await rival.current()).booking is None


async def test_a_correction_after_the_slot_read_back_voids_it_and_the_brief() -> None:
    w = await (await Interview().ready()).offered()
    await w.read_back()
    await w.update(
        context("t5"),
        args("update_candidate", patch={"hours_per_week": 25}, evidence_text="25 horas"),
    )
    state = await w.current()
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "invalidated"
    assert state.brief_confirmed_revision == 1 and state.candidate.revision == 2
    refused = await w.reserve(context("t6"), args("reserve_interview", slot_id=SLOT))
    assert not refused.ok and refused.summary == "confirmation_refused:already_answered"


def full_confirmation() -> Confirmation:
    return Confirmation(
        confirmation_id=ConfirmationId("rival"),
        target=SlotTarget(slot_id=SlotId(SLOT), brief_revision=1),
        presentation_text="…",
        presented_turn_id=TurnId("r1"),
        fully_delivered=True,
        status="confirmed",
    )


async def test_a_handler_save_is_fenced_on_the_contexts_lease_generation() -> None:
    w = World()
    await w.store.sessions.create(w.state, access_hash="")
    await w.said("t1", "Ane")
    stale = ToolContext(
        session_id=SID, turn_id=TurnId("t1"), now=NOW, language="es", lease_generation=7
    )
    with pytest.raises(ServiceError) as refused:
        await UpdateCandidateHandler(store=w.store, configurations=CONFIGS)(
            stale, args("update_candidate", patch={"name": "Ane"}, evidence_text="Ane")
        )
    assert refused.value.code == "conflict"
