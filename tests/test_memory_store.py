"""Transaction and repository semantics of the in-memory store."""

import asyncio
from datetime import UTC, datetime

import pytest

from cafe_norte.domain.contracts import (
    CandidateRecord,
    ConfigId,
    InputId,
    SessionId,
    SessionState,
    TurnId,
)
from cafe_norte.errors import ServiceError
from cafe_norte.persistence.contracts import EventRecord, TurnRecord
from cafe_norte.persistence.memory import MemoryStore

NOW = datetime(2026, 10, 20, tzinfo=UTC)
SID = SessionId("s1")


def state(revision: int = 0) -> SessionState:
    return SessionState(
        session_id=SID,
        config_id=ConfigId("c"),
        config_version="1",
        language="es",
        channel="text",
        created_at=NOW,
        candidate=CandidateRecord(revision=revision),
    )


def turn(input_id: str, role: str = "user") -> TurnRecord:
    return TurnRecord(
        turn_id=TurnId("t-" + input_id),
        session_id=SID,
        input_id=InputId(input_id),
        role="user" if role == "user" else "assistant",
        channel="text",
        language="es",
        text="hola",
        started_at=NOW,
    )


def event(seq: int) -> EventRecord:
    return EventRecord(session_id=SID, turn_id=None, seq=seq, kind="x", payload_json="{}", at=NOW)


async def test_writes_are_invisible_until_commit_and_dropped_on_rollback() -> None:
    store = MemoryStore()
    await store.sessions.create(state(), access_hash="")
    async with store.transaction() as tx:
        await store.turns.append(tx, turn("a"))
        assert await store.turns.recent(SID, 10) == ()
        await tx.rollback()
    assert await store.turns.recent(SID, 10) == ()
    async with store.transaction() as tx:
        await store.turns.append(tx, turn("a"))
    assert [t.input_id for t in await store.turns.recent(SID, 10)] == ["a"]


async def test_an_exception_inside_the_transaction_rolls_back() -> None:
    store = MemoryStore()
    with pytest.raises(RuntimeError):
        async with store.transaction() as tx:
            await store.turns.append(tx, turn("a"))
            raise RuntimeError("boom")
    assert await store.turns.recent(SID, 10) == ()


async def test_save_is_conditional_on_the_revision_the_writer_saw() -> None:
    store = MemoryStore()
    await store.sessions.create(state(), access_hash="")
    async with store.transaction() as tx:
        await store.sessions.save(tx, state(1), expected_revision=0)
    with pytest.raises(ServiceError) as stale:
        async with store.transaction() as tx:
            await store.sessions.save(tx, state(2), expected_revision=0)
    assert stale.value.code == "conflict"
    current = await store.sessions.get(SID)
    assert current is not None and current.candidate.revision == 1


async def test_duplicate_input_ids_conflict_per_role() -> None:
    store = MemoryStore()
    async with store.transaction() as tx:
        await store.turns.append(tx, turn("a"))
        await store.turns.append(tx, turn("a", role="assistant"))
    with pytest.raises(ServiceError) as duplicate:
        async with store.transaction() as tx:
            await store.turns.append(tx, turn("a"))
    assert duplicate.value.code == "conflict"


async def test_recent_returns_the_last_n_in_order() -> None:
    store = MemoryStore()
    async with store.transaction() as tx:
        for i in range(5):
            await store.turns.append(tx, turn(str(i)))
    assert [t.input_id for t in await store.turns.recent(SID, 2)] == ["3", "4"]


async def test_since_replays_then_delivers_live_events() -> None:
    store = MemoryStore()
    async with store.transaction() as tx:
        await store.events.append(tx, event(1))
        await store.events.append(tx, event(2))
    received: list[int] = []

    async def listen() -> None:
        async for record in store.events.since(SID, 1):
            received.append(record.seq)
            if record.seq == 3:
                return

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0)
    async with store.transaction() as tx:
        await store.events.append(tx, event(3))
    await asyncio.wait_for(listener, 1)
    assert received == [2, 3]
    assert store.events.last_seq(SID) == 3
