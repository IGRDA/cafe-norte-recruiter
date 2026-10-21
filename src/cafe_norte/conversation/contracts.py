"""Runtime boundary: what channels put in, what they get out, and the ports it needs."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.contracts import (
    Booking,
    CandidateRecord,
    Channel,
    Confirmation,
    InputId,
    Lifecycle,
    Outcome,
    SessionId,
    SessionState,
    Signal,
    TurnId,
)
from cafe_norte.errors import ErrorCode, Language
from cafe_norte.observability.contracts import StageTiming, UsageRecord


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TurnInput(Frozen):
    """One finalized user turn. Never an STT interim."""

    session_id: SessionId
    input_id: InputId
    text: str
    channel: Channel
    received_at: datetime
    expected_revision: int | None = None  # UI mutations that must not race a model update


# ---- events a channel consumes --------------------------------------------------------------


class TurnStarted(Frozen):
    """Opens a turn. ``text`` is the finalized user input the turn answers (persisted before
    this is emitted), empty for Ana's opening; the browser renders the user bubble from it so
    the transcript comes from the stream alone, replay included."""

    type: Literal["turn_started"] = "turn_started"
    turn_id: TurnId
    language: Language
    text: str


class AssistantText(Frozen):
    """A sentence or clause ready for display and TTS. ``spoken_form`` has dates, times, money
    and phone numbers normalized for speech; ``text`` keeps canonical values."""

    type: Literal["assistant_text"] = "assistant_text"
    text: str
    spoken_form: str


class ToolStarted(Frozen):
    type: Literal["tool_started"] = "tool_started"
    name: str


class ToolFinished(Frozen):
    type: Literal["tool_finished"] = "tool_finished"
    name: str
    ok: bool
    summary: str  # safe, content-free description for the reviewer panel


class StateUpdated(Frozen):
    """Emitted after the transaction commits. The browser renders this, not the transcript."""

    type: Literal["state_updated"] = "state_updated"
    revision: int
    candidate: CandidateRecord
    pending_confirmation: Confirmation | None
    booking: Booking | None
    lifecycle: Lifecycle
    outcome: Outcome | None

    @classmethod
    def of(cls, state: SessionState) -> "StateUpdated":
        return cls(
            revision=state.candidate.revision,
            candidate=state.candidate,
            pending_confirmation=state.pending_confirmation,
            booking=state.booking,
            lifecycle=state.lifecycle,
            outcome=state.outcome,
        )


class SourcesShown(Frozen):
    """What the candidate asked and which chunks were shown for it, title › section."""

    type: Literal["sources_shown"] = "sources_shown"
    question: str
    chunk_ids: tuple[str, ...]
    titles: tuple[str, ...]
    sections: tuple[str, ...]
    excerpts: tuple[str, ...]


class SignalRecorded(Frozen):
    """The asynchronous classifier's verdict on one user turn, journaled after that turn
    ended. Advisory: the reviewer panel and the export show it; it never scores anyone."""

    type: Literal["signal_recorded"] = "signal_recorded"
    signal: Signal


class TurnFinished(Frozen):
    type: Literal["turn_finished"] = "turn_finished"
    turn_id: TurnId
    interrupted: bool
    usage: tuple[UsageRecord, ...]
    timings: tuple[StageTiming, ...]


class TurnFailed(Frozen):
    """Terminal for the turn; the session may continue. ``message`` is fixed public text."""

    type: Literal["turn_failed"] = "turn_failed"
    turn_id: TurnId
    code: ErrorCode
    message: str


RuntimeEvent = (
    TurnStarted
    | AssistantText
    | ToolStarted
    | ToolFinished
    | StateUpdated
    | SourcesShown
    | SignalRecorded
    | TurnFinished
    | TurnFailed
)


# ---- ports ---------------------------------------------------------------------------------------


class ConversationRuntime(Protocol):
    """Owns history, prompt assembly, tool execution and cancellation for a session.

    ``run_turn`` is an async generator; closing it cancels in-flight model and tool work and
    marks the turn interrupted. Mutations are serialized per session and require the current
    ownership lease generation. A duplicate ``input_id`` yields a single ``TurnFailed`` with
    ``conflict``. Nothing is announced before it is persisted."""

    def run_turn(self, turn: TurnInput) -> AsyncIterator[RuntimeEvent]: ...

    def open_session(self, session_id: SessionId) -> AsyncIterator[RuntimeEvent]:
        """Ana's opening: the fixed disclosure greeting, journaled like any turn, no model."""
        ...

    def resume_session(self, session_id: SessionId) -> AsyncIterator[RuntimeEvent]:
        """A private resume link reopened the session: a paused session becomes active, Ana
        says the fixed resume sentence and repeats a pending read-back; no model, nothing is
        rebooked (D32)."""
        ...

    async def delivered(self, turn_id: TurnId, *, text: str, complete: bool) -> None:
        """Playback acknowledgement from the voice channel: what was actually heard."""
        ...

    def say(self, session_id: SessionId, text: str) -> AsyncIterator[RuntimeEvent]:
        """A fixed sentence the system says outside a candidate turn, journaled."""
        ...

    async def aside(self, turn_id: TurnId, text: str) -> None:
        """A sentence voice said inside a running turn, journaled under it."""
        ...

    async def end(
        self, session_id: SessionId, reason: Literal["stop", "limit", "shutdown"]
    ) -> None: ...


class ToolContext(Frozen):
    """Injected by the server for every tool execution; never read from model arguments."""

    session_id: SessionId
    turn_id: TurnId
    now: datetime
    language: Language
    lease_generation: int | None  # the turn's lease; every save in the turn is fenced on it


class ToolOutcome(Frozen):
    """What goes back to the model and what the channel is told."""

    ok: bool
    model_text: str  # content the model reads next; short, factual, in the session language
    summary: str  # content-free note for the reviewer panel
    events: tuple[StateUpdated | SourcesShown, ...] = ()
    spoken: str = ""  # text the runtime says verbatim (read-backs): shown == spoken == pending


class ToolHandler(Protocol):
    async def __call__(self, context: ToolContext, arguments: BaseModel) -> ToolOutcome: ...


class SignalAnalyzer(Protocol):
    """Asynchronous sentiment/intent classification of finalized text; results are advisory and
    attached to their turn. ``None`` when there is no evidence-backed verdict. Explicit stop and
    human requests have a synchronous path in ``signals.py`` and never wait for this."""

    async def analyze(self, turn_id: TurnId, text: str, language: Language) -> Signal | None: ...
