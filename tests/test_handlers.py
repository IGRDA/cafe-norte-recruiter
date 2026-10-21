"""Tool handlers: the domain decides, the store commits, the model is told what to do next."""

import json
from datetime import UTC, date, datetime

import pytest
from pydantic import BaseModel

from cafe_norte.conversation.brief import field_readback, render_brief
from cafe_norte.conversation.contracts import StateUpdated, ToolContext, ToolOutcome
from cafe_norte.conversation.handlers import (
    NEXT_STEP,
    ConfirmBriefHandler,
    ConfirmFieldHandler,
    EndSessionHandler,
    ListInterviewSlotsHandler,
    PresentConfirmationHandler,
    ReserveInterviewHandler,
    ReviewReadbackHandler,
    UpdateCandidateHandler,
)
from cafe_norte.conversation.readback import review_parts
from cafe_norte.conversation.tools import ARGUMENT_MODELS, ToolName
from cafe_norte.domain.candidate import apply_patch
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import (
    BriefTarget,
    CandidatePatch,
    CandidateRecord,
    ConfigId,
    Confirmation,
    ConfirmationId,
    Evidence,
    FieldTarget,
    ReviewInParts,
    ReviewOffered,
    ReviewWaived,
    SessionId,
    SessionState,
    SlotId,
    SlotTarget,
    TurnId,
)
from cafe_norte.errors import ServiceError
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.persistence.seed import seed_calendar
from tests.support import CONFIG_DIR

CONFIGS = load_configurations(CONFIG_DIR)
CONFIG = CONFIGS[ConfigId("chamberi_barista_v1")]
SID = SessionId("s")
NOW = datetime(2026, 10, 20, 10, tzinfo=UTC)
EVIDENCE = Evidence(source_turn_id=TurnId("t0"), text="…")
FULL = CandidatePatch(
    name="Lucía Marín",
    interest="yes",
    work_authorization="yes",
    availability_days=frozenset({"mon", "tue", "thu"}),
    availability_shifts=frozenset({"morning"}),
    hours_per_week=30,
    earliest_start_date=date(2026, 10, 26),
    experience="dos años en una cafetería",
)


def context(turn: str = "t1") -> ToolContext:
    return ToolContext(
        session_id=SID, turn_id=TurnId(turn), now=NOW, language="es", lease_generation=None
    )


def args(name: ToolName, **payload: object) -> BaseModel:
    return ARGUMENT_MODELS[name].model_validate_json(json.dumps(payload, default=str))


class World:
    def __init__(
        self, candidate: CandidateRecord | None = None, store: MemoryStore | None = None
    ) -> None:
        self.store = store or MemoryStore()
        self.state = SessionState(
            session_id=SID,
            config_id=CONFIG.config_id,
            config_version="1",
            language="es",
            channel="text",
            created_at=NOW,
            candidate=candidate or CandidateRecord(),
        )
        self.update = UpdateCandidateHandler(store=self.store, configurations=CONFIGS)
        self.present = PresentConfirmationHandler(store=self.store, configurations=CONFIGS)
        self.confirm_field = ConfirmFieldHandler(store=self.store)
        self.confirm_brief = ConfirmBriefHandler(store=self.store)
        self.end = EndSessionHandler(store=self.store, configurations=CONFIGS)
        self.reserve = ReserveInterviewHandler(store=self.store, configurations=CONFIGS)
        self.review = ReviewReadbackHandler(
            store=self.store,
            configurations=CONFIGS,
            targets={
                "field": self.confirm_field,
                "brief": self.confirm_brief,
                "slot": self.reserve,
            },
        )

    async def open(self) -> "World":
        await self.store.sessions.create(self.state, access_hash="")
        return self

    async def current(self) -> SessionState:
        state = await self.store.sessions.get(SID)
        assert state is not None
        return state

    async def deliver(self) -> None:
        """What the runtime does after speaking a presentation."""
        state = await self.current()
        assert state.pending_confirmation is not None
        pending = state.pending_confirmation.model_copy(update={"fully_delivered": True})
        async with self.store.transaction() as tx:
            await self.store.sessions.save(
                tx,
                state.model_copy(update={"pending_confirmation": pending}),
                expected_revision=state.candidate.revision,
            )


def full_record() -> CandidateRecord:
    return apply_patch(CandidateRecord(), FULL, EVIDENCE)


async def test_the_brief_is_refused_until_every_requested_field_is_settled() -> None:
    w = await World().open()
    outcome = await w.present(context(), args("present_confirmation", target="brief"))
    assert not outcome.ok and outcome.summary == "brief_not_ready:name"
    assert "name" in outcome.model_text and outcome.spoken == ""
    assert (await w.current()).pending_confirmation is None


async def test_only_phone_and_date_have_field_readbacks() -> None:
    w = await World(full_record()).open()
    outcome = await w.present(context(), args("present_confirmation", target="field", field="name"))
    assert not outcome.ok and outcome.summary == "no_readback_for:name"


async def test_presenting_the_brief_speaks_the_exact_text_that_becomes_pending() -> None:
    w = await World(full_record()).open()
    outcome = await w.present(context(), args("present_confirmation", target="brief"))
    expected = render_brief(full_record(), CONFIG, "es")
    assert outcome.ok and outcome.spoken == expected
    assert "already spoken" in outcome.model_text
    state = await w.current()
    pending = state.pending_confirmation
    assert pending is not None and pending.status == "pending"
    assert pending.target == BriefTarget(revision=1)
    assert pending.presentation_text == expected and pending.fully_delivered is False
    assert isinstance(outcome.events[0], StateUpdated)
    assert outcome.events[0].pending_confirmation == pending


async def test_a_correction_after_the_brief_invalidates_it() -> None:
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    outcome = await w.update(
        context("t2"),
        args("update_candidate", patch={"hours_per_week": 25}, evidence_text="son 25 horas"),
    )
    assert outcome.ok
    state = await w.current()
    assert state.candidate.revision == 2
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "invalidated"
    assert "present the brief again" in outcome.model_text


async def test_capturing_a_date_or_phone_speaks_the_read_back_itself() -> None:
    """No model decision in between: the read-back is pending the moment the value is saved."""
    w = await World().open()
    outcome = await w.update(
        context(),
        args(
            "update_candidate",
            patch={"name": "Ane", "earliest_start_date": "2026-10-26"},
            evidence_text="Ane, el lunes que viene",
        ),
    )
    assert outcome.ok
    assert outcome.spoken == field_readback("earliest_start_date", date(2026, 10, 26), "es")
    assert "already spoken" in outcome.model_text
    state = await w.current()
    pending = state.pending_confirmation
    assert pending is not None and pending.status == "pending"
    assert isinstance(pending.target, FieldTarget)
    assert pending.target.field == "earliest_start_date"
    assert outcome.events[0].pending_confirmation == pending  # type: ignore[union-attr]


async def test_resending_a_known_value_changes_nothing_and_points_at_the_pending_answer() -> None:
    """Live: after "sí lo es" the model re-sent the date; it was read back a second time."""
    w = await World().open()
    first = args(
        "update_candidate",
        patch={"earliest_start_date": "2026-11-01"},
        evidence_text="1 de noviembre",
    )
    await w.update(context(), first)
    await w.deliver()
    again = await w.update(context("t2"), first)
    assert again.ok and again.spoken == "" and again.summary == "unchanged"
    assert "confirm_field" in again.model_text
    state = await w.current()
    assert state.candidate.revision == 1
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "pending"
    assert state.pending_confirmation.presented_turn_id == TurnId("t1")


async def test_resending_a_confirmed_value_keeps_it_confirmed() -> None:
    w = await World(full_record()).open()
    await w.present(
        context(), args("present_confirmation", target="field", field="earliest_start_date")
    )
    await w.deliver()
    await w.confirm_field(context("t2"), args("confirm_field", answer="affirm"))
    again = await w.update(
        context("t3"),
        args(
            "update_candidate", patch={"earliest_start_date": "2026-10-26"}, evidence_text="el 26"
        ),
    )
    assert again.ok and again.summary == "unchanged"
    state = await w.current()
    assert state.candidate.earliest_start_date.status == "confirmed"
    assert state.candidate.revision == 1


async def test_presenting_the_same_pending_read_back_again_is_a_no_op() -> None:
    """Live: the model re-presented the date read-back and it was spoken twice."""
    w = await World(full_record()).open()
    first = await w.present(
        context(), args("present_confirmation", target="field", field="earliest_start_date")
    )
    await w.deliver()
    again = await w.present(
        context("t2"), args("present_confirmation", target="field", field="earliest_start_date")
    )
    assert again.ok and again.spoken == "" and again.summary == "already_pending:field"
    assert "confirm_field" in again.model_text
    state = await w.current()
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.presented_turn_id == TurnId("t1")
    assert state.pending_confirmation.presentation_text == first.spoken


async def test_the_brief_waits_for_an_unanswered_field_read_back() -> None:
    w = await World(full_record()).open()
    await w.present(
        context(), args("present_confirmation", target="field", field="earliest_start_date")
    )
    await w.deliver()
    outcome = await w.present(context("t2"), args("present_confirmation", target="brief"))
    assert not outcome.ok and outcome.summary == "readback_pending:earliest_start_date"
    assert "confirm_field" in outcome.model_text


async def test_candidate_done_with_an_unconfirmed_brief_reads_the_brief_again() -> None:
    """Live: the model closed anyway and the session hung open. Instead of a refusal the
    candidate hears the brief and a "sí" closes it properly."""
    w = await World(full_record()).open()
    outcome = await w.end(context(), args("end_session", reason="candidate_done"))
    assert not outcome.ok and outcome.summary == "brief_re_presented"
    assert outcome.spoken == render_brief(full_record(), CONFIG, "es")
    assert "wait" in outcome.model_text.lower()
    state = await w.current()
    assert state.lifecycle == "active"
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "pending"


async def test_candidate_done_with_fields_missing_names_the_next_field() -> None:
    w = await World().open()
    refused = await w.end(context(), args("end_session", reason="candidate_done"))
    assert not refused.ok and refused.summary == "brief_not_ready:name"


async def test_candidate_done_needs_the_brief_confirmed_at_the_current_revision() -> None:
    w = await World(full_record()).open()
    refused = await w.end(context(), args("end_session", reason="candidate_done"))
    assert not refused.ok
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    done = await w.end(context("t3"), args("end_session", reason="candidate_done"))
    assert done.ok
    assert (await w.current()).outcome == "brief_only"


async def test_a_note_after_the_confirmed_brief_keeps_it_confirmed() -> None:
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    outcome = await w.update(
        context("t3"),
        args("update_candidate", patch={"note": "quiere entrevista"}, evidence_text="sí"),
    )
    assert outcome.ok and outcome.summary == "captured:note"
    state = await w.current()
    assert state.candidate.revision == 1 and state.candidate.notes == ("quiere entrevista",)
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"


async def test_the_interview_answer_after_the_confirmed_brief_leads_to_the_end() -> None:
    """Issue #10: a note saved on a confirmed brief is the interview answer; the model is
    told to end the session, not to ask about the interview again."""
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    saved = await w.update(
        context("t3"),
        args("update_candidate", patch={"note": "quiere entrevista"}, evidence_text="sí"),
    )
    assert saved.ok and "end_session" in saved.model_text
    assert NEXT_STEP["interview"] not in saved.model_text
    done = await w.end(context("t4"), args("end_session", reason="candidate_done"))
    assert done.ok and done.summary == "ended:completed:brief_only"


async def test_a_read_back_that_was_not_fully_heard_is_gone_over_in_parts() -> None:
    """The hosted call: "Mhmm" over the brief left it unheard and D35 read it again, word for
    word, and it was cut again. Presented again, a cut read-back starts with its first part."""
    w = await World(full_record()).open()
    first = await w.present(context("t1"), args("present_confirmation", target="brief"))
    again = await w.present(context("t2"), args("present_confirmation", target="brief"))
    parts = review_parts(first.spoken, "es")
    assert again.ok and again.summary == f"review:part:1/{len(parts)}"
    assert again.spoken == parts[0]  # never the whole text a second time
    pending = (await w.current()).pending_confirmation
    assert pending is not None and pending.presentation_text == first.spoken
    assert pending.review == ReviewInParts(part=0, parts=len(parts), turn_id=TurnId("t2"))
    assert pending.presented_turn_id == TurnId("t2") and pending.fully_delivered is False
    under_review = await w.present(context("t3"), args("present_confirmation", target="brief"))
    assert under_review.spoken == "" and "review_readback" in under_review.model_text


async def test_not_delivered_tells_the_model_to_pass_the_answer_to_the_review() -> None:
    w = await World(full_record()).open()
    await w.present(context("t1"), args("present_confirmation", target="brief"))
    refused = await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    assert not refused.ok and "review_readback" in refused.model_text
    assert "present_confirmation" not in refused.model_text


async def test_the_model_cannot_answer_a_read_back_in_the_turn_it_was_presented() -> None:
    w = await World(full_record()).open()
    await w.present(context("t1"), args("present_confirmation", target="brief"))
    await w.deliver()
    same_turn = await w.confirm_brief(context("t1"), args("confirm_brief", answer="affirm"))
    assert not same_turn.ok and same_turn.summary == "confirmation_refused:same_turn"
    assert "wait" in same_turn.model_text.lower()
    assert (await w.current()).pending_confirmation.status == "pending"  # type: ignore[union-attr]


async def test_affirming_a_field_readback_confirms_the_field_without_a_new_revision() -> None:
    w = await World(full_record()).open()
    await w.present(
        context(), args("present_confirmation", target="field", field="earliest_start_date")
    )
    refused = await w.confirm_field(context("t2"), args("confirm_field", answer="affirm"))
    assert not refused.ok and refused.summary == "confirmation_refused:not_delivered"
    await w.deliver()
    outcome = await w.confirm_field(context("t2"), args("confirm_field", answer="affirm"))
    assert outcome.ok
    state = await w.current()
    assert state.candidate.earliest_start_date.status == "confirmed"
    assert state.candidate.revision == 1
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"


async def test_denying_the_brief_rejects_it_and_asks_for_the_correction() -> None:
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    outcome = await w.confirm_brief(context("t2"), args("confirm_brief", answer="deny"))
    assert outcome.ok and "ask what is wrong" in outcome.model_text
    state = await w.current()
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "rejected"


async def test_affirming_the_brief_invites_questions_before_the_interview() -> None:
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    outcome = await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    assert outcome.ok and outcome.model_text.endswith(NEXT_STEP["questions"])
    assert (await w.current()).lifecycle == "active"


async def test_end_session_sets_lifecycle_and_outcome_once() -> None:
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    done = await w.end(context("t3"), args("end_session", reason="candidate_done"))
    assert done.ok and isinstance(done.events[0], StateUpdated)
    state = await w.current()
    assert (state.lifecycle, state.outcome) == ("completed", "brief_only")
    again = await w.end(context("t4"), args("end_session", reason="candidate_done"))
    assert not again.ok and again.summary == "lifecycle_refused:completed"


async def test_not_interested_stops_with_that_outcome() -> None:
    no = apply_patch(CandidateRecord(), CandidatePatch(interest="no"), EVIDENCE)
    w = await World(no).open()
    outcome = await w.end(context(), args("end_session", reason="not_interested"))
    assert outcome.ok
    state = await w.current()
    assert (state.lifecycle, state.outcome) == ("stopped", "not_interested")


def test_tool_outcome_spoken_defaults_to_nothing() -> None:
    assert ToolOutcome(ok=True, model_text="x", summary="y").spoken == ""


# ---- interview: offer, read-back, reservation --------------------------------------------------


SLOT = "chamberi_barista_v1-2026-10-21-1030"


class Interview(World):
    """A world with the calendar seeded and the brief confirmed at revision 1."""

    def __init__(self) -> None:
        super().__init__(full_record(), MemoryStore(clock=lambda: NOW))
        self.slots = ListInterviewSlotsHandler(store=self.store, configurations=CONFIGS)

    async def ready(self) -> "Interview":
        await self.open()
        await seed_calendar(self.store, CONFIGS, now=NOW)
        await self.present(context("t1"), args("present_confirmation", target="brief"))
        await self.deliver()
        await self.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
        return self

    async def offered(self) -> "Interview":
        await self.slots(context("t3"), args("list_interview_slots", evidence_text="Sí, quiero."))
        return self

    async def read_back(self, slot_id: str = SLOT, turn: str = "t4") -> ToolOutcome:
        outcome = await self.present(
            context(turn), args("present_confirmation", target="slot", slot_id=slot_id)
        )
        await self.deliver()
        return outcome


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
    stale = ToolContext(
        session_id=SID, turn_id=TurnId("t1"), now=NOW, language="es", lease_generation=7
    )
    with pytest.raises(ServiceError) as refused:
        await UpdateCandidateHandler(store=w.store, configurations=CONFIGS)(
            stale, args("update_candidate", patch={"name": "Ane"}, evidence_text="Ane")
        )
    assert refused.value.code == "conflict"


# ---- going over a read-back the candidate cut (D39) ------------------------------------------


async def cut_brief() -> tuple[World, str]:
    """The brief said in t1 and cut by the candidate: not heard to the end."""
    w = await World(full_record()).open()
    said = await w.present(context("t1"), args("present_confirmation", target="brief"))
    return w, said.spoken


async def test_a_yes_over_a_cut_read_back_earns_one_offer_in_the_models_words() -> None:
    w, _ = await cut_brief()
    offered = await w.review(context("t2"), args("review_readback", answer="affirm"))
    assert offered.ok and offered.summary == "review:offered" and offered.spoken == ""
    assert "offer" in offered.model_text and "review_readback" in offered.model_text
    pending = (await w.current()).pending_confirmation
    assert pending is not None and pending.review == ReviewOffered(turn_id=TurnId("t2"))
    assert isinstance(offered.events[0], StateUpdated)


async def test_going_over_it_says_each_part_and_the_yes_to_the_last_confirms() -> None:
    w, text = await cut_brief()
    parts = review_parts(text, "es")
    await w.review(context("t2"), args("review_readback", answer="affirm"))
    for number, part in enumerate(parts, start=1):
        said = await w.review(context(f"t{number + 2}"), args("review_readback", answer="affirm"))
        assert said.ok and said.summary == f"review:part:{number}/{len(parts)}"
        assert said.spoken == part and "already spoken" in said.model_text
        await w.deliver()
    confirmed = await w.review(context("t9"), args("review_readback", answer="affirm"))
    assert confirmed.ok and confirmed.summary == "brief:confirmed"
    state = await w.current()
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"
    assert state.brief_confirmed_revision == 1


async def test_carrying_on_after_the_offer_confirms_it_as_waived_in_one_call() -> None:
    w, _ = await cut_brief()
    await w.review(context("t2"), args("review_readback", answer="skip"))  # before: the offer
    waived = await w.review(context("t3"), args("review_readback", answer="skip"))
    assert waived.ok and waived.summary == "brief:confirmed"
    assert NEXT_STEP["questions"] in waived.model_text
    first, last = waived.events[0], waived.events[-1]
    assert isinstance(first, StateUpdated) and isinstance(last, StateUpdated)
    assert first.pending_confirmation is not None
    assert first.pending_confirmation.status == "pending"  # the waiver is saved first
    assert first.pending_confirmation.review == ReviewWaived(turn_id=TurnId("t3"))
    state = await w.current()
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"
    assert state.pending_confirmation.review == ReviewWaived(turn_id=TurnId("t3"))


async def test_a_cut_field_read_back_carried_on_confirms_the_field() -> None:
    w = await World(full_record()).open()
    await w.present(
        context("t1"), args("present_confirmation", target="field", field="earliest_start_date")
    )
    await w.review(context("t2"), args("review_readback", answer="affirm"))
    waived = await w.review(context("t3"), args("review_readback", answer="skip"))
    assert waived.ok and waived.summary == "field:confirmed"
    assert (await w.current()).candidate.earliest_start_date.status == "confirmed"


async def test_a_cut_slot_read_back_carried_on_is_booked() -> None:
    w = await (await Interview().ready()).offered()
    await w.present(context("t4"), args("present_confirmation", target="slot", slot_id=SLOT))
    await w.review(context("t5"), args("review_readback", answer="affirm"))
    booked = await w.review(context("t6"), args("review_readback", answer="skip"))
    assert booked.ok and booked.summary == "reserved"
    booking = (await w.current()).booking
    assert booking is not None and booking.slot_id == SLOT


async def test_the_review_refuses_what_the_domain_refuses() -> None:
    w = await World(full_record()).open()
    nothing = await w.review(context("t1"), args("review_readback", answer="affirm"))
    assert not nothing.ok and nothing.summary == "review_refused:nothing_pending"
    await w.present(context("t1"), args("present_confirmation", target="brief"))
    same_turn = await w.review(context("t1"), args("review_readback", answer="affirm"))
    assert not same_turn.ok and same_turn.summary == "review_refused:same_turn"
    assert "wait" in same_turn.model_text.lower()
    await w.review(context("t2"), args("review_readback", answer="affirm"))
    twice = await w.review(context("t2"), args("review_readback", answer="affirm"))
    assert not twice.ok and twice.summary == "review_refused:same_turn"


async def test_reserve_on_a_cut_slot_read_back_points_at_the_review() -> None:
    w = await (await Interview().ready()).offered()
    await w.present(context("t4"), args("present_confirmation", target="slot", slot_id=SLOT))
    refused = await w.reserve(context("t5"), args("reserve_interview", slot_id=SLOT))
    assert refused.summary == "confirmation_refused:not_delivered"
    assert "review_readback" in refused.model_text


async def test_a_save_beside_a_cut_read_back_points_at_the_review() -> None:
    w = await World(full_record()).open()
    await w.present(
        context("t1"), args("present_confirmation", target="field", field="earliest_start_date")
    )
    saved = await w.update(
        context("t2"),
        args("update_candidate", patch={"note": "tiene coche"}, evidence_text="tengo coche"),
    )
    assert saved.ok and "review_readback" in saved.model_text
    assert "confirm_field" not in saved.model_text
