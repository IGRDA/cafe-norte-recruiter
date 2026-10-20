"""In-memory Store for offline tests. Same semantics, one process, no durability."""

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


class MemoryStore:
    sessions: Sessions
    turns: Turns
    events: Events
    calendar: Calendar
    leases: Leases
    admission: Admission
    summary_jobs: SummaryJobs
    resume_tokens: ResumeTokens
    exports: Exports

    def __init__(self) -> None:
        raise NotImplementedError

    def transaction(self) -> AbstractAsyncContextManager[Transaction]:
        raise NotImplementedError

    async def check_ready(self) -> bool:
        return True
