"""Retention: demo sessions older than the retention window are deleted, a bounded batch at a
time, at startup and periodically, under the store's maintenance lock so two containers never
do the same work (spec §8, D34)."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.contracts import Store

log = logging.getLogger(__name__)


async def purge_expired(
    store: Store, *, now: datetime, days: int, limit: int = 100
) -> tuple[SessionId, ...]:
    """Delete the oldest sessions created more than ``days`` ago, at most ``limit``; nothing
    when another container holds the maintenance lock. Returns what was deleted."""
    async with store.maintenance() as held:
        if not held:
            return ()
        expired = await store.sessions.expired(now - timedelta(days=days), limit)
        for session_id in expired:
            await store.sessions.delete(session_id)
        return expired


async def purge_periodically(
    store: Store,
    *,
    days: int,
    interval_seconds: float,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """The lifespan task: a purge now, then one every ``interval_seconds`` until cancelled.
    A failure is logged and the next round still comes."""
    while True:
        try:
            deleted = await purge_expired(store, now=clock(), days=days)
            if deleted:
                log.info("retention: deleted %d expired sessions", len(deleted))
        except Exception:
            log.exception("retention purge failed")
        await asyncio.sleep(interval_seconds)
