"""Repositories whose stage has not arrived: the ports are declared, the calls raise.

Both stores use these so a route that reaches one fails the same way everywhere. Each class
disappears when its stage lands (leases, admission rows, resume tokens: PR2; summary jobs and
export snapshots: PR4)."""

from datetime import datetime

from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.contracts import Lease, SummaryJob, Transaction


class LeasesLater:
    async def claim(self, session_id: SessionId, owner: str, ttl_seconds: int) -> Lease | None:
        raise NotImplementedError

    async def renew(self, lease: Lease, ttl_seconds: int) -> Lease | None:
        raise NotImplementedError

    async def release(self, lease: Lease) -> None:
        raise NotImplementedError


class AdmissionLater:
    async def acquire(self, session_id: SessionId, *, max_active: int, reserve_eur: float) -> bool:
        raise NotImplementedError

    async def release(self, session_id: SessionId, *, actual_eur: float) -> None:
        raise NotImplementedError


class SummaryJobsLater:
    async def enqueue(self, tx: Transaction, session_id: SessionId) -> None:
        raise NotImplementedError

    async def claim_next(self, owner: str, *, max_attempts: int) -> SummaryJob | None:
        raise NotImplementedError

    async def finish(self, job: SummaryJob, *, ok: bool) -> None:
        raise NotImplementedError


class ResumeTokensLater:
    async def issue(self, session_id: SessionId, token_hash: str, expires_at: datetime) -> None:
        raise NotImplementedError

    async def redeem(self, token_hash: str, now: datetime) -> SessionId | None:
        raise NotImplementedError


class ExportsLater:
    async def write_snapshot(self, tx: Transaction, session_id: SessionId, json_text: str) -> None:
        raise NotImplementedError

    async def read_snapshot(self, session_id: SessionId) -> str | None:
        raise NotImplementedError
