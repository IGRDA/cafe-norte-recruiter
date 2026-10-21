"""The in-memory calendar: idempotent seeding, ordered availability, one booking per slot and
per session, the same key returning the same booking."""

from datetime import UTC, datetime, timedelta

import pytest

from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import (
    ConfigId,
    Confirmation,
    ConfirmationId,
    InterviewSlot,
    SessionId,
    SlotId,
    SlotTarget,
    TurnId,
)
from cafe_norte.errors import ServiceError
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.persistence.seed import seed_calendar
from tests.support import CONFIG_DIR

NOW = datetime(2026, 10, 20, 10, tzinfo=UTC)
CONFIGS = load_configurations(CONFIG_DIR)
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


async def reserve(store: MemoryStore, slot_id: str, session: str, key: str) -> None:
    async with store.transaction() as tx:
        await store.calendar.reserve(
            tx, SlotId(slot_id), SessionId(session), confirmation(slot_id, key), key
        )


async def test_seed_inserts_missing_slots_and_never_touches_an_existing_one() -> None:
    store = MemoryStore(clock=lambda: NOW)
    await store.calendar.seed([slot(1), slot(2)])
    await reserve(store, "s1", "a", "k1")
    await store.calendar.seed([slot(1), slot(2), slot(3)])
    taken = await store.calendar.get(SlotId("s1"))
    assert taken is not None and taken.status == "reserved"
    free = await store.calendar.available(CHAMBERI, after=NOW, limit=10)
    assert [s.slot_id for s in free] == ["s2", "s3"]


async def test_available_is_this_store_future_free_slots_in_order_up_to_the_limit() -> None:
    store = MemoryStore(clock=lambda: NOW)
    other = ConfigId("arganzuela_barista_v1")
    await store.calendar.seed([slot(3), slot(1), slot(-1), slot(2, other), slot(5)])
    assert [s.slot_id for s in await store.calendar.available(CHAMBERI, after=NOW, limit=2)] == [
        "s1",
        "s3",
    ]
    assert await store.calendar.get(SlotId("nope")) is None


async def test_two_sessions_one_slot_exactly_one_succeeds_and_alternatives_remain() -> None:
    store = MemoryStore(clock=lambda: NOW)
    await store.calendar.seed([slot(1), slot(2)])
    await reserve(store, "s1", "a", "ka")
    with pytest.raises(ServiceError) as error:
        await reserve(store, "s1", "b", "kb")
    assert error.value.code == "conflict"
    assert [s.slot_id for s in await store.calendar.available(CHAMBERI, after=NOW, limit=5)] == [
        "s2"
    ]


async def test_the_race_is_decided_at_commit_not_at_enlist() -> None:
    store = MemoryStore(clock=lambda: NOW)
    await store.calendar.seed([slot(1)])
    async with store.transaction() as first:
        await store.calendar.reserve(first, SlotId("s1"), SessionId("a"), confirmation("s1"), "ka")
        async with store.transaction() as second:
            await store.calendar.reserve(
                second, SlotId("s1"), SessionId("b"), confirmation("s1", "c2"), "kb"
            )
            await second.commit()  # b wins: it committed first
        with pytest.raises(ServiceError):
            await first.commit()
    assert await store.calendar.booking_by_key("kb") is not None
    assert await store.calendar.booking_by_key("ka") is None


async def test_the_same_key_returns_the_original_booking_and_a_session_books_once() -> None:
    store = MemoryStore(clock=lambda: NOW)
    await store.calendar.seed([slot(1), slot(2)])
    await reserve(store, "s1", "a", "ka")
    original = await store.calendar.booking_by_key("ka")
    assert original is not None and original.slot_id == "s1" and original.committed_at == NOW
    async with store.transaction() as tx:
        again = await store.calendar.reserve(
            tx, SlotId("s1"), SessionId("a"), confirmation("s1"), "ka"
        )
    assert again == original
    with pytest.raises(ServiceError) as error:
        await reserve(store, "s2", "a", "k-second")
    assert error.value.code == "conflict"
    assert (await store.calendar.get(SlotId("s2"))) == slot(2)


async def test_seed_calendar_seeds_every_store_from_the_domain_rule() -> None:
    store = MemoryStore(clock=lambda: NOW)
    await seed_calendar(store, CONFIGS, now=NOW)
    for config_id in CONFIGS:
        offered = await store.calendar.available(config_id, after=NOW, limit=3)
        assert len(offered) == 3 and all(s.config_id == config_id for s in offered)
    await seed_calendar(store, CONFIGS, now=NOW)  # a second seed changes nothing
    assert len(await store.calendar.available(CHAMBERI, after=NOW, limit=100)) == 13
