"""Known issues from the second hosted voice call of 21 October (docs/known-issues.md).

Each test reproduces one problem offline and is marked ``xfail(strict=True)``: it fails today,
as it should, and the suite stays green. The fix makes it pass, strict xfail then fails the
suite, and the marker comes off in the same commit as the fix. KI-03, KI-04 and KI-05 are fixed
(D40), KI-06 (D41), KI-01 and KI-02 (D39), KI-07 and KI-08 (D44); their tests stay as
regression guards.
"""

import json

import pytest

from cafe_norte.conversation.contracts import AssistantText, TurnFailed
from cafe_norte.conversation.signals import answer_to_readback
from cafe_norte.domain.confirmation import assurance
from cafe_norte.domain.contracts import TurnId
from cafe_norte.model.contracts import ModelEvent, ModelMessage, ModelText, ToolCall, ToolSchema
from cafe_norte.model.fake import FakeModel
from tests.support.builders import SESSION
from tests.support.harness import (
    DATE_CALL,
    FRI_1030,
    STOP,
    WANTS_TOOLS,
    Harness,
    fill_record,
    name_call,
    present_brief,
    says,
    slots_offered,
    turn,
    with_slots_offered,
)
from tests.support.time import FakeTime
from tests.support.voice import FakeRuntime, Recorder, finished, say, session


@pytest.mark.parametrize(
    "text",
    ["Sí, está todo bien.", "Está todo bien.", "Está todo bien. Todo correcto.", "Todo bien"],
)
def test_ki01_everyday_ways_of_saying_it_is_all_correct_are_a_plain_yes(text: str) -> None:
    assert answer_to_readback(text) == "affirm"


async def test_ki03_the_candidate_starting_to_speak_restarts_the_silence_clock() -> None:
    """Live: Aggregator 'User started speaking' at 16:06:46.7, '¿Sigues ahí?' at 16:06:50.1.
    In the pipeline the start of speech reaches the session as an interruption."""
    time = FakeTime()
    runtime = FakeRuntime([[say("¿Tienes permiso de trabajo?"), finished()]])
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    await s.transcript("Sí, me interesa.")
    await s.wait()
    await s.played_one()  # the question has played: the silence clock starts
    await time.advance(5)
    await s.interrupted()  # the candidate starts answering
    await time.advance(5)  # 10 s since the question, 5 s since the speech
    assert "¿Sigues ahí?" not in recorder.spoken
    await s.close()


async def test_ki04_after_a_failed_turn_the_silence_prompt_is_said_once() -> None:
    """Live: the failed turn's summary was still playing; the apology (16:09:04) started the
    silence clock, '¿Sigues ahí?' came at 16:09:12, and when the summary's last sentence
    finished playing the clock was armed again: a second '¿Sigues ahí?' at 16:09:28."""
    failed = TurnFailed(turn_id=TurnId("t1"), code="limit_exceeded", message="Límite.")
    runtime = FakeRuntime([[say("Te resumo lo que tengo."), say("¿Es todo correcto?"), failed]])
    recorder = Recorder()
    time = FakeTime()
    s = session(runtime, recorder, time=time)
    await s.transcript("Está todo bien.")
    await s.wait()
    await time.advance(20)  # the summary is still playing: no silence to prompt about
    await s.played_one()
    await s.played_one()  # the summary's two sentences finish playing
    await s.played_one()  # and then the apology
    await time.advance(30)
    assert recorder.spoken.count("¿Sigues ahí?") == 1
    await s.close()


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


async def test_ki02_a_yes_over_the_summary_earns_one_offer_and_carrying_on_confirms_it() -> None:
    """Live: the summary takes about 12 s to speak and is shown at once on the page. Iñaki read
    it and answered "Sí, está todo bien" at 10.8 s, before "¿Es todo correcto?" played; the
    read-back was not heard, so the yes could not confirm it; it was read again three times,
    each one interrupted the same way, until the turn hit its round limit (16:09:04).

    Decided (D39): the yes is not a confirmation of what was not heard; it earns one offer, in
    the model's words, and "sigue" confirms it, recorded as waived. The model never re-reads."""
    offer = "Perdona, me has contestado antes de acabar. ¿Lo repasamos por partes o seguimos?"
    h = Harness([[present_brief(), WANTS_TOOLS], says(""), says(offer), says("¿Alguna duda?")])
    await h.open_session()
    await fill_record(h)
    voice = turn("ya está todo", "in-1").model_copy(update={"channel": "voice"})
    async for _ in h.runtime.run_turn(voice):
        pass  # voice: delivery comes from playback, which the candidate cut short
    yes = turn("Sí, está todo bien.", "in-2").model_copy(update={"channel": "voice"})
    said = [e async for e in h.runtime.run_turn(yes)]
    assert [e.text for e in said if isinstance(e, AssistantText)] == [
        "Perdona, me has contestado antes de acabar.",
        "¿Lo repasamos por partes o seguimos?",
    ]
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    assert state.pending_confirmation.status == "pending"
    carry_on = turn("Sigue.", "in-3").model_copy(update={"channel": "voice"})
    async for _ in h.runtime.run_turn(carry_on):
        pass
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"
    assert assurance(state.pending_confirmation) == "waived"


async def test_ki06_a_day_and_a_time_end_in_a_booking_without_the_model_copying_an_id() -> None:
    """Live: after "el viernes", "el viernes", "exacto, sí" and "el viernes, veintitrés, a las
    diez y media" the model re-listed the slots, asked in plain text, reserved with nothing
    pending and presented an id that does not exist (seq 172 to 183). Here the model never
    presents a slot; the runtime turns the words into the read-back, and the yes into the
    booking (D41)."""
    ask = "¿Cuál te viene mejor?"
    h = with_slots_offered(
        says(ask), says(ask), says(ask), says(""), says("Reservado."), date_preference="2026-10-23"
    )
    await slots_offered(h)
    for n, words in enumerate(
        [
            "El viernes.",
            "El viernes.",
            "Exacto, sí.",
            "El viernes, veintitrés, a las diez y media.",
            "Sí.",
        ],
        start=2,
    ):
        await h.run(words, f"in-{n}")
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.booking is not None
    assert state.booking.slot_id == FRI_1030


async def test_ki07_an_answer_cut_by_a_pause_reaches_the_model_whole() -> None:
    """Live: "El lunes," (seq 53) and "uno, de, dos de noviembre." (54) became two turns 4 s
    apart; the second cancelled the first before Ana said anything, and the model only ever
    read the second half as the answer."""
    time = FakeTime()
    runtime = FakeRuntime(
        [[say("¿Y qué día?"), finished()], [say("Perfecto."), finished()]],
        slow=True,
        sleep=time.sleep,
    )
    recorder = Recorder()
    s = session(runtime, recorder, time=time)
    await s.transcript("El lunes,")
    await s.interrupted()  # the candidate goes on before any of Ana's answer was said
    await s.transcript("uno, de, dos de noviembre.")
    await time.advance(1)
    await s.wait()
    assert runtime.turns[-1].text == "El lunes, uno, de, dos de noviembre."
    await s.close()


def repeats_its_save(
    messages: tuple[ModelMessage, ...], tools: tuple[ToolSchema, ...]
) -> list[ModelEvent]:
    """gpt-4o-mini in the hosted call: it saves the name again while it may, and answers in
    words once ``update_candidate`` is no longer offered."""
    if any(tool.name == "update_candidate" for tool in tools):
        return [name_call(f"c{len(messages)}"), WANTS_TOOLS]
    return [ModelText(text="¿Tienes permiso de trabajo?"), STOP]


async def test_ki08_a_save_that_changed_nothing_is_not_repeated_before_ana_speaks() -> None:
    """Live: ``update_candidate`` came back ``unchanged`` two or three times in one turn (seq
    39, 47, 49) before the first sentence; each round cost 0.6 to 0.9 s."""
    model = FakeModel([], policy=repeats_its_save)
    h = Harness([], model=model)
    await h.open_session()
    events = await h.run("Soy Lucía.")
    assert not any(isinstance(e, TurnFailed) for e in events)
    assert [e.text for e in events if isinstance(e, AssistantText)] == [
        "¿Tienes permiso de trabajo?"
    ]
    assert len(model.calls) == 3  # the save, its unchanged repeat, the answer


async def test_ki08_a_confirm_in_the_turn_of_the_read_back_ends_the_turn() -> None:
    """Live: ``confirm_field`` in the very turn that read the date back (``same_turn``, seq
    62). The read-back already asked its question, so nothing more can be said: the round
    after the refusal is pure latency."""
    confirm = ToolCall(
        call_id="c2", name="confirm_field", arguments_json=json.dumps({"answer": "affirm"})
    )
    h = Harness([[DATE_CALL, WANTS_TOOLS], [confirm, WANTS_TOOLS], says("")])
    await h.open_session()
    await h.run("El 2 de noviembre")
    assert len(h.model.calls) == 2
