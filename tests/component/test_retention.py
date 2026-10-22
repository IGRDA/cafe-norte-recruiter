"""Retention purges only what is older than the window, a batch at a time, under the lock."""

import asyncio
from datetime import UTC, datetime, timedelta

from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.persistence.retention import purge_expired, purge_periodically
from tests.support.builders import session_state
from tests.support.time import FakeTime, settle

NOW = datetime(2026, 10, 20, tzinfo=UTC)


async def seeded() -> MemoryStore:
    store = MemoryStore()
    for session_id, age in (("a", 10), ("b", 8), ("c", 6), ("d", 0)):
        await store.sessions.create(
            session_state(SessionId(session_id)).model_copy(
                update={"created_at": NOW - timedelta(days=age)}
            ),
            access_hash="",
        )
    return store


async def test_purge_deletes_the_oldest_beyond_the_window_up_to_the_limit() -> None:
    store = await seeded()
    assert await purge_expired(store, now=NOW, days=7, limit=1) == ("a",)
    assert await purge_expired(store, now=NOW, days=7) == ("b",)
    assert await purge_expired(store, now=NOW, days=7) == ()
    assert await store.sessions.get(SessionId("c")) is not None


async def test_purge_does_nothing_while_another_container_holds_the_lock() -> None:
    store = await seeded()

    async with store.maintenance() as held:  # what another container holding it looks like
        assert held
        assert await purge_expired(store, now=NOW, days=7) == ()

    assert await store.sessions.get(SessionId("a")) is not None


async def test_the_periodic_purge_runs_at_once_and_survives_a_failure() -> None:
    store = await seeded()
    time = FakeTime()
    rounds: list[datetime] = []

    def clock() -> datetime:
        rounds.append(time.now())
        if len(rounds) == 1:
            raise RuntimeError("the database is restarting")
        return NOW

    task = asyncio.create_task(
        purge_periodically(store, days=7, interval_seconds=3600, clock=clock, sleep=time.sleep)
    )
    await settle()
    assert len(rounds) == 1  # at once, and it failed
    assert await store.sessions.get(SessionId("a")) is not None

    await time.advance(3600)

    assert len(rounds) == 2
    assert await store.sessions.get(SessionId("a")) is None
    assert await store.sessions.get(SessionId("c")) is not None
    task.cancel()
