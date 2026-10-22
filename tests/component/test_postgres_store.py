"""What the contract cannot say about the Postgres store: migrations on open, readiness, and
the database's own timeouts surfacing as stable error codes."""

import asyncio
from datetime import UTC, datetime

import psycopg
import pytest

from cafe_norte.domain.contracts import ConfigId, SessionId, SessionState
from cafe_norte.errors import ServiceError
from cafe_norte.persistence.postgres import PostgresStore
from cafe_norte.persistence.postgres.support import connection

pytestmark = pytest.mark.postgres

STATE = SessionState(
    session_id=SessionId("s1"),
    config_id=ConfigId("c"),
    config_version="1",
    language="es",
    channel="text",
    created_at=datetime(2026, 10, 20, tzinfo=UTC),
)


async def test_open_applies_the_migrations_once_and_is_idempotent(empty_database: str) -> None:
    store = PostgresStore(empty_database)
    await store.open()
    await store.open()
    assert await store.check_ready()
    await store.close()
    async with await psycopg.AsyncConnection.connect(empty_database) as conn:
        rows = await (await conn.execute("select name from schema_migrations")).fetchall()
    assert [row[0] for row in rows] == [
        "0001_initial.sql",
        "0002_leases_admission_resume.sql",
        "0003_exports_and_cascades.sql",
        "0004_admission_owner.sql",
    ]


async def test_check_ready_is_false_when_the_database_is_unreachable() -> None:
    store = PostgresStore("postgresql://cafe:cafe@127.0.0.1:1/nowhere", checkout_seconds=0.5)
    assert not await store.check_ready()


async def test_a_statement_timeout_is_a_timeout(empty_database: str) -> None:
    store = PostgresStore(empty_database, statement_seconds=0.2)
    await store.open()
    with pytest.raises(ServiceError) as slow:
        async with store.transaction() as tx:
            await connection(tx).execute("select pg_sleep(2)")
    assert slow.value.code == "timeout"
    await store.close()


async def test_a_lock_wait_longer_than_the_lock_timeout_is_a_timeout(empty_database: str) -> None:
    store = PostgresStore(empty_database, lock_seconds=0.2)
    await store.open()
    await store.sessions.create(STATE, access_hash="")
    lock = "select 1 from sessions where session_id = 's1' for update"
    with pytest.raises(ServiceError) as waited:
        async with store.transaction() as holder:
            await connection(holder).execute(lock)
            async with store.transaction() as waiter:
                await connection(waiter).execute(lock)
    assert waited.value.code == "timeout"
    await store.close()


async def test_pool_exhaustion_is_busy(empty_database: str) -> None:
    store = PostgresStore(empty_database, pool_size=1, checkout_seconds=0.2)
    await store.open()

    async def hold() -> None:
        async with store.transaction():
            await asyncio.sleep(0.6)

    holder = asyncio.create_task(hold())
    await asyncio.sleep(0.1)
    with pytest.raises(ServiceError) as full:
        async with store.transaction():
            pass
    assert full.value.code == "busy"
    await holder
    await store.close()


async def test_an_admission_older_than_its_ttl_no_longer_counts(empty_database: str) -> None:
    """A crashed container never releases its place; the row ages out instead."""
    store = PostgresStore(empty_database, admission_ttl_seconds=0)
    await store.open()
    for session_id in ("s1", "s2"):
        await store.sessions.create(
            STATE.model_copy(update={"session_id": SessionId(session_id)}), access_hash=""
        )
    assert await store.admission.acquire(SessionId("s1"), max_active=1, reserve_eur=0.5)
    await asyncio.sleep(0.01)
    assert await store.admission.acquire(SessionId("s2"), max_active=1, reserve_eur=0.5)
    await store.close()


async def test_a_restart_releases_only_its_own_instances_places(empty_database: str) -> None:
    """Rows carry the instance that acquired them: another container's live calls keep their
    places when this one restarts."""
    here = PostgresStore(empty_database, instance="vm-a")
    there = PostgresStore(empty_database, instance="vm-b")
    await here.open()
    await there.open()
    for session_id in ("s1", "s2"):
        await here.sessions.create(
            STATE.model_copy(update={"session_id": SessionId(session_id)}), access_hash=""
        )
    assert await here.admission.acquire(SessionId("s1"), max_active=2, reserve_eur=0.5)
    assert await there.admission.acquire(SessionId("s2"), max_active=2, reserve_eur=0.5)

    assert await here.admission.release_left_over() == 1

    assert not await there.admission.acquire(SessionId("s1"), max_active=1, reserve_eur=0.5)
    await here.close()
    await there.close()
