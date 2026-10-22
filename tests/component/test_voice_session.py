"""``VoiceSession``: the voice logic with no Pipecat in sight. A fake runtime yields scripted
events; a recorder stands in for TTS; virtual time (``FakeTime``) drives every timer."""

import asyncio

from cafe_norte.conversation.contracts import (
    StateUpdated,
    ToolFinished,
    ToolStarted,
    TurnFailed,
)
from cafe_norte.domain.contracts import CandidateRecord, Lifecycle, TurnId
from cafe_norte.errors import Language
from cafe_norte.voice.session import VoiceSession
from tests.support.builders import SID, session_state
from tests.support.time import FakeTime, settle
from tests.support.voice import TEXTS, FakeRuntime, Recorder, finished, say, session


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
    time = FakeTime()
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
        sleep=time.sleep,
    )
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    await s.transcript("ya está")
    await time.advance(0.015)  # first sentence out, the rest still streaming
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
    await settle()  # the first sentence is with TTS, which has not finished it
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
    time = FakeTime()
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
        sleep=time.sleep,
    )
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    s.filler_after_seconds = 0.0  # a tool that takes any time at all triggers the filler
    await s.transcript("sí me interesa")
    await time.advance(1)  # every scripted event has come
    await s.wait()
    assert recorder.spoken[0] == "Un momento."
    assert recorder.spoken[-1] == "¿Y tu nombre?"
    assert runtime.asides == [(TurnId("t1"), "Un momento.")]  # journaled, so it is on screen


async def test_the_filler_waits_while_a_sentence_is_still_playing() -> None:
    time = FakeTime()
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
        sleep=time.sleep,
    )
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    s.filler_after_seconds = 0.0
    await s.transcript("¿Dónde está el local?")
    await time.advance(1)  # every scripted event has come
    await s.wait()
    assert "Un momento." not in recorder.spoken
    assert runtime.asides == []


async def test_the_opening_is_spoken_in_the_session_language() -> None:
    recorder = Recorder()
    s = session(FakeRuntime([]), recorder, language="en")
    await s.joined()
    assert recorder.spoken == ["Hi, I'm Ana."]


async def test_the_filler_follows_a_language_switched_in_the_turn() -> None:
    time = FakeTime()
    runtime = FakeRuntime(
        [[ToolStarted(name="update_candidate"), say("What is your name?"), finished()]],
        slow=True,
        sleep=time.sleep,
        language="en",
    )
    recorder = Recorder()
    s = session(runtime, recorder, time=time)  # opened in Spanish; the runtime switched this turn
    s.filler_after_seconds = 0.0
    await s.transcript("Can we continue in English?")
    await time.advance(1)  # every scripted event has come
    await s.wait()
    assert recorder.spoken[0] == "One moment."


async def test_silence_prompts_once_and_never_pauses_a_live_call() -> None:
    """S18 (silence): one prompt and the state untouched. The hosted call of 21 October: the
    session went "paused" while the candidate was still talking."""
    time = FakeTime()
    runtime = FakeRuntime([[say("¿Cómo te llamas?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    await s.transcript("hola")
    await s.wait()
    await s.played_one()  # listening starts the idle clock

    await time.advance(7.9)
    assert "¿Sigues ahí?" not in recorder.spoken
    await time.advance(0.1)
    assert recorder.spoken[-1] == "¿Sigues ahí?"
    await s.played_one()
    await time.advance(60)

    assert recorder.spoken.count("¿Sigues ahí?") == 1
    assert runtime.ended == []
    assert recorder.status[-1] != "paused"
    await s.close()


async def test_any_heard_speech_resets_the_silence_clock() -> None:
    """A soft "sí" that VAD misses still reaches STT: it is not silence."""
    time = FakeTime()
    runtime = FakeRuntime([[say("¿Cómo te llamas?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    await s.transcript("hola")
    await s.wait()
    await s.played_one()

    await time.advance(5)
    await s.heard_speech()
    await time.advance(5)  # 10 s since listening, 5 s since speech: no prompt yet
    assert "¿Sigues ahí?" not in recorder.spoken
    await time.advance(3)  # 8 s since speech

    assert recorder.spoken.count("¿Sigues ahí?") == 1
    await s.close()


async def test_speech_that_comes_to_nothing_still_earns_one_prompt_later() -> None:
    """A cough starts the aggregator's turn and no transcript follows: the clock restarts."""
    time = FakeTime()
    runtime = FakeRuntime([[say("¿Cómo te llamas?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    await s.transcript("hola")
    await s.wait()
    await s.played_one()

    await s.interrupted()
    await time.advance(20)

    assert recorder.spoken.count("¿Sigues ahí?") == 1
    await s.close()


async def test_speech_after_the_prompt_does_not_earn_a_second_one() -> None:
    """One prompt per candidate turn: speech that does not become a turn earns no other."""
    time = FakeTime()
    runtime = FakeRuntime([[say("¿Cómo te llamas?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    await s.transcript("hola")
    await s.wait()
    await s.played_one()
    await time.advance(8)  # the prompt is said

    await s.heard_speech()
    await s.interrupted()
    await time.advance(20)

    assert recorder.spoken.count("¿Sigues ahí?") == 1
    await s.close()


async def test_a_new_turn_earns_a_new_prompt_even_when_its_apology_is_cut() -> None:
    """The prompt of one period does not carry over: the candidate answered, the turn failed,
    they spoke over the apology and went quiet. Silence is prompted again."""
    time = FakeTime()
    failed = TurnFailed(turn_id=TurnId("t1"), code="timeout", message="La operación tardó.")
    runtime = FakeRuntime([[say("¿Cómo te llamas?"), finished()], [failed]])
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    await s.transcript("hola")
    await s.wait()
    await s.played_one()
    await time.advance(8)  # first period: the prompt is said
    await s.played_one()

    await s.transcript("Lucía")  # a new turn, which fails: the apology is said at once
    await s.wait()
    await s.interrupted()  # the candidate speaks over the apology, then nothing follows
    await time.advance(8)

    assert recorder.spoken.count("¿Sigues ahí?") == 2
    await s.close()


async def test_the_call_ending_pauses_the_session_once() -> None:
    runtime = FakeRuntime([])
    s = session(runtime, Recorder())
    await s.close()
    await s.close()
    assert runtime.ended == ["shutdown"]


def ended(lifecycle: Lifecycle = "completed") -> StateUpdated:
    return StateUpdated(
        revision=1,
        candidate=CandidateRecord(),
        pending_confirmation=None,
        booking=None,
        lifecycle=lifecycle,
        outcome="reserved" if lifecycle == "completed" else None,
    )


def hanging(runtime: FakeRuntime, time: FakeTime) -> tuple[VoiceSession, list[str]]:
    """A session whose hang-ups are counted, on virtual time."""
    hung_up: list[str] = []

    async def hang_up() -> None:
        hung_up.append("bye")

    s = VoiceSession(
        runtime,
        SID,
        speak=Recorder().speak,
        on_status=lambda _status: None,
        texts=TEXTS,
        language="es",
        on_hang_up=hang_up,
        sleep=time.sleep,
    )
    return s, hung_up


async def test_ana_hangs_up_two_seconds_after_her_goodbye_has_played() -> None:
    """The hosted call: the page left the room before "¡Hasta pronto!" was heard. And after
    D48 she left the instant it had played, which felt like a slam (D59)."""
    time = FakeTime()
    runtime = FakeRuntime([[say("Gracias, Lucía."), say("¡Hasta pronto!"), ended(), finished()]])
    s, hung_up = hanging(runtime, time)
    await s.transcript("nada más, gracias")
    await s.wait()
    await s.played_one()
    assert hung_up == []  # the goodbye is still playing
    await s.played_one()
    assert runtime.acks == [(TurnId("t1"), "Gracias, Lucía. ¡Hasta pronto!", True)]
    await time.advance(VoiceSession.hang_up_grace_seconds - 0.5)
    assert hung_up == []  # the grace is running
    await time.advance(0.6)
    assert hung_up == ["bye"]
    await s.played_one()  # a late playback report hangs up nothing twice
    await time.advance(5)
    assert hung_up == ["bye"]
    await s.close()


async def test_talking_over_the_goodbye_waits_for_the_words_then_leaves() -> None:
    """Live: "Ya está… pero no lo entiendo muy bien… cuelga" after the goodbye all failed on
    an ended session; before that, talking over the goodbye hung up at once (D48). Now Ana
    waits for the candidate to finish, runs no turn on the ended session, and leaves."""
    time = FakeTime()
    runtime = FakeRuntime([[say("¡Hasta pronto!"), ended(), finished()]])
    s, hung_up = hanging(runtime, time)
    await s.transcript("adiós")
    await s.wait()
    await s.interrupted()
    await time.advance(VoiceSession.hang_up_grace_seconds + 1)
    assert hung_up == []  # they are speaking: no hang-up yet
    await s.transcript("pero no lo entiendo muy bien")
    assert len(runtime.turns) == 1  # nothing runs on the ended session
    await time.advance(VoiceSession.hang_up_grace_seconds + 0.1)
    assert hung_up == ["bye"]
    await s.close()


async def test_a_sound_over_the_goodbye_with_no_words_still_ends_the_call() -> None:
    time = FakeTime()
    runtime = FakeRuntime([[say("¡Hasta pronto!"), ended(), finished()]])
    s, hung_up = hanging(runtime, time)
    await s.transcript("adiós")
    await s.wait()
    await s.interrupted()  # a cough: no transcript ever comes
    await time.advance(VoiceSession.hang_up_fallback_seconds + 0.1)
    assert hung_up == ["bye"]
    await s.close()


async def test_a_session_still_open_keeps_listening() -> None:
    runtime = FakeRuntime([[say("¿Qué días puedes?"), ended("active"), finished()]])
    s, hung_up = hanging(runtime, FakeTime())
    await s.transcript("hola")
    await s.wait()
    await s.played_one()
    assert hung_up == [] and s.status == "listening"
    await s.close()


async def test_the_silence_prompt_is_a_journaled_turn() -> None:
    """The hosted call: "¿Sigues ahí?" was heard but never appeared in the transcript."""
    time = FakeTime()
    runtime = FakeRuntime([[say("¿Cómo te llamas?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    await s.transcript("hola")
    await s.wait()
    await s.played_one()

    await time.advance(8)

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
    time = FakeTime()
    runtime = failed_after_two_sentences()
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    await s.transcript("Está todo bien.")
    await s.wait()
    await s.played_one()
    await s.played_one()  # the summary has played; the apology is now playing

    await time.advance(20)
    assert "¿Sigues ahí?" not in recorder.spoken  # silence is only what the candidate can hear
    await s.played_one()  # the apology has played
    await time.advance(8)

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
    time = FakeTime()
    failed = TurnFailed(turn_id=TurnId("t1"), code="timeout", message="La operación tardó.")
    runtime = FakeRuntime([[failed]])
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    await s.transcript("De lunes a viernes")
    await s.wait()
    assert runtime.said == [APOLOGY]

    await time.advance(20)

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


async def test_a_switch_announced_inside_the_turn_moves_recognition_before_ana_speaks() -> None:
    switched_state = session_state(SID).model_copy(update={"language": "en"})
    runtime = FakeRuntime([[StateUpdated.of(switched_state), say("Sure."), finished()]])
    switched: list[Language] = []
    recorder = Recorder()
    s = VoiceSession(
        runtime,
        SID,
        speak=recorder.speak,
        on_status=lambda _: None,
        texts=TEXTS,
        language="es",
        on_language=switched.append,
    )

    await s.transcript("perdona, no hablo bien español")
    await s.wait()

    assert switched == ["en"]
    assert recorder.spoken == ["Sure."]


# ---- an answer cut by a pause (KI-07, D44) -------------------------------------------------------


def cut_answer(time: FakeTime) -> tuple[FakeRuntime, VoiceSession]:
    """Ana's answers stream 0.01 s apart, so a test can cut one before any of it is said."""
    runtime = FakeRuntime(
        [[say("¿Y qué día?"), finished()], [say("Perfecto."), finished()]],
        slow=True,
        sleep=time.sleep,
    )
    return runtime, session(runtime, Recorder(), time=time)


async def answered(s: VoiceSession, time: FakeTime) -> None:
    """The running turn streams to its end."""
    await time.advance(1)
    await s.wait()


async def test_a_pause_longer_than_the_join_window_starts_a_new_answer() -> None:
    time = FakeTime()
    runtime, s = cut_answer(time)
    await s.transcript("El lunes,")
    await settle()

    await time.advance(VoiceSession.join_window_seconds + 0.1)  # silent, then speaking again
    await s.interrupted()
    await s.transcript("uno, de, dos de noviembre.")
    await answered(s, time)

    assert runtime.turns[-1].text == "uno, de, dos de noviembre."
    await s.close()


async def test_a_long_continuation_is_joined_when_it_started_inside_the_window() -> None:
    """Ignacio's call: "Sí, soy español, pero lo que quiero saber es" was cut, and the rest
    took longer than the window to finish. The window counts the pause, not the words after
    it (it ran to the continuation's final transcript)."""
    time = FakeTime()
    runtime, s = cut_answer(time)
    await s.transcript("Sí, soy español, pero lo que quiero saber es")
    await settle()

    await s.interrupted()  # they start speaking again at once
    await time.advance(VoiceSession.join_window_seconds + 2)  # and talk for seven seconds
    await s.transcript("cuánto dinero voy a ganar en el bar este al año.")
    await answered(s, time)

    assert runtime.turns[-1].text == (
        "Sí, soy español, pero lo que quiero saber es "
        "cuánto dinero voy a ganar en el bar este al año."
    )
    await s.close()


async def test_an_answer_that_was_heard_is_not_joined_to_the_next_words() -> None:
    time = FakeTime()
    runtime, s = cut_answer(time)
    await s.transcript("El lunes,")
    await time.advance(0.03)  # "¿Y qué día?" was said
    await s.played_one()  # and heard

    await s.interrupted()
    await s.transcript("el dos de noviembre.")
    await answered(s, time)

    assert runtime.turns[-1].text == "el dos de noviembre."
    await s.close()


async def test_a_cut_part_is_joined_once() -> None:
    time = FakeTime()
    runtime, s = cut_answer(time)
    runtime.scripts.append([say("Vale."), finished()])
    await s.transcript("El lunes,")
    await settle()  # the turn has started; nothing of it was said yet

    await s.interrupted()
    await s.transcript("uno, de, dos de noviembre.")
    await answered(s, time)
    await s.played_one()
    await s.played_one()
    await s.transcript("Sí.")
    await answered(s, time)

    assert [t.text for t in runtime.turns] == [
        "El lunes,",
        "El lunes, uno, de, dos de noviembre.",
        "Sí.",
    ]
    await s.close()
