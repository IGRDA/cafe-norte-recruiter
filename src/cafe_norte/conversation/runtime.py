"""The runtime implementation behind the ``ConversationRuntime`` port."""

import asyncio
import json
import logging
import math
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeGuard
from zoneinfo import ZoneInfo

from cafe_norte.conversation import prompts
from cafe_norte.conversation.contracts import (
    AssistantText,
    RuntimeEvent,
    SignalAnalysis,
    SignalAnalyzer,
    SignalRecorded,
    StateUpdated,
    ToolContext,
    ToolFinished,
    ToolOutcome,
    ToolStarted,
    TurnFailed,
    TurnFinished,
    TurnInput,
    TurnStarted,
)
from cafe_norte.conversation.prompt import (
    HISTORY_TURNS,
    PromptHints,
    build_messages,
    clean_sentence,
    conversation_tail,
    sentences,
    split_sentences,
    tool_message,
)
from cafe_norte.conversation.readback import answer_call, current_saying
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.signals import (
    answer_to_readback,
    explicit_controls,
    fresh_sentiment,
    fresh_switch,
    is_farewell,
    requested_language,
)
from cafe_norte.conversation.slot_answer import Shortlist, slot_answer
from cafe_norte.domain.contracts import (
    ConfigId,
    InputId,
    SessionId,
    SessionState,
    Signal,
    SlotId,
    StoreConfiguration,
    TurnId,
)
from cafe_norte.domain.lifecycle import TERMINAL, LifecycleEvent, is_terminal, transition
from cafe_norte.domain.result import Err
from cafe_norte.domain.review import add_followup
from cafe_norte.domain.session_time import active_increment
from cafe_norte.errors import MESSAGES, ErrorCode, Language, ServiceError
from cafe_norte.model.contracts import (
    Model,
    ModelEvent,
    ModelFinished,
    ModelMessage,
    ModelText,
    ModelUsage,
    ToolCall,
    ToolSchema,
)
from cafe_norte.observability.contracts import (
    EventName,
    ObservationKind,
    Severity,
    Span,
    SpanValue,
    Stage,
    StageTiming,
    StructuredEvent,
    Telemetry,
    UsageRecord,
    token_usage,
)
from cafe_norte.observability.redaction import redact
from cafe_norte.persistence.contracts import EventRecord, Lease, Store, TurnRecord


class Limits:
    """Per-turn and per-session bounds, all configurable from the environment."""

    __slots__ = (
        "lease_seconds",
        "llm_first_output_seconds",
        "max_answer_characters",
        "max_repairs",
        "max_tool_rounds",
        "session_seconds",
        "tool_seconds",
    )

    def __init__(
        self,
        *,
        max_tool_rounds: int = 4,
        max_repairs: int = 1,
        llm_first_output_seconds: float = 6.0,
        tool_seconds: float = 10.0,
        session_seconds: float = 480.0,
        max_answer_characters: int = 600,
        lease_seconds: int = 60,
    ) -> None:
        self.lease_seconds = lease_seconds
        self.max_tool_rounds = max_tool_rounds
        self.max_repairs = max_repairs
        self.max_answer_characters = max_answer_characters
        self.llm_first_output_seconds = llm_first_output_seconds
        self.tool_seconds = tool_seconds
        self.session_seconds = session_seconds


log = logging.getLogger(__name__)


_END_EVENTS: dict[str, LifecycleEvent] = {"stop": "stop", "limit": "abandon", "shutdown": "pause"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


# A generation with no usage report is estimated at this many characters per token (D44).
CHARACTERS_PER_TOKEN = 4


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
    repairs: int = 0  # malformed tool calls this turn; the budget is ``Limits.max_repairs``
    round_idle: bool = False  # every call of the latest model round changed nothing (D44)
    withheld: set[str] = field(default_factory=set)  # tools not offered again this turn (D44)
    previous_end: datetime | None = None  # when Ana last finished, for the gap before this turn
    ana_before: str = ""  # what Ana said last before this turn, for the signal analyzer (D52)
    recorded: bool = False  # the user turn is stored, so an interruption has a turn to close
    lease: Lease | None = None  # held for the turn; every write is fenced on its generation
    outcome: ToolOutcome = field(
        default_factory=lambda: ToolOutcome(ok=True, model_text="", summary="")
    )
    answered: str | None = None  # what the runtime's own read-back answer told the model
    slot_choice: str | None = None  # what the runtime did with the candidate's slot choice
    trace: Span = field(init=False)  # the root span; set by run_turn before anything else
    tools_called: int = 0
    rounds: int = 0

    @property
    def session_id(self) -> SessionId:
        return self.input.session_id

    @property
    def generation(self) -> int | None:
        return None if self.lease is None else self.lease.generation

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

    def count(self, usage: ModelUsage, model_id: str) -> None:
        self.usage.extend(
            token_usage(
                self.session_id,
                self.turn_id,
                model_id,
                usage.input_tokens,
                usage.output_tokens,
                estimated=False,
            )
        )

    def record(
        self,
        role: Literal["user", "assistant"],
        text: str,
        finished_at: datetime,
        *,
        interrupted: bool = False,
    ) -> TurnRecord:
        return TurnRecord(
            turn_id=self.turn_id,
            session_id=self.session_id,
            input_id=self.input.input_id,
            role=role,
            channel=self.input.channel,
            language=self.state.language,
            text=text,
            interrupted=interrupted,
            started_at=self.input.received_at,
            finished_at=finished_at,
        )


class Runtime:
    """One turn at a time per session. Every event is journaled to ``store.events`` before it is
    yielded, so the channel's stream and a later replay are the same data.

    Explicit stop and human requests are matched before the model runs; the signal analyzer,
    when configured, classifies each user turn after it finished and its verdict shapes only
    the next turn. A second malformed tool call in one turn ends it with ``invalid_response``;
    closing or cancelling ``run_turn`` mid-stream stores what was said as an interrupted turn."""

    def __init__(
        self,
        *,
        model: Model,
        tools: ToolRegistry,
        store: Store,
        configurations: dict[ConfigId, StoreConfiguration],
        signals: SignalAnalyzer | None,
        limits: Limits,
        telemetry: Telemetry,
        owner: str,
        clock: Callable[[], datetime] = _utcnow,
        on_closed: Callable[[SessionId], Awaitable[None]] | None = None,
    ) -> None:
        self._on_closed = on_closed
        self._model = model
        self._tools = tools
        self._store = store
        self._configurations = configurations
        self._signals = signals
        self._limits = limits
        self._telemetry = telemetry
        self._owner = owner
        self._clock = clock
        self._locks: dict[SessionId, asyncio.Lock] = {}
        self._turn_sessions: dict[TurnId, SessionId] = {}  # for delivery acknowledgements
        self._last_user_turn: dict[SessionId, TurnId] = {}
        self._latest_signal: dict[SessionId, Signal] = {}
        self._analyses: set[asyncio.Task[None]] = set()

    async def run_turn(self, turn: TurnInput) -> AsyncGenerator[RuntimeEvent, None]:
        lock = self._locks.setdefault(turn.session_id, asyncio.Lock())
        async with lock:
            state = await self._store.sessions.get(turn.session_id)
            if state is None:
                yield _NOT_FOUND  # nothing to journal against, and nobody can stream it
                return
            if turn.ui_answer is not None and not turn.text:
                label = prompts.table("ui", state.language)[turn.ui_answer.answer]
                turn = turn.model_copy(update={"text": label})
            run = _Turn(input=turn, state=state)
            self._turn_sessions[run.turn_id] = turn.session_id
            run.trace = self._telemetry.turn(
                session_id=run.session_id,
                turn_id=run.turn_id,
                configuration=self._configurations[state.config_id],
                channel=turn.channel,
                language=state.language,
            )
            with run.trace:
                if is_terminal(state):
                    self._close_trace(run, failure="session_ended")
                    yield await self._emit(run, run.failed("session_ended"))
                    return
                if not await self._claim(run):
                    self._close_trace(run, failure="conflict")
                    yield await self._emit(run, run.failed("conflict"))
                    return
                try:
                    async with aclosing(self._turn(run)) as events:  # closing us closes the model
                        async for event in events:
                            yield event
                    self._close_trace(run)
                except (asyncio.CancelledError, GeneratorExit):
                    self._close_trace(run, failure="interrupted")
                    await self._interrupted(run)
                    raise
                except ServiceError as error:
                    self._event(run, "turn_failed", "WARNING", code=error.code, detail=str(error))
                    self._close_trace(run, failure=error.code)
                    run.lease = None  # the fence may be what failed; journal the failure unfenced
                    yield await self._emit(run, run.failed(error.code))
                finally:
                    await self._release(run)

    def _event(self, run: _Turn, name: EventName, severity: Severity, **payload: SpanValue) -> None:
        self._telemetry.emit(
            StructuredEvent(
                at=self._clock(),
                severity=severity,
                session_id=run.session_id,
                turn_id=run.turn_id,
                event=name,
                payload=dict(payload),
            )
        )

    @staticmethod
    def _close_trace(run: _Turn, *, failure: str | None = None) -> None:
        """What the root span says about the turn: how it ended and how big it was, never the
        words (they go in as content, which the adapter drops unless the operator asked)."""
        if failure is not None:
            run.trace.fail(failure)
        run.trace.annotate(
            outcome="finished" if failure is None else "failed",
            tools_called=run.tools_called,
            rounds=run.rounds,
            chars_in=len(run.input.text),
            chars_out=len(" ".join(run.spoken)),
        )
        run.trace.set_content(input=run.input.text, output=" ".join(run.spoken))

    async def open_session(self, session_id: SessionId) -> AsyncIterator[RuntimeEvent]:
        """The spec's opening sentence, word for word, before any candidate input."""
        async for event in self._system_turn(session_id, InputId("opening"), _opening):
            yield event

    async def resume_session(self, session_id: SessionId) -> AsyncIterator[RuntimeEvent]:
        """A resume link reopened the session: ``paused`` becomes ``active``, then the fixed
        resume sentence and, when a read-back is still unanswered, its text again."""
        input_id = InputId(f"resume-{uuid.uuid4().hex[:8]}")
        async for event in self._system_turn(session_id, input_id, _resume, reactivate=True):
            yield event

    async def say(self, session_id: SessionId, text: str) -> AsyncIterator[RuntimeEvent]:
        """A fixed sentence the system says outside a candidate turn (the silence prompt, the
        apology after a failed turn), journaled as its own turn so the page and the export
        show everything Ana said (D35)."""
        input_id = InputId(f"system-{uuid.uuid4().hex[:8]}")
        async for event in self._system_turn(session_id, input_id, lambda _: [text]):
            yield event

    async def aside(self, turn_id: TurnId, text: str) -> None:
        """A sentence voice said inside a running turn (the filler while a tool works),
        journaled under that turn. Unknown turns are ignored."""
        session_id = self._turn_sessions.get(turn_id)
        if session_id is not None:
            await self._journal(session_id, turn_id, _say(text))

    async def record_usage(self, session_id: SessionId, usage: Sequence[UsageRecord]) -> None:
        """Usage measured outside a turn, such as a call's speech providers. A session that
        has already ended stores its export again, so the cost in it includes this (D44)."""
        await self._record(usage)
        state = await self._store.sessions.get(session_id)
        if state is not None and is_terminal(state):
            self._close_later(session_id)

    async def _system_turn(
        self,
        session_id: SessionId,
        input_id: InputId,
        lines: Callable[[SessionState], list[str]],
        *,
        reactivate: bool = False,
    ) -> AsyncIterator[RuntimeEvent]:
        """A turn the system speaks by itself, journaled like any other, under the lease."""
        system = TurnInput(
            session_id=session_id,
            input_id=input_id,
            text="",
            channel="text",
            received_at=self._clock(),
        )
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            state = await self._store.sessions.get(session_id)
            if state is None:
                yield _NOT_FOUND
                return
            run = _Turn(input=system, state=state)
            if is_terminal(state):
                yield await self._emit(run, run.failed("session_ended"))
                return
            if not await self._claim(run):
                yield await self._emit(run, run.failed("conflict"))
                return
            try:
                spoken = lines(state)
                async with self._store.transaction() as tx:
                    if reactivate and state.lifecycle == "paused":
                        result = transition(state, "resume")
                        if not isinstance(result, Err):
                            lifecycle, outcome = result.value
                            run.state = state.model_copy(
                                update={"lifecycle": lifecycle, "outcome": outcome}
                            )
                            await self._store.sessions.save(
                                tx,
                                run.state,
                                expected_revision=state.candidate.revision,
                                lease_generation=run.generation,
                            )
                    await self._store.turns.append(
                        tx, run.record("assistant", " ".join(spoken), self._clock())
                    )
                yield await self._emit(
                    run, TurnStarted(turn_id=run.turn_id, language=state.language, text="")
                )
                for sentence in spoken:
                    yield await self._emit(run, _say(sentence))
                yield await self._emit(
                    run,
                    TurnFinished(turn_id=run.turn_id, interrupted=False, usage=(), timings=()),
                )
            except ServiceError as error:  # a second opening for the same session
                run.lease = None
                yield await self._emit(run, run.failed(error.code))
            finally:
                await self._release(run)

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
                    # Heard when playback reached the last sentence of what was said: the
                    # whole read-back, or the part under review (D39).
                    last_sentence = sentences(current_saying(pending, state.language))[-1]
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
            if lifecycle in TERMINAL:
                self._close_later(session_id)

    async def _claim(self, run: _Turn) -> bool:
        """The session lease for this turn (D32). ``False`` when another container holds it."""
        run.lease = await self._store.leases.claim(
            run.session_id, self._owner, ttl_seconds=self._limits.lease_seconds
        )
        return run.lease is not None

    async def _release(self, run: _Turn) -> None:
        if run.lease is not None:
            await self._store.leases.release(run.lease)
            run.lease = None

    async def settle(self) -> None:
        """Wait for every signal analysis in flight; tests and the eval runner call this
        between turns so the asynchronous path is deterministic there."""
        while self._analyses:
            await asyncio.gather(*self._analyses)

    # ---- the turn, step by step ------------------------------------------------------------------

    async def _turn(self, run: _Turn) -> AsyncGenerator[RuntimeEvent, None]:
        # An explicit language request applies to this very turn: saved with the user turn,
        # before the model is called, so the record, the prompt and the reply all agree. With
        # none, a switch the analyzer read in the previous turn applies now, the same way (D52).
        previous = run.state
        controls = explicit_controls(run.input.text)
        language = requested_language(controls, previous.language)
        if not controls & {"switch_es", "switch_en"}:
            suggested = fresh_switch(
                self._latest_signal.get(run.session_id),
                self._last_user_turn.get(run.session_id),
            )
            language = suggested or language
        run.state = previous.model_copy(update={"language": language})
        if previous.lifecycle == "paused":  # the candidate is back: the session is live again
            resumed = transition(run.state, "resume")
            if not isinstance(resumed, Err):
                lifecycle, outcome = resumed.value
                run.state = run.state.model_copy(
                    update={"lifecycle": lifecycle, "outcome": outcome}
                )
        with run.trace.child("write-user-turn"):
            async with self._store.transaction() as tx:  # a duplicate input_id raises conflict
                await self._store.turns.append(
                    tx, run.record("user", run.input.text, run.input.received_at)
                )
                if run.state != previous:
                    await self._store.sessions.save(
                        tx,
                        run.state,
                        expected_revision=previous.candidate.revision,
                        lease_generation=run.generation,
                    )
        run.recorded = True
        yield await self._emit(
            run,
            TurnStarted(turn_id=run.turn_id, language=run.state.language, text=run.input.text),
        )

        hints = PromptHints(
            explicit=controls,
            sentiment=fresh_sentiment(
                self._latest_signal.get(run.session_id),
                self._last_user_turn.get(run.session_id),
            ),
        )
        self._last_user_turn[run.session_id] = run.turn_id
        if "human" in controls:
            async for event in self._human_request(run):
                yield event
        async for event in self._plain_answer(run):
            yield event
        if run.answered is None and "human" not in controls:
            async for event in self._slot_choice(run):
                yield event
        if run.answered is None and run.slot_choice is None and "human" not in controls:
            async for event in self._farewell(run):
                yield event
        if run.answered is not None:
            hints = hints.model_copy(update={"readback_answered": run.answered})
        if run.slot_choice is not None:
            hints = hints.model_copy(update={"slot_choice": run.slot_choice})

        if not is_terminal(run.state):  # a farewell ended it above: nothing for the model
            history = await self._store.turns.recent(run.session_id, HISTORY_TURNS + 1)
            if len(history) > 1:
                run.previous_end = history[-2].finished_at
            run.ana_before = next(
                (t.text for t in reversed(history[:-1]) if t.role == "assistant"), ""
            )
            configuration = self._configurations[run.state.config_id]
            today = self._clock().astimezone(ZoneInfo(configuration.timezone)).date()
            run.messages = list(
                build_messages(configuration, run.state, history[:-1], run.input.text, today, hints)
            )

            with run.trace.child("invoke-agent", "agent", model=self._model.model_id) as agent:
                for round_index in range(self._limits.max_tool_rounds + 1):
                    run.rounds = round_index + 1
                    with agent.child("step", "chain", round=run.rounds) as step:
                        async with aclosing(self._model_round(run, step)) as round_events:
                            async for (
                                event
                            ) in round_events:  # closing it closes the provider stream
                                yield event
                        if not run.calls:
                            break
                        if round_index == self._limits.max_tool_rounds:
                            raise ServiceError("tool rounds exhausted", code="limit_exceeded")
                        async for event in self._tool_calls(run, step):
                            yield event
                        if _nothing_left_to_do(run):
                            step.annotate(idle=True)
                            break

        run.time("llm_total", run.started)
        with run.trace.child("write-assistant-turn"):
            capped = await self._close_turn(run, interrupted=False)
        if capped is not None:  # the session cap: saved above, announced, then said
            state, goodbye = capped
            yield await self._emit(run, StateUpdated.of(state))
            for sentence in goodbye:
                yield await self._emit(run, _say(sentence))
        yield await self._emit(
            run,
            TurnFinished(
                turn_id=run.turn_id,
                interrupted=False,
                usage=tuple(run.usage),
                timings=tuple(run.timings),
            ),
        )
        if self._signals is not None:
            self._analyze_later(self._signals, run)

    async def _close_turn(
        self, run: _Turn, *, interrupted: bool
    ) -> tuple[SessionState, list[str]] | None:
        """One transaction ends the turn: the assistant record, usage and timings, and the
        turn's active seconds on the session. The turn that carries the session past its cap
        also abandons it there and its record holds the goodbye; the state and the goodbye
        are returned for the caller to announce."""
        finished_at = self._clock()
        state = await self._store.sessions.get(run.session_id)
        goodbye: list[str] = []
        ended: SessionState | None = None
        if state is not None:
            seconds = active_increment(run.previous_end, run.input.received_at, finished_at)
            state = state.model_copy(update={"active_seconds": state.active_seconds + seconds})
            if not is_terminal(state) and state.active_seconds >= self._limits.session_seconds:
                result = transition(state, "abandon")
                if not isinstance(result, Err):
                    lifecycle, outcome = result.value
                    state = state.model_copy(update={"lifecycle": lifecycle, "outcome": outcome})
                    ended = state
                    goodbye = sentences(_control_reply("time_cap", state.language))
        spoken = [*run.spoken, *goodbye]
        async with self._store.transaction() as tx:
            await self._store.turns.append(
                tx, run.record("assistant", " ".join(spoken), finished_at, interrupted=interrupted)
            )
            for usage in run.usage:
                await self._store.events.record_usage(tx, usage)
            for timing in run.timings:
                await self._store.events.record_timing(tx, timing)
            if state is not None:
                await self._store.sessions.save(
                    tx,
                    state,
                    expected_revision=state.candidate.revision,
                    lease_generation=run.generation,
                )
        return None if ended is None else (ended, goodbye)

    async def _interrupted(self, run: _Turn) -> None:
        """The channel closed the turn or cancelled it (barge-in, hang-up): what was generated
        so far is stored as an interrupted assistant turn and the journal says so. The closing
        itself is never refused; a failure to write is logged and the cancellation goes on."""
        if not run.recorded:
            return
        try:
            run.time("llm_total", run.started)
            capped = await self._close_turn(run, interrupted=True)
            finished = TurnFinished(
                turn_id=run.turn_id,
                interrupted=True,
                usage=tuple(run.usage),
                timings=tuple(run.timings),
            )
            if capped is not None:  # nobody is listening to a goodbye, but the session is over
                await self._emit(run, StateUpdated.of(capped[0]))
            await self._emit(run, finished)
        except ServiceError as error:
            log.warning(
                "interrupted turn not closed session=%s code=%s", run.session_id, error.code
            )

    async def _human_request(self, run: _Turn) -> AsyncIterator[RuntimeEvent]:
        """An explicit request for a person: the follow-up flag is saved, then the fixed reply
        is said in full. The model still runs (the same sentence may carry a fact) but says
        nothing more: the reply ends with this turn's question."""
        state = add_followup(run.state, run.turn_id, run.input.text)
        async with self._store.transaction() as tx:
            await self._store.sessions.save(tx, state, expected_revision=state.candidate.revision)
        run.state = state
        yield await self._emit(run, StateUpdated.of(state))
        async for event in self._verbatim(run, _control_reply("human", state.language)):
            yield event

    def _analyze_later(self, analyzer: SignalAnalyzer, run: _Turn) -> None:
        """Off the critical path: the turn has finished; the verdict is journaled when it
        arrives and kept for the next turn's prompt."""

        async def analyze() -> None:
            try:
                analysis = await analyzer.analyze(
                    run.turn_id, run.input.text, run.state.language, ana_said=run.ana_before
                )
                if analysis.usage is not None:
                    await self._record(_analysis_usage(run, analysis))
                signal = analysis.signal
                if signal is None:
                    return
                if self._last_user_turn.get(run.session_id) == run.turn_id:
                    self._latest_signal[run.session_id] = signal  # a newer turn's never replaced
                await self._journal(run.session_id, run.turn_id, SignalRecorded(signal=signal))
            except Exception:  # advisory: a failed analysis never reaches the candidate
                log.exception("signal analysis failed session=%s", run.session_id)

        task = asyncio.create_task(analyze())
        self._analyses.add(task)
        task.add_done_callback(self._analyses.discard)

    async def _record(self, usage: Sequence[UsageRecord]) -> None:
        """Usage that arrives outside a turn's own closing transaction."""
        async with self._store.transaction() as tx:
            for record in usage:
                await self._store.events.record_usage(tx, record)

    async def _model_round(self, run: _Turn, step: Span) -> AsyncGenerator[RuntimeEvent, None]:
        """One model call: sentences out as they complete; tool calls collected in ``run.calls``;
        the assistant message appended to ``run.messages`` when tools were requested."""
        run.calls = []
        start = len(run.spoken)  # what this round says is what run.spoken gains from here
        buffer = ""
        first = True
        with step.child("chat", "generation") as chat:
            chat.set_content(input=conversation_tail(run.messages))
            events = self._round_events(run, chat)
            try:
                async for event in events:
                    if first:
                        first = False
                        run.time("llm_first_output", run.started)
                    if isinstance(event, ModelText):
                        buffer += event.text
                        complete, buffer = split_sentences(buffer)
                        for sentence in complete:
                            if self._say_once(run, sentence):
                                yield await self._emit(run, _say(sentence))
                        said = run.spoken[start:]
                        if sum(map(len, said)) + len(buffer) > self._limits.max_answer_characters:
                            # A runaway generation: stop reading, keep what was said, drop the rest.
                            self._event(
                                run,
                                "answer_cut",
                                "WARNING",
                                limit_characters=self._limits.max_answer_characters,
                            )
                            buffer = ""
                            break
                    elif isinstance(event, ToolCall):
                        run.calls.append(event)
                    elif isinstance(event, ModelUsage):
                        run.count(event, self._model.model_id)
                        chat.set_usage(
                            model_id=self._model.model_id,
                            input_tokens=event.input_tokens,
                            output_tokens=event.output_tokens,
                        )
            except ServiceError as error:
                chat.fail(error.code)
                raise
            finally:
                await events.aclose()
            tail = clean_sentence(buffer)
            if tail and self._say_once(run, tail):
                yield await self._emit(run, _say(tail))
            chat.set_content(output=" ".join(run.spoken[start:]))
        if run.calls:
            run.messages.append(
                ModelMessage(
                    role="assistant",
                    content=" ".join(run.spoken[start:]),
                    tool_calls=tuple(run.calls),
                )
            )

    @staticmethod
    def _say_once(run: _Turn, sentence: str) -> bool:
        """One main question per turn, and never the same sentence twice.

        Once a question has been spoken in this turn nothing else is voiced; the model's
        extra questions and rephrasings are read (tool calls and usage still count) but
        dropped. The prompt asks for this; the runtime guarantees it."""
        if run.asked or sentence in run.spoken:
            return False
        run.spoken.append(sentence)
        run.asked = "?" in sentence
        return True

    def _stream_model(self, run: _Turn) -> AsyncGenerator[ModelEvent, None]:
        remaining = max(self._limits.session_seconds - run.state.active_seconds, 1.0)
        deadline = self._clock() + timedelta(seconds=remaining)
        tools = _offered(self._tools.schemas(), run.withheld)
        return self._model.stream(tuple(run.messages), tools, deadline=deadline)

    async def _round_events(
        self, run: _Turn, chat: Span
    ) -> AsyncGenerator[ModelText | ToolCall | ModelUsage, None]:
        """One model round with the first-output bound. A round that says nothing in time is
        abandoned and asked once more (spec §12: one bounded retry for safe generation;
        nothing of it was spoken); a second miss fails the turn with ``timeout``."""
        bound = self._limits.llm_first_output_seconds
        for attempt in (1, 2):
            stream = self._stream_model(run)
            started = time.monotonic()
            try:
                async with asyncio.timeout(bound):
                    first = await anext(stream, None)
            except TimeoutError as error:
                await stream.aclose()
                self._estimate(run, output_characters=0)
                if attempt == 1:
                    chat.annotate(silent_attempts=1)
                    self._event(
                        run, "model_round_silent", "WARNING", attempt=attempt, bound_seconds=bound
                    )
                    continue
                raise ServiceError("no model output in time", code="timeout") from error
            break
        first_output_ms = int((time.monotonic() - started) * 1000)
        chat.first_output()
        chat.annotate(attempt=attempt, first_output_ms=first_output_ms)
        seen = _Attempt()
        try:
            if first is None:
                raise ServiceError("empty model stream", code="invalid_response")
            if seen.note(first):
                yield first
            async for event in stream:
                if seen.note(event):
                    yield event
        finally:
            await stream.aclose()
            if not seen.reported:
                self._estimate(run, output_characters=seen.output_characters)
            self._event(
                run,
                "model_round",
                "INFO",
                attempt=attempt,
                first_output_ms=first_output_ms,
                total_ms=int((time.monotonic() - started) * 1000),
            )

    def _estimate(self, run: _Turn, *, output_characters: int) -> None:
        """A generation that ended with no usage report (cut by a barge-in or the answer
        limit, silent, or failed) still cost tokens: they are estimated from its characters,
        the prompt and tools it was sent and the text it streamed, and marked so (D44)."""
        input_characters = sum(len(m.content) for m in run.messages) + sum(
            len(schema.model_dump_json())
            for schema in _offered(self._tools.schemas(), run.withheld)
        )
        run.usage.extend(
            token_usage(
                run.session_id,
                run.turn_id,
                self._model.model_id,
                math.ceil(input_characters / CHARACTERS_PER_TOKEN),
                math.ceil(output_characters / CHARACTERS_PER_TOKEN),
                estimated=True,
            )
        )

    async def _tool_calls(self, run: _Turn, step: Span) -> AsyncIterator[RuntimeEvent]:
        """Dispatch every call of the round in order; each result becomes a tool message."""
        run.round_idle = True
        for call in run.calls:
            async for event in self._run_tool(run, call, step):
                yield event
            run.round_idle = run.round_idle and run.outcome.idle
            if run.outcome.idle:
                run.withheld.add(call.name)  # the next round has to speak instead
            if run.outcome.malformed:
                run.repairs += 1
                if run.repairs > self._limits.max_repairs:
                    raise ServiceError("malformed tool call after repair", code="invalid_response")
            run.messages.append(
                ModelMessage(
                    role="tool",
                    content=tool_message(run.outcome.model_text, run.spoken),
                    tool_call_id=call.call_id,
                )
            )

    async def _run_tool(
        self, run: _Turn, call: ToolCall, parent: Span
    ) -> AsyncIterator[RuntimeEvent]:
        """One tool call through the registry: started, its events, anything it says, finished.
        The outcome is left on ``run.outcome`` for the caller."""
        yield await self._emit(
            run, ToolStarted(name=call.name, arguments=redact(call.arguments_json))
        )
        started = time.monotonic()
        context = ToolContext(
            session_id=run.session_id,
            turn_id=run.turn_id,
            now=self._clock(),
            language=run.state.language,
            lease_generation=run.generation,
        )
        kind: ObservationKind = "retriever" if call.name == "search_knowledge" else "tool"
        with parent.child(call.name, kind) as span:
            try:
                async with asyncio.timeout(self._limits.tool_seconds):
                    outcome = await self._tools.dispatch(call, context)
            except TimeoutError as error:
                span.fail("timeout")
                raise ServiceError(f"tool {call.name} timed out", code="timeout") from error
            span.annotate(ok=outcome.ok)
            span.set_content(input=call.arguments_json, output=outcome.model_text)
        run.tools_called += 1
        run.time("tool", started, tool_name=call.name)
        for extra in outcome.events:
            yield await self._emit(run, extra)
        if outcome.spoken:
            # A read-back is said in full, then recorded as delivered (text channel).
            async for event in self._verbatim(run, outcome.spoken):
                yield event
            if run.input.channel == "text":
                await self._mark_delivered(run)
        yield await self._emit(
            run, ToolFinished(name=call.name, ok=outcome.ok, summary=outcome.summary)
        )
        run.outcome = outcome

    async def _plain_answer(self, run: _Turn) -> AsyncIterator[RuntimeEvent]:
        """A plain yes, no or carry-on to the pending read-back is resolved here, through the
        same tools and domain rules as the model's call, so a model that forgets
        ``confirm_field`` can no longer leave it pending (D35). Where the read-back stands
        decides the tool (``readback.answer_call``): one heard to the end is answered, one the
        candidate cut goes to the review (D39). Anything else is the model's."""
        ui = run.input.ui_answer
        answer = ui.answer if ui is not None else answer_to_readback(run.input.text)
        pending = run.state.pending_confirmation
        if ui is not None and (pending is None or pending.confirmation_id != ui.confirmation_id):
            return  # an answer to a read-back that is no longer the pending one
        call = answer_call(pending, answer, run.turn_id) if answer is not None else None
        if call is None:
            return
        name, arguments = call
        async for event in self._runtime_call(run, name, arguments):
            yield event
        run.answered = run.outcome.model_text

    async def _slot_choice(self, run: _Turn) -> AsyncIterator[RuntimeEvent]:
        """The candidate's answer to the slot offer, decided by ``slot_answer`` (D41) and run
        here through the tools the model would call; a shortlist is saved and the model asks."""
        answer = slot_answer(
            run.state,
            run.input.text,
            by_button=run.input.ui_answer is not None,
            turn_id=run.turn_id,
            configuration=self._configurations[run.state.config_id],
            now=self._clock(),
        )
        if answer is None:
            return
        if isinstance(answer, Shortlist):
            await self._save_shortlist(run, answer.slot_ids)
            run.slot_choice = answer.note
            return
        name, arguments = answer
        async for event in self._runtime_call(run, name, arguments):
            yield event
        run.slot_choice = run.outcome.model_text

    async def _save_shortlist(self, run: _Turn, shortlist: tuple[SlotId, ...]) -> None:
        """The slots an ambiguous answer left in question; the next answer is held to them."""
        offer = run.state.slot_offer
        assert offer is not None
        state = run.state.model_copy(
            update={"slot_offer": offer.model_copy(update={"shortlist": shortlist})}
        )
        async with self._store.transaction() as tx:
            await self._store.sessions.save(
                tx,
                state,
                expected_revision=state.candidate.revision,
                lease_generation=run.generation,
            )
        run.state = state

    async def _farewell(self, run: _Turn) -> AsyncIterator[RuntimeEvent]:
        """A goodbye once the interview is booked ends the session here, through
        ``end_session`` like the model's call, and the fixed goodbye is said (D46): a model
        that answers every goodbye with one of its own can no longer leave the session open."""
        if run.state.booking is None or not is_farewell(run.input.text):
            return
        async for event in self._runtime_call(run, "end_session", {"reason": "candidate_done"}):
            yield event
        if is_terminal(run.state):
            async for event in self._verbatim(run, _control_reply("goodbye", run.state.language)):
                yield event

    async def _runtime_call(
        self, run: _Turn, name: str, arguments: dict[str, str]
    ) -> AsyncIterator[RuntimeEvent]:
        """A tool the runtime calls for the candidate, through the registry and the domain like
        the model's; ``run.outcome`` and ``run.state`` are fresh afterwards."""
        call = ToolCall(call_id=f"runtime-{name}", name=name, arguments_json=json.dumps(arguments))
        async for event in self._run_tool(run, call, run.trace):
            yield event
        refreshed = await self._store.sessions.get(run.session_id)
        if refreshed is not None:
            run.state = refreshed

    async def _verbatim(self, run: _Turn, text: str) -> AsyncIterator[RuntimeEvent]:
        """Authoritative text (a read-back, a control reply): said in full even if the model
        already asked something this turn; nothing else is voiced after it."""
        run.asked = False
        for sentence in sentences(text):
            if self._say_once(run, sentence):
                yield await self._emit(run, _say(sentence))
        run.asked = True

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
        journaled = await self._journal(run.session_id, run.turn_id, event, run.generation)
        if isinstance(event, StateUpdated) and event.lifecycle in TERMINAL:
            self._close_later(run.session_id)  # a tool ended the session: the export follows
        return journaled

    def _close_later(self, session_id: SessionId) -> None:
        """After the terminal state is committed and announced: the stored export (D34)."""
        if self._on_closed is None:
            return

        async def close() -> None:
            try:
                await self._on_closed(session_id)  # type: ignore[misc]
            except Exception:
                log.exception("close hook failed session=%s", session_id)

        task = asyncio.create_task(close())
        self._analyses.add(task)
        task.add_done_callback(self._analyses.discard)

    async def _journal(
        self,
        session_id: SessionId,
        turn_id: TurnId,
        event: RuntimeEvent,
        lease_generation: int | None = None,
    ) -> RuntimeEvent:
        """Persist the event with the store's next sequence number, then hand it back."""
        async with self._store.transaction() as tx:
            seq = await self._store.sessions.next_seq(
                tx, session_id, lease_generation=lease_generation
            )
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


def _analysis_usage(run: _Turn, analysis: SignalAnalysis) -> tuple[UsageRecord, ...]:
    """The classifier's tokens, under the turn it classified."""
    usage = analysis.usage
    assert usage is not None
    return token_usage(
        run.session_id,
        run.turn_id,
        analysis.model_id,
        usage.input_tokens,
        usage.output_tokens,
        estimated=False,
    )


@dataclass
class _Attempt:
    """What one model attempt streamed: whether the provider reported its usage, and the
    characters of text, for the estimate when it did not (D44)."""

    reported: bool = False
    output_characters: int = 0

    def note(self, event: ModelEvent) -> TypeGuard[ModelText | ToolCall | ModelUsage]:
        """Count the event; ``True`` when it is for the round to read (not the finish)."""
        self.reported = self.reported or isinstance(event, ModelUsage)
        if isinstance(event, ModelText):
            self.output_characters += len(event.text)
        return not isinstance(event, ModelFinished)


def _nothing_left_to_do(run: _Turn) -> bool:
    """The question of the turn has been said and the round only repeated what was done or
    answered for the candidate: nothing more can be voiced, so another round is only latency
    (KI-08, D44)."""
    return run.asked and run.round_idle


def _offered(schemas: tuple[ToolSchema, ...], withheld: set[str]) -> tuple[ToolSchema, ...]:
    """The tools the next round may call: all but those whose call this turn changed nothing,
    so a model that repeats a done save has to answer in words (KI-08, D44)."""
    return tuple(schema for schema in schemas if schema.name not in withheld)


def _opening(state: SessionState) -> list[str]:
    return [prompts.load("opening", state.language).strip()]


def _resume(state: SessionState) -> list[str]:
    """The resume sentence, then the unanswered read-back so a yes or no still has a target."""
    spoken = [prompts.load("resume", state.language).strip()]
    pending = state.pending_confirmation
    if pending is not None and pending.status == "pending":
        spoken.append(pending.presentation_text)
    return spoken


_NOT_FOUND = TurnFailed(turn_id=TurnId(""), code="not_found", message=MESSAGES["es"]["not_found"])


def _control_reply(control: Literal["human", "time_cap", "goodbye"], language: Language) -> str:
    return prompts.table("controls", language)[control]


def _say(sentence: str) -> AssistantText:
    return AssistantText(text=sentence, spoken_form=sentence)
