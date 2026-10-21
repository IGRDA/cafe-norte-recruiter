"""Repositories whose stage has not arrived: the ports are declared, the calls raise.

Both stores use these so a route that reaches one fails the same way everywhere. Each class
disappears when its stage lands (the narrative summary job, which stays optional)."""

from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.contracts import SummaryJob, Transaction


class SummaryJobsLater:
    async def enqueue(self, tx: Transaction, session_id: SessionId) -> None:
        raise NotImplementedError

    async def claim_next(self, owner: str, *, max_attempts: int) -> SummaryJob | None:
        raise NotImplementedError

    async def finish(self, job: SummaryJob, *, ok: bool) -> None:
        raise NotImplementedError
