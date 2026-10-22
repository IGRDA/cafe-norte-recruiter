"""Leases (one worker owns a session, a stale one cannot write) and resuming a session."""

from cafe_norte.conversation import prompts
from cafe_norte.conversation.contracts import (
    AssistantText,
    TurnFailed,
)
from tests.support.builders import SESSION
from tests.support.harness import (
    WANTS_TOOLS,
    Harness,
    fill_record,
    name_call,
    present_brief,
    says,
    turn,
)


async def test_a_turn_holds_the_session_lease_and_releases_it_at_the_end() -> None:
    h = Harness([says("Hola.")])
    await h.open_session()
    seen: list[bool] = []
    async for event in h.runtime.run_turn(turn("Hola")):
        if isinstance(event, AssistantText):
            seen.append(await h.store.leases.claim(SESSION, "intruder", ttl_seconds=60) is None)
    assert seen == [True]  # nobody else could claim it during the turn
    assert await h.store.leases.claim(SESSION, "intruder", ttl_seconds=60) is not None


async def test_a_turn_fails_with_conflict_while_another_owner_holds_the_lease() -> None:
    h = Harness([says("Hola.")])
    await h.open_session()
    other = await h.store.leases.claim(SESSION, "other-container", ttl_seconds=60)
    assert other is not None
    events = await h.run("Hola")
    assert isinstance(events[-1], TurnFailed) and events[-1].code == "conflict"
    user_turns = [t for t in await h.store.turns.recent(SESSION, 10) if t.role == "user"]
    assert user_turns == []  # nothing of the turn was written


async def test_tools_run_under_the_turns_lease_generation() -> None:
    h = Harness([[name_call(), WANTS_TOOLS], says("Hola.")])
    await h.open_session()
    await h.run("Soy Lucía")
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.candidate.revision == 1
    # The handler saved under the lease: a later claim is generation 2, the save used 1.
    lease = await h.store.leases.claim(SESSION, "test", ttl_seconds=60)
    assert lease is not None and lease.generation == 2


async def test_resume_says_the_fixed_sentence_and_repeats_a_pending_read_back() -> None:
    h = Harness([[present_brief(), WANTS_TOOLS], says("")])
    await h.open_session()
    await fill_record(h)
    await h.run("ya está todo", "in-1")
    before = await h.store.sessions.get(SESSION)
    assert before is not None and before.pending_confirmation is not None
    events = [e async for e in h.runtime.resume_session(SESSION)]
    assert [type(e).__name__ for e in events] == [
        "TurnStarted",
        "AssistantText",
        "AssistantText",
        "TurnFinished",
    ]
    assert isinstance(events[1], AssistantText)
    assert events[1].text == prompts.load("resume", "es").strip()
    assert isinstance(events[2], AssistantText)
    assert events[2].text == before.pending_confirmation.presentation_text
    after = await h.store.sessions.get(SESSION)
    assert after == before  # nothing changed, nothing rebooked
    journaled = await h.store.turns.recent(SESSION, 1)
    assert journaled[0].role == "assistant" and journaled[0].text.startswith("Hola de nuevo")


async def test_resume_reactivates_a_paused_session_in_its_language() -> None:
    h = Harness([])
    await h.open_session("en")
    await h.runtime.end(SESSION, "shutdown")  # pause
    paused = await h.store.sessions.get(SESSION)
    assert paused is not None and paused.lifecycle == "paused"
    events = [e async for e in h.runtime.resume_session(SESSION)]
    assert isinstance(events[1], AssistantText) and events[1].text.startswith("Hello again")
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.lifecycle == "active"


async def test_resume_of_an_ended_or_unknown_session_fails_without_speaking() -> None:
    h = Harness([])
    assert [type(e).__name__ for e in [e async for e in h.runtime.resume_session(SESSION)]] == [
        "TurnFailed"
    ]
    await h.open_session()
    await h.runtime.end(SESSION, "stop")
    events = [e async for e in h.runtime.resume_session(SESSION)]
    assert isinstance(events[0], TurnFailed) and events[0].code == "session_ended"
