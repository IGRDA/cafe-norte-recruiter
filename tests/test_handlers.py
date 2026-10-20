"""Tool handlers: the domain decides, the store commits, the model is told what to do next."""

import json
from datetime import UTC, date, datetime

from pydantic import BaseModel

from cafe_norte.conversation.brief import field_readback, render_brief_es
from cafe_norte.conversation.contracts import StateUpdated, ToolContext, ToolOutcome
from cafe_norte.conversation.handlers import (
    ConfirmBriefHandler,
    ConfirmFieldHandler,
    EndSessionHandler,
    PresentConfirmationHandler,
    UpdateCandidateHandler,
)
from cafe_norte.conversation.tools import ARGUMENT_MODELS, ToolName
from cafe_norte.domain.candidate import apply_patch
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import (
    BriefTarget,
    CandidatePatch,
    CandidateRecord,
    ConfigId,
    Evidence,
    SessionId,
    SessionState,
    TurnId,
)
from cafe_norte.persistence.memory import MemoryStore
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
        session_id=SID, turn_id=TurnId(turn), now=NOW, language="es", lease_generation=0
    )


def args(name: ToolName, **payload: object) -> BaseModel:
    return ARGUMENT_MODELS[name].model_validate_json(json.dumps(payload, default=str))


class World:
    def __init__(self, candidate: CandidateRecord | None = None) -> None:
        self.store = MemoryStore()
        self.state = SessionState(
            session_id=SID,
            config_id=CONFIG.config_id,
            config_version="1",
            language="es",
            channel="text",
            candidate=candidate or CandidateRecord(),
        )
        self.update = UpdateCandidateHandler(store=self.store, configurations=CONFIGS)
        self.present = PresentConfirmationHandler(store=self.store, configurations=CONFIGS)
        self.confirm_field = ConfirmFieldHandler(store=self.store)
        self.confirm_brief = ConfirmBriefHandler(store=self.store)
        self.end = EndSessionHandler(store=self.store)

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
    expected = render_brief_es(full_record(), CONFIG)
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


async def test_capturing_a_date_or_phone_tells_the_model_to_read_it_back() -> None:
    w = await World().open()
    outcome = await w.update(
        context(),
        args(
            "update_candidate",
            patch={"name": "Ane", "earliest_start_date": "2026-10-26"},
            evidence_text="Ane, el lunes que viene",
        ),
    )
    assert outcome.model_text.startswith("Saved: name, earliest_start_date.")
    assert "present_confirmation(target=field, field=earliest_start_date)" in outcome.model_text
    readback = await w.present(
        context(), args("present_confirmation", target="field", field="earliest_start_date")
    )
    assert readback.spoken == field_readback("earliest_start_date", date(2026, 10, 26), CONFIG)


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


async def test_affirming_the_brief_leads_to_the_interview_question() -> None:
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    outcome = await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    assert outcome.ok and "interview" in outcome.model_text
    assert (await w.current()).lifecycle == "active"


async def test_end_session_sets_lifecycle_and_outcome_once() -> None:
    w = await World(full_record()).open()
    done = await w.end(context(), args("end_session", reason="candidate_done"))
    assert done.ok and isinstance(done.events[0], StateUpdated)
    state = await w.current()
    assert (state.lifecycle, state.outcome) == ("completed", "brief_only")
    again = await w.end(context("t2"), args("end_session", reason="candidate_done"))
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
