"""Bounded voice capacity in the memory store."""

from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.memory import MemoryStore


async def test_at_most_max_active_sessions_and_release_frees_a_slot() -> None:
    admission = MemoryStore().admission
    a, b, c = SessionId("a"), SessionId("b"), SessionId("c")
    assert await admission.acquire(a, max_active=2, reserve_eur=0.5)
    assert await admission.acquire(b, max_active=2, reserve_eur=0.5)
    assert not await admission.acquire(c, max_active=2, reserve_eur=0.5)
    assert await admission.acquire(a, max_active=2, reserve_eur=0.5)  # already in: idempotent
    await admission.release(a, actual_eur=0.3)
    assert await admission.acquire(c, max_active=2, reserve_eur=0.5)
    await admission.release(SessionId("never"), actual_eur=0.0)  # unknown: no error
