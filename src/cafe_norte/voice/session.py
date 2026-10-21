"""``VoiceSession``: everything voice decides, with no audio framework in it.

Inputs are method calls from the two Pipecat processors in ``bridge.py`` (final transcript,
interruption, one sentence finished playing, participant joined). Outputs are ``speak`` (a
sentence to TTS), ``on_status`` and the runtime's ``run_turn`` / ``delivered`` / ``end``. The
delivery ledger decides what was heard. Tested with a fake runtime and a recorder."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Literal, Protocol

from cafe_norte.conversation.contracts import (
    AssistantText,
    RuntimeEvent,
    ToolFinished,
    ToolStarted,
    TurnFinished,
    TurnInput,
    TurnStarted,
)
from cafe_norte.domain.contracts import InputId, SessionId, TurnId
from cafe_norte.errors import Language
from cafe_norte.voice.contracts import VoiceStatus, VoiceTexts
from cafe_norte.voice.delivery import Ledger, finished, heard, sent

Speak = Callable[[str], Awaitable[None]]


class VoiceRuntime(Protocol):
    """The three things voice needs from the conversation runtime."""

    def run_turn(self, turn: TurnInput) -> AsyncIterator[RuntimeEvent]: ...
    async def delivered(self, turn_id: TurnId, *, text: str, complete: bool) -> None: ...
    async def end(
        self, session_id: SessionId, reason: Literal["stop", "limit", "shutdown"]
    ) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


class VoiceSession:
    filler_after_seconds: float = 1.5

    def __init__(
        self,
        runtime: VoiceRuntime,
        session_id: SessionId,
        *,
        speak: Speak,
        on_status: Callable[[VoiceStatus], None],
        texts: Mapping[Language, VoiceTexts],
        language: Language,
        clock: Callable[[], datetime] | None = None,
        idle_prompt_seconds: float = 8.0,
    ) -> None:
        self._runtime = runtime
        self._session_id = session_id
        self._speak = speak
        self._on_status = on_status
        self._texts_by_language = texts
        self._language = language  # follows each turn, so a switch changes the next filler
        self._clock = clock or _utcnow
        self._idle_prompt_seconds = idle_prompt_seconds
        self._closed = False
        self.status: VoiceStatus = "connecting"
        self._ledger = Ledger()
        self._turn_task: asyncio.Task[None] | None = None
        self._turn_id: TurnId | None = None
        self._turn_done = False
        self._acknowledged = False
        self._opened = False
        self._filler_task: asyncio.Task[None] | None = None
        self._idle_task: asyncio.Task[None] | None = None

    # ---- inputs from the audio side --------------------------------------------------------------

    async def joined(self) -> None:
        """The candidate is in the room: Ana speaks the opening, once."""
        if self._opened:
            return
        self._opened = True
        self._set("speaking")
        self._ledger = sent(self._ledger, self._texts.opening)
        self._turn_done = True
        await self._speak(self._texts.opening)

    async def transcript(self, text: str) -> None:
        """A finalized transcript: one voice turn through the runtime."""
        self._cancel_idle()
        if self._turn_task is not None and not self._turn_task.done():
            return  # an interruption frame precedes any new speech; nothing to do here
        turn = TurnInput(
            session_id=self._session_id,
            input_id=InputId(uuid.uuid4().hex),
            text=text,
            channel="voice",
            received_at=self._clock(),
        )
        self._ledger, self._turn_id, self._turn_done, self._acknowledged = (
            Ledger(),
            None,
            False,
            False,
        )
        self._set("thinking")
        self._turn_task = asyncio.create_task(self._run(turn))

    async def played_one(self) -> None:
        """One sentence finished playing on the candidate's side."""
        self._ledger = finished(self._ledger)
        await self._maybe_acknowledge()

    async def interrupted(self) -> None:
        """The candidate started speaking over Ana: stop generating, record what was heard."""
        self._cancel_filler()
        task, self._turn_task = self._turn_task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._turn_id is not None and not self._acknowledged:
            text, _ = heard(self._ledger)
            self._acknowledged = True
            await self._runtime.delivered(self._turn_id, text=text, complete=False)
        self._ledger = Ledger()
        self._set("listening")

    async def wait(self) -> None:
        if self._turn_task is not None:
            await asyncio.gather(self._turn_task, return_exceptions=True)

    async def heard_speech(self) -> None:
        """Any raw transcript, interim or final: the candidate is talking, so it is not
        silence, even when VAD missed it and no turn has started yet (D35)."""
        if self.status == "listening":
            self._start_idle()

    async def close(self) -> None:
        """The call is over (hang-up, disconnect, expiry, stop): the session pauses here, and
        only here, so it can be resumed with the private link. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._cancel_idle()
        self._cancel_filler()
        if self._turn_task is not None:
            self._turn_task.cancel()
            await asyncio.gather(self._turn_task, return_exceptions=True)
        await self._runtime.end(self._session_id, "shutdown")
        self._set("ended")

    # ---- the turn --------------------------------------------------------------------------------

    async def _run(self, turn: TurnInput) -> None:
        try:
            async for event in self._runtime.run_turn(turn):
                if isinstance(event, TurnStarted):
                    self._turn_id = event.turn_id
                    self._language = event.language
                elif isinstance(event, AssistantText):
                    self._cancel_filler()
                    self._ledger = sent(self._ledger, event.spoken_form)
                    self._set("speaking")
                    await self._speak(event.spoken_form)
                elif isinstance(event, ToolStarted):
                    self._filler_task = asyncio.create_task(self._filler())
                elif isinstance(event, ToolFinished):
                    self._cancel_filler()
                elif isinstance(event, TurnFinished):
                    self._turn_done = True
        finally:
            self._cancel_filler()
            self._turn_done = True
        await self._maybe_acknowledge()

    async def _filler(self) -> None:
        await asyncio.sleep(self.filler_after_seconds)
        self._ledger = sent(self._ledger, self._texts.filler)
        await self._speak(self._texts.filler)

    async def _maybe_acknowledge(self) -> None:
        """Once the turn has ended and its last sentence has played, tell the runtime."""
        text, complete = heard(self._ledger)
        if not (self._turn_done and complete) or self._acknowledged:
            return
        self._acknowledged = True
        if self._turn_id is not None:
            await self._runtime.delivered(self._turn_id, text=text, complete=True)
        self._set("listening")
        self._start_idle()

    @property
    def _texts(self) -> VoiceTexts:
        return self._texts_by_language[self._language]

    # ---- silence ---------------------------------------------------------------------------------

    def _start_idle(self) -> None:
        self._cancel_idle()
        self._idle_task = asyncio.create_task(self._idle())

    async def _idle(self) -> None:
        """One "¿Sigues ahí?" after the silence; a live call is never paused for silence."""
        await asyncio.sleep(self._idle_prompt_seconds)
        await self._speak(self._texts.idle_prompt)

    def _cancel_idle(self) -> None:
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None

    def _cancel_filler(self) -> None:
        if self._filler_task is not None:
            self._filler_task.cancel()
            self._filler_task = None

    def _set(self, status: VoiceStatus) -> None:
        self.status = status
        self._on_status(status)
