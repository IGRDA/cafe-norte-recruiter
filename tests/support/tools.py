"""Calling tool handlers directly: the context a turn gives them, validated arguments, and a
``World`` of real handlers over a memory store with no model and no runtime."""

import json
import uuid

from pydantic import BaseModel

from cafe_norte.conversation.contracts import ToolContext, ToolOutcome
from cafe_norte.conversation.handlers import (
    ConfirmBriefHandler,
    ConfirmFieldHandler,
    EndSessionHandler,
    ListInterviewSlotsHandler,
    PresentConfirmationHandler,
    ReserveInterviewHandler,
    ReviewReadbackHandler,
    UpdateCandidateHandler,
)
from cafe_norte.conversation.tools import ARGUMENT_MODELS, ToolName
from cafe_norte.domain.contracts import CandidateRecord, InputId, SessionState, TurnId
from cafe_norte.persistence.contracts import TurnRecord
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.persistence.seed import seed_calendar
from tests.support.builders import CONFIG, CONFIGS, NOW, SID, full_record


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
        self.update_handler = UpdateCandidateHandler(store=self.store, configurations=CONFIGS)
        self.present_handler = PresentConfirmationHandler(store=self.store, configurations=CONFIGS)
        self.confirm_field = ConfirmFieldHandler(store=self.store)
        self.confirm_brief = ConfirmBriefHandler(store=self.store)
        self.end = EndSessionHandler(store=self.store, configurations=CONFIGS)
        self.reserve = ReserveInterviewHandler(store=self.store, configurations=CONFIGS)
        self.review = ReviewReadbackHandler(
            store=self.store,
            targets={
                "field": self.confirm_field,
                "brief": self.confirm_brief,
                "slot": self.reserve,
            },
        )

    async def open(self) -> "World":
        await self.store.sessions.create(self.state, access_hash="")
        return self

    async def said(self, turn: str, text: str) -> None:
        """The candidate's message, as the runtime records it before any tool runs."""
        record = TurnRecord(
            turn_id=TurnId(turn),
            session_id=SID,
            input_id=InputId(f"in-{uuid.uuid4().hex}"),
            role="user",
            channel="text",
            language="es",
            text=text,
            started_at=NOW,
        )
        async with self.store.transaction() as tx:
            await self.store.turns.append(tx, record)

    async def present(self, context: ToolContext, arguments: BaseModel) -> ToolOutcome:
        """``present_confirmation``; words asking for the interview were said first (D58)."""
        if getattr(arguments, "evidence_text", None):
            await self.said(context.turn_id, arguments.evidence_text)  # type: ignore[attr-defined]
        return await self.present_handler(context, arguments)

    async def update(self, context: ToolContext, arguments: BaseModel) -> ToolOutcome:
        """``update_candidate`` after the candidate said its evidence in that turn (D46)."""
        await self.said(context.turn_id, getattr(arguments, "evidence_text", ""))
        return await self.update_handler(context, arguments)

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


SLOT = "chamberi_barista_v1-2026-10-21-1030"


class Interview(World):
    """A world with the calendar seeded and the brief confirmed at revision 1."""

    def __init__(self) -> None:
        super().__init__(full_record(), MemoryStore(clock=lambda: NOW))
        self.slots_handler = ListInterviewSlotsHandler(store=self.store, configurations=CONFIGS)

    async def slots(self, context: ToolContext, arguments: BaseModel) -> ToolOutcome:
        """``list_interview_slots`` after the candidate said its evidence (D58)."""
        await self.said(context.turn_id, getattr(arguments, "evidence_text", ""))
        return await self.slots_handler(context, arguments)

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
