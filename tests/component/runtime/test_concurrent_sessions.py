"""Three conversations at once through one runtime and one store, as on the hosted VM: they
overlap instead of queueing, and nothing of one reaches another (its words, its record, its
event sequence). Run on the memory store and, with `make test-db`, on Postgres."""

import asyncio
import time
from collections.abc import Sequence

from cafe_norte.conversation.contracts import AssistantText, TurnFinished, TurnInput
from cafe_norte.conversation.runtime import Runtime
from cafe_norte.domain.contracts import InputId, SessionId
from cafe_norte.model.contracts import ModelEvent, ModelMessage, ModelText, ToolSchema
from cafe_norte.model.fake import FakeModel
from cafe_norte.persistence.contracts import Store
from tests.support.app import build_runtime
from tests.support.builders import NOW, STAMP, session_state
from tests.support.harness import STOP

SESSIONS = 3
TURNS = 3
MODEL_SECONDS = 0.3  # each model call, so a conversation takes seconds, not microseconds


def echo(messages: tuple[ModelMessage, ...], _: tuple[ToolSchema, ...]) -> Sequence[ModelEvent]:
    """Ana repeats the candidate's last words: a reply built from another session's context
    would show up as someone else's words."""
    said = next(m.content for m in reversed(messages) if m.role == "user")
    return [ModelText(text=f"Recibido: {said}."), STOP]


async def converse(runtime: Runtime, session_id: SessionId) -> list[str]:
    """Open the session, then TURNS turns one after the other; Ana's words per turn."""
    async for _ in runtime.open_session(session_id):
        pass
    replies: list[str] = []
    for n in range(TURNS):
        turn = TurnInput(
            session_id=session_id,
            input_id=InputId(f"{session_id}-{n}"),
            text=f"{session_id} mensaje {n}",
            channel="text",
            received_at=NOW,
        )
        events = [e async for e in runtime.run_turn(turn)]
        assert isinstance(events[-1], TurnFinished), events[-1]
        replies.append(" ".join(e.text for e in events if isinstance(e, AssistantText)))
    return replies


async def test_three_conversations_overlap_and_stay_apart(store: Store) -> None:
    model = FakeModel([], policy=echo, delay_seconds=MODEL_SECONDS)
    runtime = build_runtime(model=model, store=store, clock=lambda: NOW)
    ids = [SessionId(f"s{i}") for i in range(SESSIONS)]
    for session_id in [SessionId("solo"), *ids]:
        await store.sessions.create(session_state(session_id), access_hash="")

    started = time.monotonic()
    await converse(runtime, SessionId("solo"))
    alone = time.monotonic() - started
    started = time.monotonic()
    replies = await asyncio.gather(*(converse(runtime, s) for s in ids))
    together = time.monotonic() - started

    # Queued, three would take three times one; overlapping, about one.
    assert together < 2 * alone, f"{together:.2f} s for three, {alone:.2f} s for one: queued"
    for session_id, said in zip(ids, replies, strict=True):
        assert said == [f"Recibido: {session_id} mensaje {n}." for n in range(TURNS)]
        snapshot = await store.snapshot(session_id, versions=STAMP, taken_at=NOW)
        assert snapshot is not None
        users = [t.text for t in snapshot.turns if t.role == "user"]
        assert users == [f"{session_id} mensaje {n}" for n in range(TURNS)]
        seqs = [e.seq for e in snapshot.events]
        assert seqs == sorted(set(seqs)), "one session's sequence is gap-free and its own"
