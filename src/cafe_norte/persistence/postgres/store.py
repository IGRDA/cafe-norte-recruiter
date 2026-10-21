"""``PostgresStore``: the pool, the transaction boundary, readiness and the one-read snapshot."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime

from cafe_norte.domain.contracts import SessionId
from cafe_norte.errors import ServiceError
from cafe_norte.observability.contracts import VersionStamp
from cafe_norte.persistence.contracts import (
    SNAPSHOT_TURNS,
    SessionSnapshot,
    SummaryJobs,
    Transaction,
)
from cafe_norte.persistence.export import confirmations_from_events
from cafe_norte.persistence.later import SummaryJobsLater
from cafe_norte.persistence.migrate import apply_pending
from cafe_norte.persistence.postgres.admission import PostgresAdmission
from cafe_norte.persistence.postgres.calendar import PostgresCalendar
from cafe_norte.persistence.postgres.events import (
    PostgresEvents,
    select_events,
    select_timings,
    select_usage,
)
from cafe_norte.persistence.postgres.exports import PostgresExports
from cafe_norte.persistence.postgres.leases import PostgresLeases
from cafe_norte.persistence.postgres.resume_tokens import PostgresResumeTokens
from cafe_norte.persistence.postgres.sessions import PostgresSessions, select_state
from cafe_norte.persistence.postgres.support import (
    PostgresTransaction,
    fetch_one,
    make_pool,
    reading,
    translating,
)
from cafe_norte.persistence.postgres.turns import PostgresTurns, select_turns

MAINTENANCE_LOCK = 7_423_002  # one advisory lock for every container's retention purge
SNAPSHOT_EVENTS = 100_000  # dozens of events per turn; the session cap keeps it far below


class PostgresStore:
    """At most ``pool_size`` connections; statement and lock timeouts of a few seconds; never
    holds a transaction open across an external call. ``open`` applies pending migrations."""

    def __init__(
        self,
        dsn: str,
        *,
        pool_size: int = 5,
        poll_seconds: float = 0.2,
        checkout_seconds: float = 5.0,
        statement_seconds: float = 3.0,
        lock_seconds: float = 2.0,
        admission_ttl_seconds: float = 600.0,
    ) -> None:
        self._dsn = dsn
        self._pool = make_pool(
            dsn,
            pool_size=pool_size,
            checkout_seconds=checkout_seconds,
            statement_seconds=statement_seconds,
            lock_seconds=lock_seconds,
        )
        connect = self._pool.connection
        self.sessions = PostgresSessions(connect)
        self.turns = PostgresTurns(connect)
        self.events = PostgresEvents(connect, poll_seconds=poll_seconds)
        self.calendar = PostgresCalendar(connect)
        self.leases = PostgresLeases(connect)
        self.admission = PostgresAdmission(connect, ttl_seconds=admission_ttl_seconds)
        self.summary_jobs: SummaryJobs = SummaryJobsLater()
        self.resume_tokens = PostgresResumeTokens(connect)
        self.exports = PostgresExports(connect)
        self._open = False

    async def open(self) -> None:
        if self._open:
            return
        await apply_pending(self._dsn)
        await self._pool.open(wait=True, timeout=10)
        self._open = True

    async def close(self) -> None:
        if self._open:
            await self._pool.close()
            self._open = False

    def transaction(self) -> AbstractAsyncContextManager[Transaction]:
        return self._transaction()

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[Transaction]:
        """Commits on clean exit unless already committed; rolls back on an exception."""
        async with translating(), self._pool.connection() as conn:
            tx = PostgresTransaction(conn)
            try:
                yield tx
            except BaseException:
                await tx.rollback()
                raise
            else:
                if not tx.committed:
                    await tx.commit()

    async def check_ready(self) -> bool:
        """Open and answering. Before ``open`` the process is not ready to serve."""
        if not self._open:
            return False
        try:
            async with reading(self._pool.connection) as conn:
                await conn.execute("select 1")
        except ServiceError:
            return False
        return True

    def maintenance(self) -> AbstractAsyncContextManager[bool]:
        return self._maintenance()

    @asynccontextmanager
    async def _maintenance(self) -> AsyncIterator[bool]:
        """A session-level advisory lock on one dedicated connection, released with it."""
        async with translating(), self._pool.connection() as conn:
            row = await fetch_one(
                conn, "select pg_try_advisory_lock(%s) as held", (MAINTENANCE_LOCK,)
            )
            held = bool(row and row["held"])
            try:
                yield held
            finally:
                if held:
                    await conn.execute("select pg_advisory_unlock(%s)", (MAINTENANCE_LOCK,))
                await conn.commit()

    async def snapshot(
        self, session_id: SessionId, *, versions: VersionStamp, taken_at: datetime
    ) -> SessionSnapshot | None:
        """One repeatable-read transaction: every read sees the same committed state."""
        async with reading(self._pool.connection) as conn:
            await conn.execute("set transaction isolation level repeatable read read only")
            state = await select_state(conn, session_id)
            if state is None:
                return None
            events = await select_events(conn, session_id, after=0, limit=SNAPSHOT_EVENTS)
            return SessionSnapshot(
                state=state,
                turns=await select_turns(conn, session_id, SNAPSHOT_TURNS),
                confirmations=confirmations_from_events(events),
                events=events,
                usage=await select_usage(conn, session_id),
                timings=await select_timings(conn, session_id),
                versions=versions,
                taken_at=taken_at,
            )
