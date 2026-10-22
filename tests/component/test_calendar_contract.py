"""The calendar contract: idempotent seeding, ordered availability, one booking per slot and
per session, the same key returning the same booking. Runs against every ``Store``."""

import asyncio
from datetime import timedelta

import pytest

from cafe_norte.domain.contracts import (
    CandidateRecord,
    ConfigId,
    Confirmation,
    ConfirmationId,
    InterviewSlot,
    SessionId,
    SessionState,
    SlotId,
    SlotTarget,
    TurnId,
)
from cafe_norte.errors import ServiceError
from cafe_norte.persistence.contracts import Store
from cafe_norte.persistence.seed import seed_calendar
from tests.support.builders import CONFIGS, NOW

CHAMBERI = ConfigId("chamberi_barista_v1")


def slot(n: int, config_id: ConfigId = CHAMBERI) -> InterviewSlot:
    return InterviewSlot(
        slot_id=SlotId(f"s{n}"), config_id=config_id, starts_at_utc=NOW + timedelta(hours=n)
    )


def confirmation(slot_id: str, cid: str = "c1") -> Confirmation:
    return Confirmation(
        confirmation_id=ConfirmationId(cid),
        target=SlotTarget(slot_id=SlotId(slot_id), brief_revision=1),
        presentation_text="¿Te la reservo?",
        presented_turn_id=TurnId("t1"),
        fully_delivered=True,
        status="confirmed",
    )


async def sessions(store: Store, *ids: str) -> None:
    for session_id in ids:
        await store.sessions.create(
            SessionState(
                session_id=SessionId(session_id),
                config_id=CHAMBERI,
                config_version="1",
                language="es",
                channel="text",
                created_at=NOW,
                candidate=CandidateRecord(),
            ),
            access_hash="",
        )


async def reserve(store: Store, slot_id: str, session: str, key: str) -> None:
    async with store.transaction() as tx:
        await store.calendar.reserve(
            tx, SlotId(slot_id), SessionId(session), confirmation(slot_id, key), key
        )


async def test_seed_inserts_missing_slots_and_never_touches_an_existing_one(store: Store) -> None:
    await sessions(store, "a")
    await store.calendar.seed([slot(1), slot(2)])
    await reserve(store, "s1", "a", "k1")
    await store.calendar.seed([slot(1), slot(2), slot(3)])
    taken = await store.calendar.get(SlotId("s1"))
    assert taken is not None and taken.status == "reserved"
    free = await store.calendar.available(CHAMBERI, after=NOW, limit=10)
    assert [s.slot_id for s in free] == ["s2", "s3"]


async def test_available_is_this_store_future_free_slots_in_order_up_to_the_limit(
    store: Store,
) -> None:
    other = ConfigId("arganzuela_barista_v1")
    await store.calendar.seed([slot(3), slot(1), slot(-1), slot(2, other), slot(5)])
    assert [s.slot_id for s in await store.calendar.available(CHAMBERI, after=NOW, limit=2)] == [
        "s1",
        "s3",
    ]
    assert await store.calendar.get(SlotId("nope")) is None
    assert await store.calendar.get(SlotId("s1")) == slot(1)


async def test_two_sessions_one_slot_exactly_one_succeeds_and_alternatives_remain(
    store: Store,
) -> None:
    await sessions(store, "a", "b")
    await store.calendar.seed([slot(1), slot(2)])
    await reserve(store, "s1", "a", "ka")
    with pytest.raises(ServiceError) as error:
        await reserve(store, "s1", "b", "kb")
    assert error.value.code == "conflict"
    assert [s.slot_id for s in await store.calendar.available(CHAMBERI, after=NOW, limit=5)] == [
        "s2"
    ]


async def test_two_concurrent_reservers_for_one_slot_exactly_one_wins(store: Store) -> None:
    await sessions(store, "a", "b")
    await store.calendar.seed([slot(1)])
    results = await asyncio.gather(
        reserve(store, "s1", "a", "ka"), reserve(store, "s1", "b", "kb"), return_exceptions=True
    )
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(failures) == 1
    assert isinstance(failures[0], ServiceError) and failures[0].code == "conflict"
    bookings = [await store.calendar.booking_by_key(k) for k in ("ka", "kb")]
    assert sum(b is not None for b in bookings) == 1
    assert await store.calendar.available(CHAMBERI, after=NOW, limit=5) == ()


async def test_the_same_key_returns_the_original_booking_and_a_session_books_once(
    store: Store,
) -> None:
    await sessions(store, "a")
    await store.calendar.seed([slot(1), slot(2)])
    await reserve(store, "s1", "a", "ka")
    original = await store.calendar.booking_by_key("ka")
    assert original is not None and original.slot_id == "s1"
    assert original.committed_at.tzinfo is not None
    async with store.transaction() as tx:
        again = await store.calendar.reserve(
            tx, SlotId("s1"), SessionId("a"), confirmation("s1"), "ka"
        )
    assert again == original
    with pytest.raises(ServiceError) as error:
        await reserve(store, "s2", "a", "k-second")
    assert error.value.code == "conflict"
    assert (await store.calendar.get(SlotId("s2"))) == slot(2)
    assert await store.calendar.booking_by_key("k-second") is None


async def test_seed_calendar_seeds_every_store_from_the_domain_rule(store: Store) -> None:
    await seed_calendar(store, CONFIGS, now=NOW)
    for config_id in CONFIGS:
        offered = await store.calendar.available(config_id, after=NOW, limit=3)
        assert len(offered) == 3 and all(s.config_id == config_id for s in offered)
    await seed_calendar(store, CONFIGS, now=NOW)  # a second seed changes nothing
    assert len(await store.calendar.available(CHAMBERI, after=NOW, limit=100)) == 13
