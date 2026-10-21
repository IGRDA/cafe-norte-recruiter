"""``VoiceSession``: the voice logic with no Pipecat in sight. A fake runtime yields scripted
events; a recorder stands in for TTS; a controllable clock drives the idle timers."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime, timedelta
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


async def test_the_filler_waits_while_a_sentence_is_still_playing() -> None:
    """The filler fills silence; while "Vale, lo miro." is still playing there is none, so it
    is not queued behind it (D40)."""
    runtime = FakeRuntime(
        [
            [
                say("Vale, lo miro."),
                ToolStarted(name="search_knowledge"),
                ToolFinished(name="search_knowledge", ok=True, summary="x"),
                say("Está en el centro."),
                finished(),
            ]
        ],
        slow=True,
    )
    recorder = Recorder()
    s = session(runtime, recorder)
    s.filler_after_seconds = 0.0
    await s.transcript("¿Dónde está el local?")
    await s.wait()
    assert "Un momento." not in recorder.spoken
    assert runtime.asides == []


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
    """One prompt per candidate turn: speech that does not become a turn earns no other."""
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


async def test_a_new_turn_earns_a_new_prompt_even_when_its_apology_is_cut() -> None:
    """The prompt of one period does not carry over: the candidate answered, the turn failed,
    they spoke over the apology and went quiet. Silence is prompted again."""
    failed = TurnFailed(turn_id=TurnId("t1"), code="timeout", message="La operación tardó.")
    runtime = FakeRuntime([[say("¿Cómo te llamas?"), finished()], [failed]])
    recorder = Recorder()
    s = session(runtime, recorder, prompt=0.02)
    await s.transcript("hola")
    await s.wait()
    await s.played_one()
    await asyncio.sleep(0.03)  # first period: the prompt is said
    await s.played_one()
    await s.transcript("Lucía")  # a new turn, which fails: the apology is said at once
    await s.wait()
    await s.interrupted()  # the candidate speaks over the apology, then nothing follows
    await asyncio.sleep(0.04)
    assert recorder.spoken.count("¿Sigues ahí?") == 2
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


APOLOGY = "Perdona, se me ha cortado. ¿Me lo repites?"


def failed_after_two_sentences() -> FakeRuntime:
    failed = TurnFailed(turn_id=TurnId("t1"), code="limit_exceeded", message="Límite.")
    return FakeRuntime([[say("Te resumo lo que tengo."), say("¿Es todo correcto?"), failed]])


async def test_the_apology_is_said_when_the_queued_sentences_have_played() -> None:
    runtime = failed_after_two_sentences()
    recorder = Recorder()
    s = session(runtime, recorder)
    await s.transcript("Está todo bien.")
    await s.wait()
    await s.played_one()
    assert runtime.said == []  # one sentence is still playing
    await s.played_one()
    assert runtime.said == [APOLOGY] and recorder.spoken[-1] == APOLOGY
    # What was heard is still recorded for the failed turn: the summary played to the end.
    assert runtime.acks == [(TurnId("t1"), "Te resumo lo que tengo. ¿Es todo correcto?", True)]
    await s.close()


async def test_the_silence_clock_starts_when_the_apology_has_played() -> None:
    runtime = failed_after_two_sentences()
    recorder = Recorder()
    s = session(runtime, recorder, prompt=0.02)
    await s.transcript("Está todo bien.")
    await s.wait()
    await s.played_one()
    await s.played_one()  # the summary has played; the apology is now playing
    await asyncio.sleep(0.04)
    assert "¿Sigues ahí?" not in recorder.spoken  # silence is only what the candidate can hear
    await s.played_one()  # the apology has played
    await asyncio.sleep(0.04)
    assert recorder.spoken.count("¿Sigues ahí?") == 1
    await s.close()


async def test_an_interruption_drops_the_apology_still_owed() -> None:
    runtime = failed_after_two_sentences()
    recorder = Recorder()
    s = session(runtime, recorder)
    await s.transcript("Está todo bien.")
    await s.wait()
    await s.played_one()
    await s.interrupted()  # the candidate speaks before the summary ends
    await s.played_one()
    assert runtime.said == [] and APOLOGY not in recorder.spoken
    await s.close()


async def test_a_failed_turn_with_nothing_queued_apologises_at_once() -> None:
    failed = TurnFailed(turn_id=TurnId("t1"), code="timeout", message="La operación tardó.")
    runtime = FakeRuntime([[failed]])
    recorder = Recorder()
    s = session(runtime, recorder, prompt=0.02)
    await s.transcript("De lunes a viernes")
    await s.wait()
    assert runtime.said == [APOLOGY]
    await asyncio.sleep(0.04)
    assert "¿Sigues ahí?" not in recorder.spoken  # the apology is still playing
    await s.close()


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


# ---- an answer cut by a pause (KI-07, D44) -------------------------------------------------------


def cut_answer(now: list[datetime]) -> tuple[FakeRuntime, VoiceSession]:
    runtime = FakeRuntime([[say("¿Y qué día?"), finished()], [say("Perfecto."), finished()]])
    runtime.slow = True
    s = VoiceSession(
        runtime,
        SID,
        speak=Recorder().speak,
        on_status=lambda _status: None,
        texts=TEXTS,
        language="es",
        clock=lambda: now[0],
    )
    return runtime, s


async def test_a_pause_longer_than_the_join_window_starts_a_new_answer() -> None:
    now = [datetime(2026, 10, 20, tzinfo=UTC)]
    runtime, s = cut_answer(now)
    await s.transcript("El lunes,")
    await s.interrupted()
    now[0] += timedelta(seconds=VoiceSession.join_window_seconds + 0.1)
    await s.transcript("uno, de, dos de noviembre.")
    await s.wait()
    assert runtime.turns[-1].text == "uno, de, dos de noviembre."
    await s.close()


async def test_an_answer_that_was_heard_is_not_joined_to_the_next_words() -> None:
    now = [datetime(2026, 10, 20, tzinfo=UTC)]
    runtime, s = cut_answer(now)
    await s.transcript("El lunes,")
    await asyncio.sleep(0.03)  # "¿Y qué día?" was said
    await s.played_one()  # and heard
    await s.interrupted()
    await s.transcript("el dos de noviembre.")
    await s.wait()
    assert runtime.turns[-1].text == "el dos de noviembre."
    await s.close()


async def test_a_cut_part_is_joined_once() -> None:
    now = [datetime(2026, 10, 20, tzinfo=UTC)]
    runtime, s = cut_answer(now)
    runtime.scripts.append([say("Vale."), finished()])
    await s.transcript("El lunes,")
    await asyncio.sleep(0.005)  # the turn has started; nothing of it was said yet
    await s.interrupted()
    await s.transcript("uno, de, dos de noviembre.")
    await s.wait()
    await s.played_one()
    await s.played_one()
    await s.transcript("Sí.")
    await s.wait()
    assert [t.text for t in runtime.turns] == [
        "El lunes,",
        "El lunes, uno, de, dos de noviembre.",
        "Sí.",
    ]
    await s.close()
