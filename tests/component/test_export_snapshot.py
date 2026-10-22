"""The memory store's snapshot holds the whole session, and its export leaks no secret."""

from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.export import build_export
from cafe_norte.persistence.memory import MemoryStore
from tests.support.builders import NOW, STAMP
from tests.support.exports import SID, journal, snapshot


async def test_memory_store_snapshot_reads_the_whole_session() -> None:
    store = MemoryStore()
    base = snapshot()
    await store.sessions.create(base.state, access_hash="secret")
    async with store.transaction() as tx:
        await store.turns.append(tx, base.turns[0])
        for event in journal():
            await store.events.append(tx, event)
        await store.events.record_usage(tx, base.usage[0])
        await store.events.record_usage(tx, base.usage[0].model_copy(update={"session_id": "x"}))
    taken = await store.snapshot(SID, versions=STAMP, taken_at=NOW)
    assert taken is not None
    assert taken.turns == base.turns and len(taken.events) == 6
    assert [c.status for c in taken.confirmations] == ["invalidated", "confirmed"]
    assert taken.usage == base.usage and taken.timings == ()
    assert "secret" not in build_export(taken).model_dump_json()
    assert await store.snapshot(SessionId("nope"), versions=STAMP, taken_at=NOW) is None
