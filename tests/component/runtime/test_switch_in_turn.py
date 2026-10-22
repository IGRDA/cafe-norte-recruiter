"""A language switch the analyzer reads in time is applied in the same turn (D53): the round is
dropped before Ana says anything, the language is saved and announced, and Ana answers again in
the new language. A verdict that comes too late keeps D52's switch at the next turn."""

from cafe_norte.conversation import prompts
from cafe_norte.conversation.contracts import (
    AssistantText,
    StateUpdated,
    ToolStarted,
    TurnStarted,
)
from cafe_norte.conversation.runtime import Limits
from tests.support.builders import SESSION
from tests.support.harness import WANTS_TOOLS, Harness, decision_analyzer, name_call, says


async def test_a_switch_read_before_the_first_sentence_answers_in_the_new_language() -> None:
    h = Harness(
        [says("Claro, seguimos."), says("Sure, let's go on in English.")],
        signals=decision_analyzer(0.95),
    )
    await h.open_session()

    events = await h.run("Perdona, no hablo bien español, soy de Londres.")

    said = [e.text for e in events if isinstance(e, AssistantText)]
    assert said == ["Sure, let's go on in English."]
    started = next(e for e in events if isinstance(e, TurnStarted))
    assert started.language == "es"  # the turn opened before the verdict
    switched = next(e for e in events if isinstance(e, StateUpdated))
    assert switched.language == "en"
    assert events.index(switched) < next(
        i for i, e in enumerate(events) if isinstance(e, AssistantText)
    )
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.language == "en"
    system = h.model.calls[1][0].content
    assert system.rstrip().endswith(prompts.language_line("en"))


async def test_tool_calls_of_the_dropped_round_are_not_executed() -> None:
    h = Harness(
        [[name_call(), WANTS_TOOLS], says("Nice to meet you.")],
        signals=decision_analyzer(0.95),
    )
    await h.open_session()

    events = await h.run("Me llamo Lucía, pero no hablo bien español.")

    assert not any(isinstance(e, ToolStarted) for e in events)
    assert [e.text for e in events if isinstance(e, AssistantText)] == ["Nice to meet you."]


async def test_a_verdict_later_than_the_wait_keeps_the_switch_for_the_next_turn() -> None:
    h = Harness(
        [says("Claro, seguimos."), says("Great.")],
        signals=decision_analyzer(0.95, 0.0, delay=0.2),
        limits=Limits(switch_wait_seconds=0.01),
    )
    await h.open_session()

    first = await h.run("Perdona, no hablo bien español.", "in-1")
    await h.runtime.settle()
    second = await h.run("Monday to Friday.", "in-2")

    assert [e.text for e in first if isinstance(e, AssistantText)] == ["Claro, seguimos."]
    assert next(e for e in second if isinstance(e, TurnStarted)).language == "en"


async def test_no_switch_means_no_second_round() -> None:
    h = Harness([says("Vale, apuntado.")], signals=decision_analyzer(0.1))
    await h.open_session()

    events = await h.run("De lunes a viernes.")

    assert [e.text for e in events if isinstance(e, AssistantText)] == ["Vale, apuntado."]
    assert len(h.model.calls) == 1
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.language == "es"


async def test_an_explicit_request_switches_without_waiting_for_the_analyzer() -> None:
    h = Harness([says("Sure.")], signals=decision_analyzer(0.0))
    await h.open_session()

    events = await h.run("In English, please.")

    assert next(e for e in events if isinstance(e, TurnStarted)).language == "en"
    assert len(h.model.calls) == 1


async def test_once_ana_has_spoken_the_turn_is_not_restarted() -> None:
    h = Harness([says("Claro."), says("Okay.")], signals=decision_analyzer(0.95, 0.0))
    await h.open_session()

    first = await h.run("Quiero hablar con una persona, no hablo bien español.", "in-1")
    await h.runtime.settle()
    second = await h.run("Thanks.", "in-2")

    said = [e.text for e in first if isinstance(e, AssistantText)]
    assert said[0] in prompts.load("controls", "es")  # the fixed reply, said before the model
    assert len(h.model.calls) == 2  # one round each turn: the first was not restarted
    assert next(e for e in second if isinstance(e, TurnStarted)).language == "en"


async def test_frustration_read_before_the_first_sentence_reaches_this_turn() -> None:
    """Ignacio's call: "estoy bastante mosqueado… no me ha gustado nada tu servicio" got the
    next field question. The analyzer's verdict, read where D53 reads the language, now
    reaches the turn it is about: the round is dropped and answered again with it (D58)."""
    h = Harness(
        [says("¿Qué turno prefieres?"), says("Siento que te haya molestado.")],
        signals=decision_analyzer(0.0, sentiment="frustrated"),
    )
    await h.open_session()

    events = await h.run("Estoy bastante mosqueado, no me ha gustado nada tu servicio.")

    assert [e.text for e in events if isinstance(e, AssistantText)] == [
        "Siento que te haya molestado."
    ]
    assert '"candidate_sentiment": null' in h.model.calls[0][0].content
    assert '"candidate_sentiment": "frustrated"' in h.model.calls[1][0].content


async def test_a_neutral_verdict_answers_once() -> None:
    h = Harness([says("Vale.")], signals=decision_analyzer(0.0, sentiment="neutral"))
    await h.open_session()
    await h.run("De lunes a viernes.")
    assert len(h.model.calls) == 1
