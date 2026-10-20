"""The runtime implementation behind the ``ConversationRuntime`` port."""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
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
from cafe_norte.errors import MESSAGES, ErrorCode, ServiceError
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


log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class _Turn:
    """Everything one turn accumulates. Mutable on purpose and private to the runtime."""

    input: TurnInput
    state: SessionState
    turn_id: TurnId = field(default_factory=lambda: TurnId(uuid.uuid4().hex))
    started: float = field(default_factory=time.monotonic)
    messages: list[ModelMessage] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)  # asked for in the latest model round
    spoken: list[str] = field(default_factory=list)
    usage: list[UsageRecord] = field(default_factory=list)
    timings: list[StageTiming] = field(default_factory=list)

    @property
    def session_id(self) -> SessionId:
        return self.input.session_id

    def failed(self, code: ErrorCode) -> TurnFailed:
        message = MESSAGES[self.state.language][code]
        return TurnFailed(turn_id=self.turn_id, code=code, message=message)

    def time(self, stage: Stage, since: float, *, tool_name: str = "") -> None:
        self.timings.append(
            StageTiming(
                session_id=self.session_id,
                turn_id=self.turn_id,
                stage=stage,
                milliseconds=int((time.monotonic() - since) * 1000),
                source="server",
                tool_name=tool_name,
            )
        )

    def count(self, usage: ModelUsage) -> None:
        for detail, quantity in (("input", usage.input_tokens), ("output", usage.output_tokens)):
            self.usage.append(
                UsageRecord(
                    session_id=self.session_id,
                    turn_id=self.turn_id,
                    kind="llm_tokens",
                    quantity=quantity,
                    unit_detail=detail,
                    estimated=False,
                )
            )

    def record(
        self, role: Literal["user", "assistant"], text: str, finished_at: datetime
    ) -> TurnRecord:
        return TurnRecord(
            turn_id=self.turn_id,
            session_id=self.session_id,
            input_id=self.input.input_id,
            role=role,
            channel=self.input.channel,
            language=self.state.language,
            text=text,
            started_at=self.input.received_at,
            finished_at=finished_at,
        )


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
            state = await self._store.sessions.get(turn.session_id)
            if state is None:
                yield await self._journal(turn.session_id, TurnId(""), _NOT_FOUND)
                return
            run = _Turn(input=turn, state=state)
            try:
                async for event in self._turn(run):
                    yield event
            except ServiceError as error:
                log.warning(
                    "turn failed session=%s turn=%s code=%s detail=%s",
                    run.session_id,
                    run.turn_id,
                    error.code,
                    error,
                )
                yield await self._emit(run, run.failed(error.code))

    async def delivered(self, turn_id: TurnId, *, text: str, complete: bool) -> None:
        raise NotImplementedError  # voice stage

    async def end(
        self, session_id: SessionId, reason: Literal["stop", "limit", "shutdown"]
    ) -> None:
        raise NotImplementedError  # lifecycle stage

    # ---- the turn, step by step ------------------------------------------------------------------

    async def _turn(self, run: _Turn) -> AsyncIterator[RuntimeEvent]:
        async with self._store.transaction() as tx:  # duplicate input_id raises conflict here
            await self._store.turns.append(
                tx, run.record("user", run.input.text, run.input.received_at)
            )
        yield await self._emit(run, TurnStarted(turn_id=run.turn_id, language=run.state.language))

        history = await self._store.turns.recent(run.session_id, HISTORY_TURNS + 1)
        configuration = self._configurations[run.state.config_id]
        run.messages = list(build_messages(configuration, run.state, history[:-1], run.input.text))

        for round_index in range(self._limits.max_tool_rounds + 1):
            async for event in self._model_round(run):
                yield event
            if not run.calls:
                break
            if round_index == self._limits.max_tool_rounds:
                raise ServiceError("tool rounds exhausted", code="limit_exceeded")
            async for event in self._tool_calls(run):
                yield event

        run.time("llm_total", run.started)
        async with self._store.transaction() as tx:
            await self._store.turns.append(
                tx, run.record("assistant", " ".join(run.spoken), self._clock())
            )
            for usage in run.usage:
                await self._store.events.record_usage(tx, usage)
            for timing in run.timings:
                await self._store.events.record_timing(tx, timing)
        yield await self._emit(
            run,
            TurnFinished(
                turn_id=run.turn_id,
                interrupted=False,
                usage=tuple(run.usage),
                timings=tuple(run.timings),
            ),
        )

    async def _model_round(self, run: _Turn) -> AsyncIterator[RuntimeEvent]:
        """One model call: sentences out as they complete; tool calls collected in ``run.calls``;
        the assistant message appended to ``run.messages`` when tools were requested."""
        run.calls = []
        said: list[str] = []
        buffer = ""
        first = True
        async for event in self._stream_model(run):
            if first:
                first = False
                run.time("llm_first_output", run.started)
            if isinstance(event, ModelText):
                buffer += event.text
                sentences, buffer = split_sentences(buffer)
                for sentence in sentences:
                    said.append(sentence)
                    yield await self._emit(run, _say(sentence))
            elif isinstance(event, ToolCall):
                run.calls.append(event)
            elif isinstance(event, ModelUsage):
                run.count(event)
        if buffer.strip():
            said.append(buffer.strip())
            yield await self._emit(run, _say(buffer.strip()))
        run.spoken.extend(said)
        if run.calls:
            run.messages.append(
                ModelMessage(role="assistant", content=" ".join(said), tool_calls=tuple(run.calls))
            )

    async def _stream_model(self, run: _Turn) -> AsyncIterator[ModelText | ToolCall | ModelUsage]:
        """The model stream with the first-output bound applied around the first event."""
        remaining = max(self._limits.session_seconds - run.state.active_seconds, 1.0)
        deadline = self._clock() + timedelta(seconds=remaining)
        stream = self._model.stream(tuple(run.messages), self._tools.schemas(), deadline=deadline)
        try:
            async with asyncio.timeout(self._limits.llm_first_output_seconds):
                first = await anext(stream, None)
        except TimeoutError as error:
            raise ServiceError("no model output in time", code="timeout") from error
        if first is None:
            raise ServiceError("empty model stream", code="invalid_response")
        if not isinstance(first, ModelFinished):
            yield first
        async for event in stream:
            if not isinstance(event, ModelFinished):
                yield event

    async def _tool_calls(self, run: _Turn) -> AsyncIterator[RuntimeEvent]:
        """Dispatch every call of the round in order; each result becomes a tool message."""
        for call in run.calls:
            yield await self._emit(run, ToolStarted(name=call.name))
            started = time.monotonic()
            context = ToolContext(
                session_id=run.session_id,
                turn_id=run.turn_id,
                now=self._clock(),
                language=run.state.language,
                lease_generation=0,
            )
            try:
                async with asyncio.timeout(self._limits.tool_seconds):
                    outcome = await self._tools.dispatch(call, context)
            except TimeoutError as error:
                raise ServiceError(f"tool {call.name} timed out", code="timeout") from error
            run.time("tool", started, tool_name=call.name)
            for extra in outcome.events:
                yield await self._emit(run, extra)
            yield await self._emit(
                run, ToolFinished(name=call.name, ok=outcome.ok, summary=outcome.summary)
            )
            run.messages.append(
                ModelMessage(role="tool", content=outcome.model_text, tool_call_id=call.call_id)
            )

    # ---- the journal -----------------------------------------------------------------------------

    async def _emit(self, run: _Turn, event: RuntimeEvent) -> RuntimeEvent:
        return await self._journal(run.session_id, run.turn_id, event)

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
                    turn_id=turn_id or None,
                    seq=seq,
                    kind=event.type,
                    payload_json=event.model_dump_json(),
                    at=self._clock(),
                ),
            )
        return event


_NOT_FOUND = TurnFailed(turn_id=TurnId(""), code="not_found", message=MESSAGES["es"]["not_found"])


def _say(sentence: str) -> AssistantText:
    return AssistantText(text=sentence, spoken_form=sentence)
