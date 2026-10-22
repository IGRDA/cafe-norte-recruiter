"""The store contract: every implementation of ``Store`` passes these, through the ``store``
fixture of ``conftest.py``. Only port methods are used; nothing implementation-specific."""

import asyncio
import json
from datetime import timedelta

import pytest

from cafe_norte.domain.contracts import (
    ConfigId,
    Confirmation,
    ConfirmationId,
    InputId,
    InterviewSlot,
    SessionId,
    SlotId,
    SlotTarget,
    TurnId,
)
from cafe_norte.errors import ServiceError
from cafe_norte.observability.contracts import StageTiming, UsageRecord
from cafe_norte.persistence.contracts import EventRecord, Store, TurnRecord
from tests.support.builders import NOW, STAMP, session_state

SID = SessionId("s1")


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
    await store.sessions.create(session_state(), access_hash="")
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
        await store.sessions.create(session_state(), access_hash="")
    assert twice.value.code == "conflict"
    assert await store.sessions.get(SessionId("unknown")) is None


async def test_save_is_conditional_on_the_revision_the_writer_saw(store: Store) -> None:
    await created(store)
    async with store.transaction() as tx:
        await store.sessions.save(tx, session_state(revision=1), expected_revision=0)
    with pytest.raises(ServiceError) as stale:
        async with store.transaction() as tx:
            await store.sessions.save(tx, session_state(revision=2), expected_revision=0)
    assert stale.value.code == "conflict"
    current = await store.sessions.get(SID)
    assert current is not None and current.candidate.revision == 1


async def test_saving_an_unknown_session_is_not_found(store: Store) -> None:
    with pytest.raises(ServiceError) as missing:
        async with store.transaction() as tx:
            await store.sessions.save(tx, session_state(), expected_revision=0)
    assert missing.value.code == "not_found"


async def test_the_state_round_trips_whole(store: Store) -> None:
    full = session_state().model_copy(update={"lifecycle": "completed", "outcome": "brief_only"})
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
    assert await store.snapshot(SID, versions=STAMP, taken_at=NOW) is None


async def test_snapshot_holds_turns_events_usage_and_timings_of_this_session_only(
    store: Store,
) -> None:
    await created(store)
    other = SessionId("s2")
    await store.sessions.create(session_state(other), access_hash="")
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
    snapshot = await store.snapshot(SID, versions=STAMP, taken_at=NOW)
    assert snapshot is not None
    assert snapshot.state == session_state()
    assert [t.input_id for t in snapshot.turns] == ["a"]
    assert [e.seq for e in snapshot.events] == [1, 2]
    assert snapshot.usage == (usage,)
    assert snapshot.timings == (timing,)
    assert snapshot.confirmations == ()
    assert (snapshot.versions, snapshot.taken_at) == (STAMP, NOW)


async def test_check_ready(store: Store) -> None:
    assert await store.check_ready()


# ---- the event sequence --------------------------------------------------------------------------


async def test_next_seq_counts_from_one_per_session_inside_a_transaction(store: Store) -> None:
    await created(store)
    await store.sessions.create(session_state(SessionId("s2")), access_hash="")
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
            tx, session_state(revision=1), expected_revision=0, lease_generation=mine.generation
        )
        assert await store.sessions.next_seq(tx, SID, lease_generation=mine.generation) == 1
    await store.leases.release(mine)
    theirs = await store.leases.claim(SID, "b", ttl_seconds=60)
    assert theirs is not None
    with pytest.raises(ServiceError) as stale_save:
        async with store.transaction() as tx:
            await store.sessions.save(
                tx, session_state(revision=2), expected_revision=1, lease_generation=mine.generation
            )
    assert stale_save.value.code == "conflict"
    with pytest.raises(ServiceError) as stale_seq:
        async with store.transaction() as tx:
            await store.sessions.next_seq(tx, SID, lease_generation=mine.generation)
    assert stale_seq.value.code == "conflict"
    current = await store.sessions.get(SID)
    assert current is not None and current.candidate.revision == 1
    async with store.transaction() as tx:  # unfenced writes still work
        await store.sessions.save(tx, session_state(revision=2), expected_revision=1)


# ---- admission -----------------------------------------------------------------------------------


async def test_at_most_max_active_voice_sessions_and_release_frees_a_place(store: Store) -> None:
    a, b, c = SessionId("a"), SessionId("b"), SessionId("c")
    for session_id in (a, b, c):
        await store.sessions.create(session_state(session_id), access_hash="")
    admission = store.admission
    assert await admission.acquire(a, max_active=2, reserve_eur=0.5)
    assert await admission.acquire(b, max_active=2, reserve_eur=0.5)
    assert not await admission.acquire(c, max_active=2, reserve_eur=0.5)
    assert await admission.acquire(a, max_active=2, reserve_eur=0.5)  # already in: idempotent
    await admission.release(a, actual_eur=0.3)
    assert await admission.acquire(c, max_active=2, reserve_eur=0.5)
    await admission.release(SessionId("never"), actual_eur=0.0)  # unknown: no error


async def test_places_held_before_a_restart_are_released_at_startup(store: Store) -> None:
    """A deploy resets the VM mid-call: the calls never release their places. The new process
    releases what this instance still held, so the next call is not refused as busy."""
    a, b, c = SessionId("a"), SessionId("b"), SessionId("c")
    for session_id in (a, b, c):
        await store.sessions.create(session_state(session_id), access_hash="")
    assert await store.admission.acquire(a, max_active=2, reserve_eur=0.5)
    assert await store.admission.acquire(b, max_active=2, reserve_eur=0.5)
    assert not await store.admission.acquire(c, max_active=2, reserve_eur=0.5)

    assert await store.admission.release_left_over() == 2

    assert await store.admission.acquire(c, max_active=2, reserve_eur=0.5)
    assert await store.admission.release_left_over() == 1
    assert await store.admission.release_left_over() == 0


async def test_concurrent_admissions_never_exceed_the_cap(store: Store) -> None:
    ids = [SessionId(f"s{i}") for i in range(6)]
    for session_id in ids:
        await store.sessions.create(session_state(session_id), access_hash="")
    results = await asyncio.gather(
        *(store.admission.acquire(s, max_active=2, reserve_eur=0.5) for s in ids)
    )
    assert sum(results) == 2


# ---- resume tokens -------------------------------------------------------------------------------


async def test_a_resume_token_opens_only_its_session_until_it_expires(store: Store) -> None:
    await created(store)
    await store.sessions.create(session_state(SessionId("s2")), access_hash="")
    later = NOW + timedelta(days=7)
    await store.resume_tokens.issue(SID, "hash-1", expires_at=later)
    await store.resume_tokens.issue(SessionId("s2"), "hash-2", expires_at=later)
    assert await store.resume_tokens.redeem("hash-1", now=NOW) == SID
    assert await store.resume_tokens.redeem("hash-1", now=NOW) == SID  # reusable until expiry
    assert await store.resume_tokens.redeem("hash-2", now=NOW) == SessionId("s2")
    assert await store.resume_tokens.redeem("hash-1", now=later) is None  # expired
    assert await store.resume_tokens.redeem("no-such-hash", now=NOW) is None


async def test_a_token_hash_is_issued_once(store: Store) -> None:
    await created(store)
    await store.resume_tokens.issue(SID, "hash-1", expires_at=NOW + timedelta(days=1))
    with pytest.raises(ServiceError) as twice:
        await store.resume_tokens.issue(SID, "hash-1", expires_at=NOW + timedelta(days=1))
    assert twice.value.code == "conflict"


# ---- exports and deletion ------------------------------------------------------------------------


async def test_the_export_snapshot_is_written_once_per_session_and_read_back(store: Store) -> None:
    await created(store)
    assert await store.exports.read_snapshot(SID) is None
    async with store.transaction() as tx:
        await store.exports.write_snapshot(tx, SID, '{"schema_version": "1", "n": 1}')
    async with store.transaction() as tx:  # a later close overwrites: one snapshot per session
        await store.exports.write_snapshot(tx, SID, '{"schema_version": "1", "n": 2}')
    stored = await store.exports.read_snapshot(SID)
    assert stored is not None and json.loads(stored) == {"schema_version": "1", "n": 2}


async def test_expired_lists_the_oldest_sessions_first_up_to_the_limit(store: Store) -> None:
    for session_id, age in (("old", 8), ("older", 9), ("new", 1)):
        await store.sessions.create(
            session_state(SessionId(session_id)).model_copy(
                update={"created_at": NOW - timedelta(days=age)}
            ),
            access_hash="",
        )
    assert await store.sessions.expired(NOW - timedelta(days=7), limit=10) == ("older", "old")
    assert await store.sessions.expired(NOW - timedelta(days=7), limit=1) == ("older",)
    assert await store.sessions.expired(NOW - timedelta(days=30), limit=10) == ()


async def test_delete_removes_the_session_and_everything_that_belongs_to_it(store: Store) -> None:
    await created(store)
    await store.calendar.seed(
        [
            InterviewSlot(
                slot_id=SlotId("x"), config_id=ConfigId("c"), starts_at_utc=NOW + timedelta(days=1)
            )
        ]
    )
    async with store.transaction() as tx:
        await store.turns.append(tx, turn("a"))
        await store.events.append(tx, event(1))
        await store.calendar.reserve(tx, SlotId("x"), SID, slot_confirmation(), "key")
        await store.exports.write_snapshot(tx, SID, "{}")
    await store.resume_tokens.issue(SID, "hash", expires_at=NOW + timedelta(days=1))
    await store.sessions.delete(SID)
    assert await store.sessions.get(SID) is None
    assert await store.turns.recent(SID, 10) == ()
    assert await store.snapshot(SID, versions=STAMP, taken_at=NOW) is None
    assert await store.exports.read_snapshot(SID) is None
    assert await store.resume_tokens.redeem("hash", now=NOW) is None
    assert await store.calendar.booking_by_key("key") is None
    free = await store.calendar.available(ConfigId("c"), after=NOW, limit=5)
    assert [s.slot_id for s in free] == ["x"]  # the simulated reservation went with it
    await store.sessions.delete(SID)  # unknown: no error


def slot_confirmation() -> Confirmation:
    return Confirmation(
        confirmation_id=ConfirmationId("c1"),
        target=SlotTarget(slot_id=SlotId("x"), brief_revision=0),
        presentation_text="¿Te la reservo?",
        presented_turn_id=TurnId("t1"),
        fully_delivered=True,
        status="confirmed",
    )


# ---- maintenance lock ----------------------------------------------------------------------------


async def test_the_maintenance_lock_is_held_by_one_holder_at_a_time(store: Store) -> None:
    async with store.maintenance() as first:
        assert first is True
        async with store.maintenance() as second:
            assert second is False
    async with store.maintenance() as again:
        assert again is True
