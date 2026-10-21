"""Repositories whose stage has not arrived: the ports are declared, the calls raise.

Both stores use these so a route that reaches one fails the same way everywhere. Each class
disappears when its stage lands (summary jobs and export snapshots: the retention stage)."""

from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.contracts import SummaryJob, Transaction


class SummaryJobsLater:
    async def enqueue(self, tx: Transaction, session_id: SessionId) -> None:
        raise NotImplementedError

    async def claim_next(self, owner: str, *, max_attempts: int) -> SummaryJob | None:
        raise NotImplementedError

    async def finish(self, job: SummaryJob, *, ok: bool) -> None:
        raise NotImplementedError


class ExportsLater:
    async def write_snapshot(self, tx: Transaction, session_id: SessionId, json_text: str) -> None:
        raise NotImplementedError

    async def read_snapshot(self, session_id: SessionId) -> str | None:
        raise NotImplementedError
