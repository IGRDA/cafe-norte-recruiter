"""What is specific to the in-memory store: its deferred-apply transactions. The shared
behaviour is in ``test_store_contract.py`` and ``test_calendar_contract.py``."""

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
from cafe_norte.persistence.memory import MemoryStore
from tests.support.builders import NOW


def confirmation(cid: str) -> Confirmation:
    return Confirmation(
        confirmation_id=ConfirmationId(cid),
        target=SlotTarget(slot_id=SlotId("s1"), brief_revision=1),
        presentation_text="¿Te la reservo?",
        presented_turn_id=TurnId("t1"),
        fully_delivered=True,
        status="confirmed",
    )


async def test_the_race_is_decided_at_commit_not_at_enlist() -> None:
    """Two open transactions reserve the same slot; whoever commits first wins, exactly as a
    row lock would decide it in Postgres."""
    store = MemoryStore(clock=lambda: NOW)
    for session_id in ("a", "b"):
        await store.sessions.create(
            SessionState(
                session_id=SessionId(session_id),
                config_id=ConfigId("c"),
                config_version="1",
                language="es",
                channel="text",
                created_at=NOW,
                candidate=CandidateRecord(),
            ),
            access_hash="",
        )
    await store.calendar.seed(
        [
            InterviewSlot(
                slot_id=SlotId("s1"),
                config_id=ConfigId("c"),
                starts_at_utc=NOW + timedelta(hours=1),
            )
        ]
    )
    async with store.transaction() as first:
        await store.calendar.reserve(first, SlotId("s1"), SessionId("a"), confirmation("c1"), "ka")
        async with store.transaction() as second:
            await store.calendar.reserve(
                second, SlotId("s1"), SessionId("b"), confirmation("c2"), "kb"
            )
            await second.commit()  # b wins: it committed first
        with pytest.raises(ServiceError):
            await first.commit()
    winner = await store.calendar.booking_by_key("kb")
    assert winner is not None and winner.committed_at == NOW
    assert await store.calendar.booking_by_key("ka") is None


async def test_a_scripted_save_failure_fails_one_save_and_writes_nothing() -> None:
    store = MemoryStore(clock=lambda: NOW)
    state = SessionState(
        session_id=SessionId("s"),
        config_id=ConfigId("c"),
        config_version="1",
        language="es",
        channel="text",
        created_at=NOW,
    )
    await store.sessions.create(state, access_hash="")
    changed = state.model_copy(update={"language": "en"})
    store.sessions.fail_next_save = ServiceError("down", code="provider_unavailable")
    with pytest.raises(ServiceError) as error:
        async with store.transaction() as tx:
            await store.sessions.save(tx, changed, expected_revision=0)
    assert error.value.code == "provider_unavailable"
    assert (await store.sessions.get(SessionId("s"))) == state  # nothing was written
    async with store.transaction() as tx:  # one-shot: the next save goes through
        await store.sessions.save(tx, changed, expected_revision=0)
    assert (await store.sessions.get(SessionId("s"))) == changed
