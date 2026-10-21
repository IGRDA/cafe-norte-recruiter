"""The store contract: every implementation of ``Store`` passes these, through the ``store``
fixture of ``conftest.py``. Only port methods are used; nothing implementation-specific."""

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
from cafe_norte.observability.contracts import StageTiming, UsageRecord, VersionStamp
from cafe_norte.persistence.contracts import EventRecord, Store, TurnRecord

NOW = datetime(2026, 10, 20, tzinfo=UTC)
SID = SessionId("s1")
VERSIONS = VersionStamp(
    config_id="c",
    config_version="1",
    kb_version="kb1",
    prompt_version="p",
    schema_version="1",
    model_id="fake",
    voice_id="",
    commit_sha="local",
)


def state(revision: int = 0, session_id: SessionId = SID) -> SessionState:
    return SessionState(
        session_id=session_id,
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


async def created(store: Store) -> Store:
    await store.sessions.create(state(), access_hash="")
    return store


# ---- transactions and sessions -------------------------------------------------------------------


async def test_writes_are_invisible_until_commit_and_dropped_on_rollback(store: Store) -> None:
    await created(store)
    async with store.transaction() as tx:
        await store.turns.append(tx, turn("a"))
        assert await store.turns.recent(SID, 10) == ()
        await tx.rollback()
    assert await store.turns.recent(SID, 10) == ()
    async with store.transaction() as tx:
        await store.turns.append(tx, turn("a"))
    assert [t.input_id for t in await store.turns.recent(SID, 10)] == ["a"]


async def test_an_exception_inside_the_transaction_rolls_back(store: Store) -> None:
    await created(store)
    with pytest.raises(RuntimeError):
        async with store.transaction() as tx:
            await store.turns.append(tx, turn("a"))
            raise RuntimeError("boom")
    assert await store.turns.recent(SID, 10) == ()


async def test_a_session_is_created_once(store: Store) -> None:
    await created(store)
    with pytest.raises(ServiceError) as twice:
        await store.sessions.create(state(), access_hash="")
    assert twice.value.code == "conflict"
    assert await store.sessions.get(SessionId("unknown")) is None


async def test_save_is_conditional_on_the_revision_the_writer_saw(store: Store) -> None:
    await created(store)
    async with store.transaction() as tx:
        await store.sessions.save(tx, state(1), expected_revision=0)
    with pytest.raises(ServiceError) as stale:
        async with store.transaction() as tx:
            await store.sessions.save(tx, state(2), expected_revision=0)
    assert stale.value.code == "conflict"
    current = await store.sessions.get(SID)
    assert current is not None and current.candidate.revision == 1


async def test_saving_an_unknown_session_is_not_found(store: Store) -> None:
    with pytest.raises(ServiceError) as missing:
        async with store.transaction() as tx:
            await store.sessions.save(tx, state(), expected_revision=0)
    assert missing.value.code == "not_found"


async def test_the_state_round_trips_whole(store: Store) -> None:
    full = state().model_copy(update={"lifecycle": "completed", "outcome": "brief_only"})
    await store.sessions.create(full, access_hash="h")
    assert await store.sessions.get(SID) == full


# ---- turns ---------------------------------------------------------------------------------------


async def test_duplicate_input_ids_conflict_per_role(store: Store) -> None:
    await created(store)
    async with store.transaction() as tx:
        await store.turns.append(tx, turn("a"))
        await store.turns.append(tx, turn("a", role="assistant"))
    with pytest.raises(ServiceError) as duplicate:
        async with store.transaction() as tx:
            await store.turns.append(tx, turn("a"))
    assert duplicate.value.code == "conflict"


async def test_recent_returns_the_last_n_in_order(store: Store) -> None:
    await created(store)
    async with store.transaction() as tx:
        for i in range(5):
            await store.turns.append(tx, turn(str(i)))
    assert [t.input_id for t in await store.turns.recent(SID, 2)] == ["3", "4"]
    assert await store.turns.recent(SID, 0) == ()


async def test_mark_delivered_touches_only_the_assistant_record(store: Store) -> None:
    await created(store)
    async with store.transaction() as tx:
        await store.turns.append(tx, turn("a"))
        await store.turns.append(tx, turn("a", role="assistant"))
    async with store.transaction() as tx:
        await store.turns.mark_delivered(
            tx, SID, TurnId("t-a"), delivered_text="ho", interrupted=True
        )
    user, assistant = await store.turns.recent(SID, 2)
    assert (user.delivered_text, user.interrupted) == (None, False)
    assert (assistant.delivered_text, assistant.interrupted) == ("ho", True)


# ---- events --------------------------------------------------------------------------------------


async def test_since_replays_then_delivers_live_events(store: Store) -> None:
    await created(store)
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
    await asyncio.wait_for(listener, 2)
    assert received == [2, 3]


async def test_a_duplicate_sequence_number_conflicts(store: Store) -> None:
    await created(store)
    async with store.transaction() as tx:
        await store.events.append(tx, event(1))
    with pytest.raises(ServiceError) as duplicate:
        async with store.transaction() as tx:
            await store.events.append(tx, event(1))
    assert duplicate.value.code == "conflict"


# ---- snapshot ------------------------------------------------------------------------------------


async def test_snapshot_is_none_for_an_unknown_session(store: Store) -> None:
    assert await store.snapshot(SID, versions=VERSIONS, taken_at=NOW) is None


async def test_snapshot_holds_turns_events_usage_and_timings_of_this_session_only(
    store: Store,
) -> None:
    await created(store)
    other = SessionId("s2")
    await store.sessions.create(state(session_id=other), access_hash="")
    usage = UsageRecord(
        session_id=SID,
        turn_id=None,
        kind="llm_tokens",
        quantity=12,
        unit_detail="in",
        estimated=False,
    )
    timing = StageTiming(
        session_id=SID,
        turn_id=TurnId("t-a"),
        stage="llm_total",
        milliseconds=5,
        source="server",
    )
    async with store.transaction() as tx:
        await store.turns.append(tx, turn("a"))
        await store.events.append(tx, event(1))
        await store.events.append(tx, event(2))
        await store.events.record_usage(tx, usage)
        await store.events.record_timing(tx, timing)
        await store.events.append(tx, event(1).model_copy(update={"session_id": other}))
    snapshot = await store.snapshot(SID, versions=VERSIONS, taken_at=NOW)
    assert snapshot is not None
    assert snapshot.state == state()
    assert [t.input_id for t in snapshot.turns] == ["a"]
    assert [e.seq for e in snapshot.events] == [1, 2]
    assert snapshot.usage == (usage,)
    assert snapshot.timings == (timing,)
    assert snapshot.confirmations == ()
    assert (snapshot.versions, snapshot.taken_at) == (VERSIONS, NOW)


async def test_check_ready(store: Store) -> None:
    assert await store.check_ready()


# ---- the event sequence --------------------------------------------------------------------------


async def test_next_seq_counts_from_one_per_session_inside_a_transaction(store: Store) -> None:
    await created(store)
    await store.sessions.create(state(session_id=SessionId("s2")), access_hash="")
    async with store.transaction() as tx:
        first = await store.sessions.next_seq(tx, SID)
        second = await store.sessions.next_seq(tx, SID)
        other = await store.sessions.next_seq(tx, SessionId("s2"))
        await store.events.append(tx, event(first))
        await store.events.append(tx, event(second))
    assert (first, second, other) == (1, 2, 1)
    async with store.transaction() as tx:
        assert await store.sessions.next_seq(tx, SID) == 3


async def test_next_seq_for_an_unknown_session_is_not_found(store: Store) -> None:
    with pytest.raises(ServiceError) as missing:
        async with store.transaction() as tx:
            await store.sessions.next_seq(tx, SessionId("nope"))
    assert missing.value.code == "not_found"


async def test_open_and_close_are_idempotent(store: Store) -> None:
    await store.open()
    await store.open()
    assert await store.check_ready()
    await store.close()


# ---- leases --------------------------------------------------------------------------------------


async def test_a_lease_is_held_by_one_owner_until_it_expires_or_is_released(store: Store) -> None:
    await created(store)
    first = await store.leases.claim(SID, "a", ttl_seconds=60)
    assert first is not None and (first.owner, first.generation) == ("a", 1)
    assert await store.leases.claim(SID, "b", ttl_seconds=60) is None  # live, someone else's
    again = await store.leases.claim(SID, "a", ttl_seconds=60)  # the owner may claim again
    assert again is not None and again.generation == 2
    await store.leases.release(again)
    taken = await store.leases.claim(SID, "b", ttl_seconds=60)
    assert taken is not None and (taken.owner, taken.generation) == ("b", 3)


async def test_an_expired_lease_can_be_claimed_by_another_owner(store: Store) -> None:
    await created(store)
    short = await store.leases.claim(SID, "a", ttl_seconds=0)
    assert short is not None
    await asyncio.sleep(0.01)
    other = await store.leases.claim(SID, "b", ttl_seconds=60)
    assert other is not None and other.owner == "b" and other.generation == 2
    assert await store.leases.renew(short, ttl_seconds=60) is None  # superseded
    renewed = await store.leases.renew(other, ttl_seconds=60)
    assert (
        renewed is not None and renewed.generation == 2 and renewed.expires_at >= other.expires_at
    )


async def test_a_lease_needs_a_session_and_release_of_a_stale_lease_is_harmless(
    store: Store,
) -> None:
    assert await store.leases.claim(SessionId("nope"), "a", ttl_seconds=60) is None
    await created(store)
    mine = await store.leases.claim(SID, "a", ttl_seconds=60)
    assert mine is not None
    theirs = mine.model_copy(update={"generation": mine.generation + 5})
    await store.leases.release(theirs)  # not the current lease: nothing happens
    assert await store.leases.claim(SID, "b", ttl_seconds=60) is None


# ---- fenced writes -------------------------------------------------------------------------------


async def test_a_write_fenced_on_a_stale_lease_generation_is_a_conflict(store: Store) -> None:
    await created(store)
    mine = await store.leases.claim(SID, "a", ttl_seconds=60)
    assert mine is not None
    async with store.transaction() as tx:
        await store.sessions.save(
            tx, state(1), expected_revision=0, lease_generation=mine.generation
        )
        assert await store.sessions.next_seq(tx, SID, lease_generation=mine.generation) == 1
    await store.leases.release(mine)
    theirs = await store.leases.claim(SID, "b", ttl_seconds=60)
    assert theirs is not None
    with pytest.raises(ServiceError) as stale_save:
        async with store.transaction() as tx:
            await store.sessions.save(
                tx, state(2), expected_revision=1, lease_generation=mine.generation
            )
    assert stale_save.value.code == "conflict"
    with pytest.raises(ServiceError) as stale_seq:
        async with store.transaction() as tx:
            await store.sessions.next_seq(tx, SID, lease_generation=mine.generation)
    assert stale_seq.value.code == "conflict"
    current = await store.sessions.get(SID)
    assert current is not None and current.candidate.revision == 1
    async with store.transaction() as tx:  # unfenced writes still work
        await store.sessions.save(tx, state(2), expected_revision=1)
