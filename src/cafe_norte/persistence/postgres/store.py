"""``PostgresStore``: the pool, the transaction boundary, readiness and the one-read snapshot."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime

from cafe_norte.domain.contracts import SessionId
from cafe_norte.errors import ServiceError
from cafe_norte.observability.contracts import VersionStamp
from cafe_norte.persistence.contracts import (
    SNAPSHOT_TURNS,
    Admission,
    Exports,
    ResumeTokens,
    SessionSnapshot,
    SummaryJobs,
    Transaction,
)
from cafe_norte.persistence.export import confirmations_from_events
from cafe_norte.persistence.later import (
    AdmissionLater,
    ExportsLater,
    ResumeTokensLater,
    SummaryJobsLater,
)
from cafe_norte.persistence.migrate import apply_pending
from cafe_norte.persistence.postgres.calendar import PostgresCalendar
from cafe_norte.persistence.postgres.events import (
    PostgresEvents,
    select_events,
    select_timings,
    select_usage,
)
from cafe_norte.persistence.postgres.leases import PostgresLeases
from cafe_norte.persistence.postgres.sessions import PostgresSessions, select_state
from cafe_norte.persistence.postgres.support import (
    PostgresTransaction,
    make_pool,
    reading,
    translating,
)
from cafe_norte.persistence.postgres.turns import PostgresTurns, select_turns

SNAPSHOT_EVENTS = (
    100_000  # a session journals a few dozen events per turn; the cap keeps it far below
)


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
        self.admission: Admission = AdmissionLater()
        self.summary_jobs: SummaryJobs = SummaryJobsLater()
        self.resume_tokens: ResumeTokens = ResumeTokensLater()
        self.exports: Exports = ExportsLater()
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
