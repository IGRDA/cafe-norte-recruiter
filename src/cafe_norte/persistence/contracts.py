"""Repository ports. Each method is one small transaction unless it takes a ``Transaction``."""

from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.contracts import (
    Booking,
    Channel,
    ConfigId,
    Confirmation,
    InputId,
    InterviewSlot,
    SessionId,
    SessionState,
    Signal,
    SlotId,
    TurnId,
)
from cafe_norte.errors import Language
from cafe_norte.observability.contracts import StageTiming, UsageRecord, VersionStamp


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TurnRecord(Frozen):
    turn_id: TurnId
    session_id: SessionId
    input_id: InputId
    role: Literal["user", "assistant"]
    channel: Channel
    language: Language
    text: str  # finalized user text, or generated assistant text
    delivered_text: str | None = None  # best available account of what was actually spoken
    interrupted: bool = False
    started_at: datetime
    finished_at: datetime | None = None


class EventRecord(Frozen):
    """Validation results, tool results, retrieval sources, signals, timings: the reviewer panel."""

    session_id: SessionId
    turn_id: TurnId | None
    seq: int
    kind: str
    payload_json: str
    at: datetime


class Lease(Frozen):
    session_id: SessionId
    owner: str  # container instance id
    generation: int
    expires_at: datetime


class SummaryJob(Frozen):
    session_id: SessionId
    status: Literal["pending", "running", "done", "failed"]
    attempts: int
    claimed_by: str | None
    updated_at: datetime


class Transaction(Protocol):
    """A unit of work. Repositories accept it so one commit can cover several writes."""

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class Sessions(Protocol):
    async def create(self, state: SessionState, *, access_hash: str) -> None: ...
    async def get(self, session_id: SessionId) -> SessionState | None: ...
    async def save(self, tx: Transaction, state: SessionState, *, expected_revision: int) -> None:
        """Conditional update on ``candidate.revision``; raises ``conflict`` otherwise."""
        ...

    async def delete(self, session_id: SessionId) -> None: ...
    async def expired(self, before: datetime, limit: int) -> tuple[SessionId, ...]: ...


class Turns(Protocol):
    async def append(self, tx: Transaction, turn: TurnRecord) -> None:
        """Unique on ``(session_id, input_id)``: a resubmitted input is a ``conflict``."""
        ...

    async def recent(self, session_id: SessionId, limit: int) -> tuple[TurnRecord, ...]: ...


class Events(Protocol):
    async def append(self, tx: Transaction, event: EventRecord) -> None: ...
    async def since(self, session_id: SessionId, seq: int) -> AsyncIterator[EventRecord]: ...
    async def record_usage(self, tx: Transaction, usage: UsageRecord) -> None: ...
    async def record_timing(self, tx: Transaction, timing: StageTiming) -> None: ...
    async def record_signal(
        self, tx: Transaction, session_id: SessionId, signal: Signal
    ) -> None: ...


class Calendar(Protocol):
    async def seed(self, slots: Sequence[InterviewSlot]) -> None:
        """Insert missing future slots; never touch an occupied one."""
        ...

    async def available(
        self, config_id: ConfigId, *, after: datetime, limit: int
    ) -> tuple[InterviewSlot, ...]: ...

    async def reserve(
        self,
        tx: Transaction,
        slot_id: SlotId,
        session_id: SessionId,
        confirmation: Confirmation,
        idempotency_key: str,
    ) -> Booking:
        """Row-locked. Unique per slot and at most one active booking per session. The same
        ``idempotency_key`` returns the original booking; a taken slot raises ``conflict``."""
        ...

    async def booking_by_key(self, idempotency_key: str) -> Booking | None: ...


class Leases(Protocol):
    async def claim(self, session_id: SessionId, owner: str, ttl_seconds: int) -> Lease | None:
        """Succeeds when no live lease exists; increments ``generation``."""
        ...

    async def renew(self, lease: Lease, ttl_seconds: int) -> Lease | None: ...
    async def release(self, lease: Lease) -> None: ...


class Admission(Protocol):
    """Bounded voice capacity and spend reservation, enforced across containers."""

    async def acquire(
        self, session_id: SessionId, *, max_active: int, reserve_eur: float
    ) -> bool: ...
    async def release(self, session_id: SessionId, *, actual_eur: float) -> None: ...


class SummaryJobs(Protocol):
    async def enqueue(self, tx: Transaction, session_id: SessionId) -> None: ...
    async def claim_next(self, owner: str, *, max_attempts: int) -> SummaryJob | None: ...
    async def finish(self, job: SummaryJob, *, ok: bool) -> None: ...


class ResumeTokens(Protocol):
    async def issue(self, session_id: SessionId, token_hash: str, expires_at: datetime) -> None: ...
    async def redeem(self, token_hash: str, now: datetime) -> SessionId | None: ...


class Exports(Protocol):
    async def write_snapshot(
        self, tx: Transaction, session_id: SessionId, json_text: str
    ) -> None: ...
    async def read_snapshot(self, session_id: SessionId) -> str | None: ...


class Store(Protocol):
    """Everything the composition root hands to the runtime and the API."""

    sessions: Sessions
    turns: Turns
    events: Events
    calendar: Calendar
    leases: Leases
    admission: Admission
    summary_jobs: SummaryJobs
    resume_tokens: ResumeTokens
    exports: Exports

    def transaction(self) -> AbstractAsyncContextManager[Transaction]: ...
    async def check_ready(self) -> bool: ...


class SessionSnapshot(Frozen):
    """One consistent read used for the export and the browser's snapshot endpoint."""

    state: SessionState
    turns: tuple[TurnRecord, ...]
    confirmations: tuple[Confirmation, ...]
    events: tuple[EventRecord, ...]
    usage: tuple[UsageRecord, ...]
    timings: tuple[StageTiming, ...]
    versions: VersionStamp
    taken_at: datetime
