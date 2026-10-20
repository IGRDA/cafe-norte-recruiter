"""The runtime implementation behind the ``ConversationRuntime`` port."""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from cafe_norte.conversation.contracts import (
    AssistantText,
    RuntimeEvent,
    SignalAnalyzer,
    ToolContext,
    ToolFinished,
    ToolStarted,
    TurnFailed,
    TurnFinished,
    TurnInput,
    TurnStarted,
)
from cafe_norte.conversation.prompt import HISTORY_TURNS, build_messages, split_sentences
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.domain.contracts import (
    ConfigId,
    SessionId,
    SessionState,
    StoreConfiguration,
    TurnId,
)
from cafe_norte.errors import MESSAGES, ErrorCode, Language, ServiceError
from cafe_norte.knowledge.contracts import Retriever
from cafe_norte.model.contracts import (
    Model,
    ModelFinished,
    ModelMessage,
    ModelText,
    ModelUsage,
    ToolCall,
)
from cafe_norte.observability.contracts import Stage, StageTiming, UsageRecord
from cafe_norte.persistence.contracts import EventRecord, Store, TurnRecord


class Limits:
    """Per-turn and per-session bounds, all configurable from the environment."""

    __slots__ = ("llm_first_output_seconds", "max_tool_rounds", "session_seconds", "tool_seconds")

    def __init__(
        self,
        *,
        max_tool_rounds: int = 4,
        llm_first_output_seconds: float = 6.0,
        tool_seconds: float = 10.0,
        session_seconds: float = 480.0,
    ) -> None:
        self.max_tool_rounds = max_tool_rounds
        self.llm_first_output_seconds = llm_first_output_seconds
        self.tool_seconds = tool_seconds
        self.session_seconds = session_seconds


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Runtime:
    """One turn at a time per session. Every event is journaled to ``store.events`` before it is
    yielded, so the channel's stream and a later replay are the same data.

    Tracer-bullet scope: prompt assembly, streamed sentences, bounded tool rounds, duplicate
    input ids. Cancellation, repair counting, signals and leases arrive in later stages."""

    def __init__(
        self,
        *,
        model: Model,
        tools: ToolRegistry,
        retriever: Retriever,
        store: Store,
        configurations: dict[ConfigId, StoreConfiguration],
        signals: SignalAnalyzer | None,
        limits: Limits,
        owner: str,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._model = model
        self._tools = tools
        self._retriever = retriever
        self._store = store
        self._configurations = configurations
        self._signals = signals
        self._limits = limits
        self._owner = owner
        self._clock = clock
        self._locks: dict[SessionId, asyncio.Lock] = {}
        self._seq: dict[SessionId, int] = {}

    async def run_turn(self, turn: TurnInput) -> AsyncIterator[RuntimeEvent]:
        lock = self._locks.setdefault(turn.session_id, asyncio.Lock())
        async with lock:
            async for event in self._turn(turn):
                yield event

    async def delivered(self, turn_id: TurnId, *, text: str, complete: bool) -> None:
        raise NotImplementedError  # voice stage

    async def end(
        self, session_id: SessionId, reason: Literal["stop", "limit", "shutdown"]
    ) -> None:
        raise NotImplementedError  # lifecycle stage

    # ---- one turn ------------------------------------------------------------------------------

    async def _turn(self, turn: TurnInput) -> AsyncIterator[RuntimeEvent]:
        turn_id = TurnId(uuid.uuid4().hex)
        state = await self._store.sessions.get(turn.session_id)
        if state is None:
            yield await self._journal(turn.session_id, turn_id, self._failed(turn_id, "not_found"))
            return
        language = state.language
        try:
            await self._persist_user_turn(turn, turn_id, state)
        except ServiceError as error:
            yield await self._journal(
                turn.session_id, turn_id, self._failed(turn_id, error.code, language)
            )
            return

        yield await self._journal(
            turn.session_id, turn_id, TurnStarted(turn_id=turn_id, language=language)
        )
        history = await self._store.turns.recent(turn.session_id, HISTORY_TURNS + 1)
        messages = list(
            build_messages(self._configurations[state.config_id], state, history[:-1], turn.text)
        )
        usage: list[UsageRecord] = []
        timings: list[StageTiming] = []
        spoken: list[str] = []
        started = time.monotonic()
        try:
            for round_index in range(self._limits.max_tool_rounds + 1):
                text, calls = "", []
                buffer = ""
                first_output: float | None = None
                async for event in self._stream_model(tuple(messages), state):
                    if first_output is None:
                        first_output = time.monotonic()
                        timings.append(self._timing(turn, turn_id, "llm_first_output", started))
                    if isinstance(event, ModelText):
                        buffer += event.text
                        sentences, buffer = split_sentences(buffer)
                        for sentence in sentences:
                            spoken.append(sentence)
                            yield await self._journal(turn.session_id, turn_id, _say(sentence))
                    elif isinstance(event, ToolCall):
                        calls.append(event)
                    elif isinstance(event, ModelUsage):
                        usage.extend(_usage(turn, turn_id, event))
                    elif isinstance(event, ModelFinished):
                        pass
                if buffer.strip():
                    spoken.append(buffer.strip())
                    yield await self._journal(turn.session_id, turn_id, _say(buffer.strip()))
                    text += buffer
                if not calls:
                    break
                if round_index == self._limits.max_tool_rounds:
                    raise ServiceError("tool rounds exhausted", code="limit_exceeded")
                messages.append(
                    ModelMessage(role="assistant", content=text, tool_calls=tuple(calls))
                )
                for call in calls:
                    yield await self._journal(turn.session_id, turn_id, ToolStarted(name=call.name))
                    tool_started = time.monotonic()
                    context = ToolContext(
                        session_id=turn.session_id,
                        turn_id=turn_id,
                        now=self._clock(),
                        language=language,
                        lease_generation=0,
                    )
                    try:
                        async with asyncio.timeout(self._limits.tool_seconds):
                            outcome = await self._tools.dispatch(call, context)
                    except TimeoutError as error:
                        raise ServiceError(f"tool {call.name} timed out", code="timeout") from error
                    timings.append(
                        self._timing(turn, turn_id, "tool", tool_started, tool_name=call.name)
                    )
                    for extra in outcome.events:
                        yield await self._journal(turn.session_id, turn_id, extra)
                    yield await self._journal(
                        turn.session_id,
                        turn_id,
                        ToolFinished(name=call.name, ok=outcome.ok, summary=outcome.summary),
                    )
                    messages.append(
                        ModelMessage(
                            role="tool", content=outcome.model_text, tool_call_id=call.call_id
                        )
                    )
        except ServiceError as error:
            yield await self._journal(
                turn.session_id, turn_id, self._failed(turn_id, error.code, language)
            )
            return

        timings.append(self._timing(turn, turn_id, "llm_total", started))
        await self._persist_assistant_turn(turn, turn_id, state, " ".join(spoken), usage, timings)
        yield await self._journal(
            turn.session_id,
            turn_id,
            TurnFinished(
                turn_id=turn_id, interrupted=False, usage=tuple(usage), timings=tuple(timings)
            ),
        )

    async def _stream_model(
        self, messages: tuple[ModelMessage, ...], state: SessionState
    ) -> AsyncIterator[ModelText | ToolCall | ModelUsage | ModelFinished]:
        """The model stream with the first-output bound applied around the first event."""
        remaining = max(self._limits.session_seconds - state.active_seconds, 1.0)
        deadline = self._clock() + timedelta(seconds=remaining)
        stream = self._model.stream(messages, self._tools.schemas(), deadline=deadline)
        try:
            async with asyncio.timeout(self._limits.llm_first_output_seconds):
                first = await anext(stream, None)
        except TimeoutError as error:
            raise ServiceError("no model output in time", code="timeout") from error
        if first is None:
            raise ServiceError("empty model stream", code="invalid_response")
        yield first
        async for event in stream:
            yield event

    # ---- persistence -------------------------------------------------------------------------

    async def _persist_user_turn(
        self, turn: TurnInput, turn_id: TurnId, state: SessionState
    ) -> None:
        async with self._store.transaction() as tx:
            await self._store.turns.append(
                tx,
                TurnRecord(
                    turn_id=turn_id,
                    session_id=turn.session_id,
                    input_id=turn.input_id,
                    role="user",
                    channel=turn.channel,
                    language=state.language,
                    text=turn.text,
                    started_at=turn.received_at,
                    finished_at=turn.received_at,
                ),
            )
            await tx.commit()

    async def _persist_assistant_turn(
        self,
        turn: TurnInput,
        turn_id: TurnId,
        state: SessionState,
        text: str,
        usage: list[UsageRecord],
        timings: list[StageTiming],
    ) -> None:
        async with self._store.transaction() as tx:
            await self._store.turns.append(
                tx,
                TurnRecord(
                    turn_id=turn_id,
                    session_id=turn.session_id,
                    input_id=turn.input_id,
                    role="assistant",
                    channel=turn.channel,
                    language=state.language,
                    text=text,
                    started_at=turn.received_at,
                    finished_at=self._clock(),
                ),
            )
            for record in usage:
                await self._store.events.record_usage(tx, record)
            for timing in timings:
                await self._store.events.record_timing(tx, timing)
            await tx.commit()

    async def _journal(
        self, session_id: SessionId, turn_id: TurnId, event: RuntimeEvent
    ) -> RuntimeEvent:
        """Persist the event with the next sequence number, then hand it back to be yielded."""
        seq = self._seq.get(session_id, 0) + 1
        self._seq[session_id] = seq
        async with self._store.transaction() as tx:
            await self._store.events.append(
                tx,
                EventRecord(
                    session_id=session_id,
                    turn_id=turn_id,
                    seq=seq,
                    kind=event.type,
                    payload_json=event.model_dump_json(),
                    at=self._clock(),
                ),
            )
            await tx.commit()
        return event

    # ---- small builders ------------------------------------------------------------------------

    @staticmethod
    def _failed(turn_id: TurnId, code: ErrorCode, language: Language = "es") -> TurnFailed:
        return TurnFailed(turn_id=turn_id, code=code, message=MESSAGES[language][code])

    @staticmethod
    def _timing(
        turn: TurnInput, turn_id: TurnId, stage: Stage, since: float, *, tool_name: str = ""
    ) -> StageTiming:
        return StageTiming(
            session_id=turn.session_id,
            turn_id=turn_id,
            stage=stage,
            milliseconds=int((time.monotonic() - since) * 1000),
            source="server",
            tool_name=tool_name,
        )


def _say(sentence: str) -> AssistantText:
    return AssistantText(text=sentence, spoken_form=sentence)


def _usage(turn: TurnInput, turn_id: TurnId, event: ModelUsage) -> tuple[UsageRecord, UsageRecord]:
    return (
        UsageRecord(
            session_id=turn.session_id,
            turn_id=turn_id,
            kind="llm_tokens",
            quantity=event.input_tokens,
            unit_detail="input",
            estimated=False,
        ),
        UsageRecord(
            session_id=turn.session_id,
            turn_id=turn_id,
            kind="llm_tokens",
            quantity=event.output_tokens,
            unit_detail="output",
            estimated=False,
        ),
    )
