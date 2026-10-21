"""Known issues from the second hosted voice call of 21 October (docs/known-issues.md).

Each test reproduces one problem offline and is marked ``xfail(strict=True)``: it fails today,
as it should, and the suite stays green. The fix makes it pass, strict xfail then fails the
suite, and the marker comes off in the same commit as the fix.
"""

import asyncio

import pytest

from cafe_norte.conversation.contracts import TurnFailed
from cafe_norte.conversation.signals import answer_to_readback
from cafe_norte.domain.contracts import TurnId
from tests.test_runtime import (
    SESSION,
    WANTS_TOOLS,
    Harness,
    fill_record,
    present_brief,
    says,
    turn,
)
from tests.test_voice_session import FakeRuntime, Recorder, finished, say, session


@pytest.mark.xfail(strict=True, reason="KI-01: 'está todo bien' is not a plain yes")
@pytest.mark.parametrize(
    "text",
    ["Sí, está todo bien.", "Está todo bien.", "Está todo bien. Todo correcto.", "Todo bien"],
)
def test_ki01_everyday_ways_of_saying_it_is_all_correct_are_a_plain_yes(text: str) -> None:
    assert answer_to_readback(text) == "affirm"


@pytest.mark.xfail(
    strict=True, reason="KI-03: the candidate speaking does not stop the silence clock"
)
async def test_ki03_the_candidate_starting_to_speak_cancels_the_silence_prompt() -> None:
    """Live: Aggregator 'User started speaking' at 16:06:46.7, '¿Sigues ahí?' at 16:06:50.1.
    In the pipeline the start of speech reaches the session as an interruption; raw transcripts
    never do (Pipecat's aggregator consumes them)."""
    runtime = FakeRuntime([[say("¿Tienes permiso de trabajo?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder, prompt=0.03)
    await s.transcript("Sí, me interesa.")
    await s.wait()
    await s.played_one()  # the question has played: the silence clock starts
    await asyncio.sleep(0.01)
    await s.interrupted()  # the candidate starts answering
    await asyncio.sleep(0.05)
    assert "¿Sigues ahí?" not in recorder.spoken
    await s.close()


@pytest.mark.xfail(strict=True, reason="KI-04: playback finishing re-arms the silence prompt")
async def test_ki04_after_a_failed_turn_the_silence_prompt_is_said_once() -> None:
    """Live: the failed turn's summary was still playing; the apology (16:09:04) started the
    silence clock, '¿Sigues ahí?' came at 16:09:12, and when the summary's last sentence
    finished playing the clock was armed again: a second '¿Sigues ahí?' at 16:09:28."""
    failed = TurnFailed(turn_id=TurnId("t1"), code="limit_exceeded", message="Límite.")
    runtime = FakeRuntime([[say("Te resumo lo que tengo."), say("¿Es todo correcto?"), failed]])
    recorder = Recorder()
    s = session(runtime, recorder, prompt=0.02)
    await s.transcript("Está todo bien.")
    await s.wait()
    await asyncio.sleep(0.03)  # first prompt, while the summary is still playing
    await s.played_one()
    await s.played_one()  # the summary's two sentences finish playing
    await asyncio.sleep(0.04)
    assert recorder.spoken.count("¿Sigues ahí?") == 1
    await s.close()


@pytest.mark.xfail(strict=True, reason="KI-05: system sentences jump the audio queue")
async def test_ki05_the_apology_waits_for_the_sentences_still_playing() -> None:
    """Live: the third summary was still playing until 16:09:23 while the apology (16:09:04)
    and '¿Sigues ahí?' (16:09:12) were journaled and queued behind it."""
    failed = TurnFailed(turn_id=TurnId("t1"), code="limit_exceeded", message="Límite.")
    runtime = FakeRuntime([[say("Te resumo lo que tengo."), say("¿Es todo correcto?"), failed]])
    recorder = Recorder()
    s = session(runtime, recorder)
    await s.transcript("Está todo bien.")
    await s.wait()
    # Two sentences were sent to TTS and none has finished playing yet.
    assert "Perdona, se me ha cortado. ¿Me lo repites?" not in runtime.said
    await s.close()


@pytest.mark.xfail(strict=True, reason="KI-02: a yes to a summary cut short by speech is lost")
async def test_ki02_a_yes_to_the_summary_on_screen_confirms_it_even_if_its_audio_was_cut() -> None:
    """Live: the summary takes about 12 s to speak and is shown at once on the page. Iñaki read
    it and answered "Sí, está todo bien" at 10.8 s, before "¿Es todo correcto?" played; the
    read-back was not heard, so the yes could not confirm it; it was read again three times,
    each one interrupted the same way, until the turn hit its round limit (16:09:04)."""
    h = Harness([[present_brief(), WANTS_TOOLS], says(""), says("¿Alguna duda?")])
    await h.open_session()
    await fill_record(h)
    voice = turn("ya está todo", "in-1").model_copy(update={"channel": "voice"})
    async for _ in h.runtime.run_turn(voice):
        pass  # voice: delivery comes from playback, which the candidate cut short
    answer = turn("Sí.", "in-2").model_copy(update={"channel": "voice"})
    async for _ in h.runtime.run_turn(answer):
        pass
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"
