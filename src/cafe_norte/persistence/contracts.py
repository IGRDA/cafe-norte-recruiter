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


class Transaction(Protocol):
    """A unit of work. Repositories accept it so one commit can cover several writes."""

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


SNAPSHOT_TURNS = 10_000  # far above the session cap; a snapshot is the whole transcript


class Sessions(Protocol):
    async def create(self, state: SessionState, *, access_hash: str) -> None: ...
    async def get(self, session_id: SessionId) -> SessionState | None: ...
    async def save(
        self,
        tx: Transaction,
        state: SessionState,
        *,
        expected_revision: int,
        lease_generation: int | None = None,
    ) -> None:
        """Conditional update on ``candidate.revision``; with ``lease_generation`` also on a
        live lease of that generation; raises ``conflict`` otherwise."""
        ...

    async def next_seq(
        self, tx: Transaction, session_id: SessionId, *, lease_generation: int | None = None
    ) -> int:
        """The next event sequence number of the session, owned by the store so a restarted
        process never reuses one; fenced like ``save``; ``not_found`` for an unknown session."""
        ...

    async def delete(self, session_id: SessionId) -> None: ...
    async def expired(self, before: datetime, limit: int) -> tuple[SessionId, ...]: ...


class Turns(Protocol):
    async def append(self, tx: Transaction, turn: TurnRecord) -> None:
        """Unique on ``(session_id, input_id, role)``; a duplicate raises ``conflict``."""
        ...

    async def recent(self, session_id: SessionId, limit: int) -> tuple[TurnRecord, ...]: ...

    async def mark_delivered(
        self,
        tx: Transaction,
        session_id: SessionId,
        turn_id: TurnId,
        *,
        delivered_text: str,
        interrupted: bool,
    ) -> None:
        """Record what the voice channel actually played for the assistant turn."""
        ...


class Events(Protocol):
    async def append(self, tx: Transaction, event: EventRecord) -> None: ...
    def since(self, session_id: SessionId, seq: int) -> AsyncIterator[EventRecord]:
        """Stored events after ``seq``, then live ones as they commit; an async generator."""
        ...

    async def record_usage(self, tx: Transaction, usage: UsageRecord) -> None: ...
    async def record_timing(self, tx: Transaction, timing: StageTiming) -> None: ...


class Calendar(Protocol):
    async def seed(self, slots: Sequence[InterviewSlot]) -> None:
        """Insert missing future slots; never touch an occupied one."""
        ...

    async def available(
        self, config_id: ConfigId, *, after: datetime, limit: int
    ) -> tuple[InterviewSlot, ...]: ...

    async def get(self, slot_id: SlotId) -> InterviewSlot | None: ...

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
    """Fence turn writes with a monotonically increasing generation.

    A turn claims once and releases on exit; its deadline must fit within the lease TTL.
    """

    async def claim(self, session_id: SessionId, owner: str, ttl_seconds: int) -> Lease | None:
        """Claim an existing session if unowned, expired or held by this owner.

        Every successful claim increments generation, including the same owner's reclaim.
        Return None for a missing session or another owner's live lease.
        """
        ...

    async def release(self, lease: Lease) -> None:
        """Expire the current generation; releasing a stale lease does nothing."""
        ...


class Admission(Protocol):
    """Reserve voice capacity; Postgres serializes admission across containers.

    Reacquiring an active session is idempotent. Spend is recorded, not a budget gate.
    """

    async def acquire(
        self, session_id: SessionId, *, max_active: int, reserve_eur: float
    ) -> bool: ...
    async def release(self, session_id: SessionId, *, actual_eur: float) -> None: ...
    async def release_left_over(self) -> int:
        """At startup: release every place this instance still holds. They belong to calls
        of the process that ran before, which a restart ended without releasing them."""
        ...


class ResumeTokens(Protocol):
    async def issue(self, session_id: SessionId, token_hash: str, expires_at: datetime) -> None: ...
    async def redeem(self, token_hash: str, now: datetime) -> SessionId | None: ...


class Exports(Protocol):
    async def write_snapshot(
        self, tx: Transaction, session_id: SessionId, json_text: str
    ) -> None: ...
    async def read_snapshot(self, session_id: SessionId) -> str | None: ...


class Store(Protocol):
    """Everything the composition root hands to the runtime and the API. Read-only properties
    so an implementation may expose richer repository types."""

    @property
    def sessions(self) -> Sessions: ...
    @property
    def turns(self) -> Turns: ...
    @property
    def events(self) -> Events: ...
    @property
    def calendar(self) -> Calendar: ...
    @property
    def leases(self) -> Leases: ...
    @property
    def admission(self) -> Admission: ...
    @property
    def resume_tokens(self) -> ResumeTokens: ...
    @property
    def exports(self) -> Exports: ...

    def transaction(self) -> AbstractAsyncContextManager[Transaction]:
        """Commit on normal exit unless already committed; roll back on an exception.

        Pass the yielded transaction only to repositories of this store. Announce a state
        change only after leaving this context successfully.
        """
        ...

    async def open(self) -> None:
        """Connect and apply pending migrations; idempotent."""
        ...

    async def close(self) -> None: ...
    async def check_ready(self) -> bool: ...

    def maintenance(self) -> AbstractAsyncContextManager[bool]:
        """Try to hold the one maintenance lock of the database for the block; yields whether
        it was obtained, so overlapping containers never purge the same rows."""
        ...

    async def snapshot(
        self, session_id: SessionId, *, versions: VersionStamp, taken_at: datetime
    ) -> "SessionSnapshot | None":
        """One consistent read of everything the export needs; ``None`` for an unknown
        session. Confirmations are the history journaled in ``state_updated`` events."""
        ...


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
