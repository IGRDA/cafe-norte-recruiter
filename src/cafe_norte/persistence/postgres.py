"""psycopg 3 implementation of the Store port."""

from contextlib import AbstractAsyncContextManager

from cafe_norte.persistence.contracts import (
    Admission,
    Calendar,
    Events,
    Exports,
    Leases,
    ResumeTokens,
    Sessions,
    SummaryJobs,
    Transaction,
    Turns,
)


class PostgresStore:
    """Async pool, at most five connections, statement and lock timeouts of a few seconds.
    Never holds a transaction open across an external call."""

    sessions: Sessions
    turns: Turns
    events: Events
    calendar: Calendar
    leases: Leases
    admission: Admission
    summary_jobs: SummaryJobs
    resume_tokens: ResumeTokens
    exports: Exports

    def __init__(self, dsn: str, *, pool_size: int = 5) -> None:
        raise NotImplementedError

    async def open(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    def transaction(self) -> AbstractAsyncContextManager[Transaction]:
        raise NotImplementedError

    async def check_ready(self) -> bool:
        raise NotImplementedError
