"""The journal: events by sequence, the polling live stream, usage and timings."""

import asyncio
from collections.abc import AsyncIterator

from cafe_norte.domain.contracts import SessionId
from cafe_norte.observability.contracts import StageTiming, UsageRecord
from cafe_norte.persistence.contracts import EventRecord, Transaction
from cafe_norte.persistence.postgres.codecs import (
    EVENT_COLUMNS,
    TIMING_COLUMNS,
    USAGE_COLUMNS,
    event_from_row,
    event_params,
    timing_from_row,
    timing_params,
    usage_from_row,
    usage_params,
)
from cafe_norte.persistence.postgres.support import (
    Connect,
    Connection,
    connection,
    fetch_all,
    reading,
)

EVENTS_PER_POLL = 500


async def select_events(
    conn: Connection, session_id: SessionId, *, after: int, limit: int = EVENTS_PER_POLL
) -> tuple[EventRecord, ...]:
    rows = await fetch_all(
        conn,
        f"select {EVENT_COLUMNS} from events where session_id = %s and seq > %s "
        "order by seq limit %s",
        (session_id, after, limit),
    )
    return tuple(event_from_row(row) for row in rows)


async def select_usage(conn: Connection, session_id: SessionId) -> tuple[UsageRecord, ...]:
    rows = await fetch_all(
        conn, f"select {USAGE_COLUMNS} from usage where session_id = %s order by id", (session_id,)
    )
    return tuple(usage_from_row(row) for row in rows)


async def select_timings(conn: Connection, session_id: SessionId) -> tuple[StageTiming, ...]:
    rows = await fetch_all(
        conn,
        f"select {TIMING_COLUMNS} from timings where session_id = %s order by id",
        (session_id,),
    )
    return tuple(timing_from_row(row) for row in rows)


class PostgresEvents:
    def __init__(self, connect: Connect, *, poll_seconds: float) -> None:
        self._connect = connect
        self._poll_seconds = poll_seconds

    async def append(self, tx: Transaction, event: EventRecord) -> None:
        await connection(tx).execute(
            "insert into events (session_id, seq, turn_id, kind, payload, at) values "
            "(%(session_id)s, %(seq)s, %(turn_id)s, %(kind)s, %(payload)s::jsonb, %(at)s)",
            event_params(event),
        )

    async def since(self, session_id: SessionId, seq: int) -> AsyncIterator[EventRecord]:
        """Stored events after ``seq``, then each new one as it commits, found by polling.
        A connection is held only for the statement, never while waiting. Never ends."""
        last = seq
        while True:
            async with reading(self._connect) as conn:
                batch = await select_events(conn, session_id, after=last)
            for event in batch:
                last = event.seq
                yield event
            if not batch:
                await asyncio.sleep(self._poll_seconds)

    async def record_usage(self, tx: Transaction, usage: UsageRecord) -> None:
        await connection(tx).execute(
            f"insert into usage ({USAGE_COLUMNS}) values "
            "(%(session_id)s, %(turn_id)s, %(kind)s, %(quantity)s, %(unit_detail)s, %(estimated)s)",
            usage_params(usage),
        )

    async def record_timing(self, tx: Transaction, timing: StageTiming) -> None:
        await connection(tx).execute(
            f"insert into timings ({TIMING_COLUMNS}) values "
            "(%(session_id)s, %(turn_id)s, %(stage)s, %(milliseconds)s, %(source)s, %(tool_name)s)",
            timing_params(timing),
        )
