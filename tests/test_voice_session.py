"""``VoiceSession``: the voice logic with no Pipecat in sight. A fake runtime yields scripted
events; a recorder stands in for TTS; a controllable clock drives the idle timers."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from typing import Literal

from cafe_norte.conversation.contracts import (
    AssistantText,
    RuntimeEvent,
    ToolFinished,
    ToolStarted,
    TurnFailed,
    TurnFinished,
    TurnInput,
    TurnStarted,
)
from cafe_norte.domain.contracts import SessionId, TurnId
from cafe_norte.errors import Language
from cafe_norte.voice.contracts import VoiceTexts
from cafe_norte.voice.session import VoiceSession

TEXTS: dict[Language, VoiceTexts] = {
    "es": VoiceTexts(
        opening="Hola, soy Ana.",
        filler="Un momento.",
        idle_prompt="¿Sigues ahí?",
        failure="Perdona, se me ha cortado. ¿Me lo repites?",
    ),
    "en": VoiceTexts(
        opening="Hi, I'm Ana.",
        filler="One moment.",
        idle_prompt="Still there?",
        failure="Sorry, I lost you there. Could you say that again?",
    ),
}

SID = SessionId("s")


def say(text: str) -> AssistantText:
    return AssistantText(text=text, spoken_form=text)


def finished(turn: str = "t1") -> TurnFinished:
    return TurnFinished(turn_id=TurnId(turn), interrupted=False, usage=(), timings=())


class FakeRuntime:
    def __init__(
        self, scripts: list[list[RuntimeEvent]], *, slow: bool = False, language: Language = "es"
    ) -> None:
        self.scripts = scripts
        self.language = language
        self.turns: list[TurnInput] = []
        self.acks: list[tuple[TurnId, str, bool]] = []
        self.ended: list[str] = []
        self.said: list[str] = []
        self.asides: list[tuple[TurnId, str]] = []
        self.closed = 0
        self.slow = slow

    async def run_turn(self, turn: TurnInput) -> AsyncGenerator[RuntimeEvent, None]:
        self.turns.append(turn)
        events = self.scripts.pop(0)
        try:
            yield TurnStarted(turn_id=TurnId("t1"), language=self.language, text=turn.text)
            for event in events:
                if self.slow:
                    await asyncio.sleep(0.01)
                yield event
        finally:
            self.closed += 1

    async def delivered(self, turn_id: TurnId, *, text: str, complete: bool) -> None:
        self.acks.append((turn_id, text, complete))

    async def end(
        self, session_id: SessionId, reason: Literal["stop", "limit", "shutdown"]
    ) -> None:
        self.ended.append(reason)

    async def say(self, session_id: SessionId, text: str) -> AsyncIterator[RuntimeEvent]:
        """A journaled system turn: what the real runtime yields for a fixed sentence."""
        self.said.append(text)
        yield TurnStarted(turn_id=TurnId("sys"), language=self.language, text="")
        yield AssistantText(text=text, spoken_form=text)
        yield TurnFinished(turn_id=TurnId("sys"), interrupted=False, usage=(), timings=())

    async def aside(self, turn_id: TurnId, text: str) -> None:
        self.asides.append((turn_id, text))


class Recorder:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.status: list[str] = []

    async def speak(self, text: str) -> None:
        self.spoken.append(text)


def session(
    runtime: FakeRuntime, recorder: Recorder, language: Language = "es", **limits: float
) -> VoiceSession:
    return VoiceSession(
        runtime,
        SID,
        speak=recorder.speak,
        on_status=recorder.status.append,
        texts=TEXTS,
        language=language,
        clock=lambda: datetime(2026, 10, 20, tzinfo=UTC),
        idle_prompt_seconds=limits.get("prompt", 8.0),
    )


async def test_a_final_transcript_runs_a_voice_turn_and_speaks_each_sentence() -> None:
    runtime = FakeRuntime([[say("Encantada."), say("¿Tienes permiso?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder)
    await s.transcript("Me llamo Lucía")
    await s.wait()
    assert runtime.turns[0].channel == "voice" and runtime.turns[0].text == "Me llamo Lucía"
    assert recorder.spoken == ["Encantada.", "¿Tienes permiso?"]
    assert recorder.status[-1] == "speaking"
    # Playback completes sentence by sentence; the full turn is acknowledged as delivered.
    await s.played_one()
    await s.played_one()
    assert runtime.acks == [(TurnId("t1"), "Encantada. ¿Tienes permiso?", True)]
    assert recorder.status[-1] == "listening"


async def test_an_interruption_cancels_the_turn_and_reports_what_was_heard() -> None:
    runtime = FakeRuntime(
        [
            [
                say("Te resumo lo que tengo."),
                say("Te llamas Lucía."),
                say("¿Es todo correcto?"),
                finished(),
            ]
        ],
        slow=True,
    )
    recorder = Recorder()
    s = session(runtime, recorder)
    await s.transcript("ya está")
    await asyncio.sleep(0.015)  # first sentence out, the rest still streaming
    await s.played_one()
    await s.interrupted()
    await s.wait()
    assert runtime.closed == 1  # the generator was closed: model stream cancelled
    assert runtime.acks == [(TurnId("t1"), "Te resumo lo que tengo.", False)]
    # A late playback event from the cancelled turn changes nothing.
    await s.played_one()
    assert len(runtime.acks) == 1


async def test_an_interruption_while_a_sentence_is_being_spoken_closes_the_runtime_turn() -> None:
    runtime = FakeRuntime([[say("Te resumo lo que tengo."), say("¿Es todo correcto?"), finished()]])
    recorder = Recorder()
    gate = asyncio.Event()

    async def blocked(text: str) -> None:  # TTS still busy with the first sentence
        recorder.spoken.append(text)
        await gate.wait()

    s = VoiceSession(
        runtime,
        SID,
        speak=blocked,
        on_status=recorder.status.append,
        texts=TEXTS,
        language="es",
    )
    await s.transcript("ya está")
    await asyncio.sleep(0.01)
    await s.interrupted()
    assert runtime.closed == 1  # closed now, not whenever the generator is collected


async def test_the_opening_is_spoken_once_on_join_and_a_second_join_is_silent() -> None:
    runtime = FakeRuntime([])
    recorder = Recorder()
    s = session(runtime, recorder)
    await s.joined()
    await s.wait()
    await s.joined()
    await s.wait()
    assert recorder.spoken == ["Hola, soy Ana."]


async def test_a_filler_is_spoken_only_while_a_tool_runs_long() -> None:
    runtime = FakeRuntime(
        [
            [
                ToolStarted(name="update_candidate"),
                ToolFinished(name="update_candidate", ok=True, summary="x"),
                say("¿Y tu nombre?"),
                finished(),
            ]
        ],
        slow=True,
    )
    recorder = Recorder()
    s = session(runtime, recorder)
    s.filler_after_seconds = 0.0  # a tool that takes any time at all triggers the filler
    await s.transcript("sí me interesa")
    await s.wait()
    assert recorder.spoken[0] == "Un momento."
    assert recorder.spoken[-1] == "¿Y tu nombre?"
    assert runtime.asides == [(TurnId("t1"), "Un momento.")]  # journaled, so it is on screen


async def test_the_opening_is_spoken_in_the_session_language() -> None:
    recorder = Recorder()
    s = session(FakeRuntime([]), recorder, language="en")
    await s.joined()
    assert recorder.spoken == ["Hi, I'm Ana."]


async def test_the_filler_follows_a_language_switched_in_the_turn() -> None:
    runtime = FakeRuntime(
        [[ToolStarted(name="update_candidate"), say("What is your name?"), finished()]],
        slow=True,
        language="en",
    )
    recorder = Recorder()
    s = session(runtime, recorder)  # opened in Spanish; the runtime switched this turn
    s.filler_after_seconds = 0.0
    await s.transcript("Can we continue in English?")
    await s.wait()
    assert recorder.spoken[0] == "One moment."


async def test_silence_prompts_once_and_never_pauses_a_live_call() -> None:
    """S18 (silence): one prompt and the state untouched. The hosted call of 21 October: the
    session went "paused" while the candidate was still talking."""
    runtime = FakeRuntime([[say("¿Cómo te llamas?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder, prompt=0.02)
    await s.transcript("hola")
    await s.wait()
    await s.played_one()  # listening starts the idle clock
    await asyncio.sleep(0.03)
    assert recorder.spoken[-1] == "¿Sigues ahí?"
    await asyncio.sleep(0.06)
    assert recorder.spoken.count("¿Sigues ahí?") == 1
    assert runtime.ended == []
    assert recorder.status[-1] != "paused"
    await s.close()


async def test_any_heard_speech_resets_the_silence_clock() -> None:
    """A soft "sí" that VAD misses still reaches STT: it is not silence."""
    runtime = FakeRuntime([[say("¿Cómo te llamas?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder, prompt=0.03)
    await s.transcript("hola")
    await s.wait()
    await s.played_one()
    await asyncio.sleep(0.02)
    await s.heard_speech()
    await asyncio.sleep(0.02)  # 0.04 since listening, 0.02 since speech: no prompt yet
    assert "¿Sigues ahí?" not in recorder.spoken
    await s.close()


async def test_speech_that_comes_to_nothing_still_earns_one_prompt_later() -> None:
    """A cough starts the aggregator's turn and no transcript follows: the clock restarts."""
    runtime = FakeRuntime([[say("¿Cómo te llamas?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder, prompt=0.03)
    await s.transcript("hola")
    await s.wait()
    await s.played_one()
    await s.interrupted()
    await asyncio.sleep(0.06)
    assert recorder.spoken.count("¿Sigues ahí?") == 1
    await s.close()


async def test_speech_after_the_prompt_does_not_earn_a_second_one() -> None:
    """One prompt per listening period; only a new turn starts a new period."""
    runtime = FakeRuntime([[say("¿Cómo te llamas?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder, prompt=0.02)
    await s.transcript("hola")
    await s.wait()
    await s.played_one()
    await asyncio.sleep(0.03)  # the prompt is said
    await s.heard_speech()
    await s.interrupted()
    await asyncio.sleep(0.05)
    assert recorder.spoken.count("¿Sigues ahí?") == 1
    await s.close()


async def test_the_call_ending_pauses_the_session_once() -> None:
    runtime = FakeRuntime([])
    s = session(runtime, Recorder())
    await s.close()
    await s.close()
    assert runtime.ended == ["shutdown"]


async def test_the_silence_prompt_is_a_journaled_turn() -> None:
    """The hosted call: "¿Sigues ahí?" was heard but never appeared in the transcript."""
    runtime = FakeRuntime([[say("¿Cómo te llamas?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder, prompt=0.01)
    await s.transcript("hola")
    await s.wait()
    await s.played_one()
    await asyncio.sleep(0.03)
    assert runtime.said == ["¿Sigues ahí?"]
    assert recorder.spoken[-1] == "¿Sigues ahí?"
    await s.close()


async def test_a_failed_turn_is_followed_by_a_spoken_and_journaled_apology() -> None:
    """The hosted call: after a timeout Ana said nothing and the candidate waited."""
    failed = TurnFailed(turn_id=TurnId("t1"), code="timeout", message="La operación tardó.")
    runtime = FakeRuntime([[failed]])
    recorder = Recorder()
    s = session(runtime, recorder)
    await s.transcript("De lunes a viernes")
    await s.wait()
    assert runtime.said == ["Perdona, se me ha cortado. ¿Me lo repites?"]
    assert recorder.spoken[-1] == "Perdona, se me ha cortado. ¿Me lo repites?"


async def test_a_language_switch_is_reported_once_so_recognition_follows_it() -> None:
    runtime = FakeRuntime([[finished()], [finished()]], language="en")
    switched: list[Language] = []
    s = VoiceSession(
        runtime,
        SID,
        speak=Recorder().speak,
        on_status=lambda _: None,
        texts=TEXTS,
        language="es",
        on_language=switched.append,
    )
    await s.transcript("in English, please")
    await s.wait()
    await s.transcript("my name is Lucy")
    await s.wait()
    assert switched == ["en"]
