"""The runtime implementation behind the ``ConversationRuntime`` port."""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from cafe_norte.conversation import prompts
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
from cafe_norte.conversation.prompt import (
    HISTORY_TURNS,
    build_messages,
    clean_sentence,
    split_sentences,
)
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.domain.contracts import (
    ConfigId,
    InputId,
    SessionId,
    SessionState,
    StoreConfiguration,
    TurnId,
)
from cafe_norte.domain.lifecycle import LifecycleEvent, is_terminal, transition
from cafe_norte.domain.result import Err
from cafe_norte.errors import MESSAGES, ErrorCode, ServiceError
from cafe_norte.knowledge.contracts import Retriever
from cafe_norte.model.contracts import (
    Model,
    ModelEvent,
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

    __slots__ = (
        "llm_first_output_seconds",
        "max_answer_characters",
        "max_tool_rounds",
        "session_seconds",
        "tool_seconds",
    )

    def __init__(
        self,
        *,
        max_tool_rounds: int = 4,
        llm_first_output_seconds: float = 6.0,
        tool_seconds: float = 10.0,
        session_seconds: float = 480.0,
        max_answer_characters: int = 600,
    ) -> None:
        self.max_tool_rounds = max_tool_rounds
        self.max_answer_characters = max_answer_characters
        self.llm_first_output_seconds = llm_first_output_seconds
        self.tool_seconds = tool_seconds
        self.session_seconds = session_seconds


log = logging.getLogger(__name__)


_END_EVENTS: dict[str, LifecycleEvent] = {"stop": "stop", "limit": "abandon", "shutdown": "pause"}


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
    asked: bool = False  # a question has been spoken; the turn says nothing more

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
        self._turn_sessions: dict[TurnId, SessionId] = {}  # for delivery acknowledgements

    async def run_turn(self, turn: TurnInput) -> AsyncIterator[RuntimeEvent]:
        lock = self._locks.setdefault(turn.session_id, asyncio.Lock())
        async with lock:
            state = await self._store.sessions.get(turn.session_id)
            if state is None:
                yield await self._journal(turn.session_id, TurnId(""), _NOT_FOUND)
                return
            run = _Turn(input=turn, state=state)
            self._turn_sessions[run.turn_id] = turn.session_id
            if is_terminal(state):
                yield await self._emit(run, run.failed("session_ended"))
                return
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

    async def open_session(self, session_id: SessionId) -> AsyncIterator[RuntimeEvent]:
        """The spec's opening sentence, word for word, before any candidate input."""
        greeting = prompts.load("opening").strip()
        opening = TurnInput(
            session_id=session_id,
            input_id=InputId("opening"),
            text="",
            channel="text",
            received_at=self._clock(),
        )
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            state = await self._store.sessions.get(session_id)
            if state is None:
                yield await self._journal(session_id, TurnId(""), _NOT_FOUND)
                return
            run = _Turn(input=opening, state=state)
            try:
                async with self._store.transaction() as tx:
                    await self._store.turns.append(
                        tx, run.record("assistant", greeting, self._clock())
                    )
            except ServiceError as error:  # a second opening for the same session
                yield await self._emit(run, run.failed(error.code))
                return
            yield await self._emit(
                run, TurnStarted(turn_id=run.turn_id, language=state.language, text="")
            )
            yield await self._emit(run, _say(greeting))
            yield await self._emit(
                run, TurnFinished(turn_id=run.turn_id, interrupted=False, usage=(), timings=())
            )

    async def delivered(self, turn_id: TurnId, *, text: str, complete: bool) -> None:
        """Playback acknowledgement from the voice channel: what was actually heard. Updates
        the assistant turn record and, when that turn presented the pending read-back, whether
        it counts as delivered (its last sentence was heard)."""
        session_id = self._turn_sessions.get(turn_id)
        if session_id is None:
            return
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            state = await self._store.sessions.get(session_id)
            if state is None:
                return
            async with self._store.transaction() as tx:
                await self._store.turns.mark_delivered(
                    tx, session_id, turn_id, delivered_text=text, interrupted=not complete
                )
                pending = state.pending_confirmation
                if pending is not None and pending.presented_turn_id == turn_id:
                    # Heard when playback reached the read-back's last sentence.
                    last_sentence = _sentences(pending.presentation_text)[-1]
                    was_heard = complete or text.endswith(last_sentence)
                    await self._store.sessions.save(
                        tx,
                        state.model_copy(
                            update={
                                "pending_confirmation": pending.model_copy(
                                    update={"fully_delivered": was_heard}
                                )
                            }
                        ),
                        expected_revision=state.candidate.revision,
                    )

    async def end(
        self, session_id: SessionId, reason: Literal["stop", "limit", "shutdown"]
    ) -> None:
        """Close a session from outside a turn (silence, time cap, shutdown). Terminal
        sessions are left alone."""
        event = _END_EVENTS[reason]
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            state = await self._store.sessions.get(session_id)
            if state is None or is_terminal(state):
                return
            result = transition(state, event)
            if isinstance(result, Err):
                return
            lifecycle, outcome = result.value
            async with self._store.transaction() as tx:
                await self._store.sessions.save(
                    tx,
                    state.model_copy(update={"lifecycle": lifecycle, "outcome": outcome}),
                    expected_revision=state.candidate.revision,
                )

    # ---- the turn, step by step ------------------------------------------------------------------

    async def _turn(self, run: _Turn) -> AsyncIterator[RuntimeEvent]:
        async with self._store.transaction() as tx:  # duplicate input_id raises conflict here
            await self._store.turns.append(
                tx, run.record("user", run.input.text, run.input.received_at)
            )
        yield await self._emit(
            run,
            TurnStarted(turn_id=run.turn_id, language=run.state.language, text=run.input.text),
        )

        history = await self._store.turns.recent(run.session_id, HISTORY_TURNS + 1)
        configuration = self._configurations[run.state.config_id]
        today = self._clock().astimezone(ZoneInfo(configuration.timezone)).date()
        run.messages = list(
            build_messages(configuration, run.state, history[:-1], run.input.text, today)
        )

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
        stream = self._stream_model(run)
        try:
            async for event in self._stream_model_events(stream):
                if first:
                    first = False
                    run.time("llm_first_output", run.started)
                if isinstance(event, ModelText):
                    buffer += event.text
                    sentences, buffer = split_sentences(buffer)
                    for sentence in sentences:
                        if self._say_once(run, said, sentence):
                            yield await self._emit(run, _say(sentence))
                    if sum(map(len, said)) + len(buffer) > self._limits.max_answer_characters:
                        # A runaway generation: stop reading, keep what was said, drop the rest.
                        log.warning(
                            "answer cut at %d characters", self._limits.max_answer_characters
                        )
                        buffer = ""
                        break
                elif isinstance(event, ToolCall):
                    run.calls.append(event)
                elif isinstance(event, ModelUsage):
                    run.count(event)
        finally:
            await stream.aclose()
        tail = clean_sentence(buffer)
        if tail and self._say_once(run, said, tail):
            yield await self._emit(run, _say(tail))
        run.spoken.extend(said)
        if run.calls:
            run.messages.append(
                ModelMessage(role="assistant", content=" ".join(said), tool_calls=tuple(run.calls))
            )

    @staticmethod
    def _say_once(run: _Turn, said: list[str], sentence: str) -> bool:
        """One main question per turn, and never the same sentence twice.

        Once a question has been spoken in this turn nothing else is voiced; the model's
        extra questions and rephrasings are read (tool calls and usage still count) but
        dropped. The prompt asks for this; the runtime guarantees it."""
        if run.asked or sentence in said or sentence in run.spoken:
            return False
        said.append(sentence)
        run.asked = "?" in sentence
        return True

    def _stream_model(self, run: _Turn) -> AsyncGenerator[ModelEvent, None]:
        remaining = max(self._limits.session_seconds - run.state.active_seconds, 1.0)
        deadline = self._clock() + timedelta(seconds=remaining)
        return self._model.stream(tuple(run.messages), self._tools.schemas(), deadline=deadline)

    async def _stream_model_events(
        self, stream: AsyncIterator[ModelEvent]
    ) -> AsyncIterator[ModelText | ToolCall | ModelUsage]:
        """The model stream with the first-output bound applied around the first event."""
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
            if outcome.spoken:
                # A read-back is authoritative: said in full even if the model already asked
                # something this turn, then recorded as delivered (text channel).
                run.asked = False
                for sentence in _sentences(outcome.spoken):
                    if self._say_once(run, run.spoken, sentence):
                        yield await self._emit(run, _say(sentence))
                run.asked = True
                if run.input.channel == "text":
                    await self._mark_delivered(run)
            yield await self._emit(
                run, ToolFinished(name=call.name, ok=outcome.ok, summary=outcome.summary)
            )
            run.messages.append(
                ModelMessage(
                    role="tool",
                    content=_tool_message(outcome.model_text, run.spoken),
                    tool_call_id=call.call_id,
                )
            )

    async def _mark_delivered(self, run: _Turn) -> None:
        """The text channel has delivered the read-back once it is journaled; voice will do
        this on playback acknowledgement instead."""
        state = await self._store.sessions.get(run.session_id)
        pending = state.pending_confirmation if state is not None else None
        if state is None or pending is None or pending.fully_delivered:
            return
        delivered = pending.model_copy(update={"fully_delivered": True})
        async with self._store.transaction() as tx:
            await self._store.sessions.save(
                tx,
                state.model_copy(update={"pending_confirmation": delivered}),
                expected_revision=state.candidate.revision,
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


def _tool_message(model_text: str, spoken: list[str]) -> str:
    """The tool result plus what the candidate has already heard this turn, so the model
    continues instead of asking again in other words."""
    if not spoken:
        return model_text
    said = " ".join(spoken)
    return (
        f"{model_text} Already said to the candidate this turn: {said} "
        "Do not repeat or rephrase it; continue, or reply with nothing if it is enough."
    )


def _sentences(text: str) -> list[str]:
    complete, rest = split_sentences(text + " ")
    tail = clean_sentence(rest)
    return complete + ([tail] if tail else [])


def _say(sentence: str) -> AssistantText:
    return AssistantText(text=sentence, spoken_form=sentence)
