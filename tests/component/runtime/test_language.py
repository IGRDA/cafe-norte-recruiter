"""The language of a turn: the session language, a switch, the language the model is told."""

from cafe_norte.conversation import prompts
from cafe_norte.conversation.contracts import (
    AssistantText,
    TurnStarted,
)
from tests.support.builders import SESSION
from tests.support.harness import (
    WANTS_TOOLS,
    Harness,
    fill_record,
    present_brief,
    says,
)


async def test_the_opening_is_in_the_session_language() -> None:
    h = Harness([])
    await h.open_session("en")
    opening = [e async for e in h.runtime.open_session(SESSION)]
    assert isinstance(opening[1], AssistantText)
    assert opening[1].text.startswith("Hi, I'm Ana, Café Norte's AI assistant.")


async def test_an_explicit_language_request_is_saved_before_the_model_answers_it() -> None:
    h = Harness([says("Sure.")])
    await h.open_session()
    events = await h.run("¿Podemos seguir en inglés, por favor?")
    started = events[0]
    assert isinstance(started, TurnStarted) and started.language == "en"
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.language == "en"
    user, assistant = await h.store.turns.recent(SESSION, 2)
    assert (user.language, assistant.language) == ("en", "en")
    system = h.model.calls[0][0].content
    assert '"language": "en"' in system
    assert system.endswith(prompts.load("language", "en").strip())  # the last word is English


async def test_a_borrowed_word_does_not_switch_the_language() -> None:
    h = Harness([says("Vale.")])
    await h.open_session()
    await h.run("He trabajado en Starbucks, en el turno de closing.")
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.language == "es"


async def test_a_pending_read_back_survives_a_language_switch() -> None:
    h = Harness([[present_brief(), WANTS_TOOLS], says("Sure, in English.")])
    await h.open_session()
    await fill_record(h)
    await h.run("ya está todo", "in-1")
    before = await h.store.sessions.get(SESSION)
    await h.run("English, please", "in-2")
    after = await h.store.sessions.get(SESSION)
    assert before is not None and after is not None
    assert after.language == "en"
    assert after.pending_confirmation == before.pending_confirmation
    assert after.candidate == before.candidate
