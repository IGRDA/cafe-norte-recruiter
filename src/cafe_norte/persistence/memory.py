"""In-memory Store for offline tests and local runs. Same semantics, one process, no durability.

Writes taken through a transaction are buffered and applied on ``commit``; conditional checks
(revision, uniqueness) run again at commit time so a conflict surfaces exactly where Postgres
would raise it. Repositories the tracer bullet does not need yet raise ``NotImplementedError``.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from functools import partial

from cafe_norte.domain.contracts import (
    Booking,
    ConfigId,
    Confirmation,
    InterviewSlot,
    SessionId,
    SessionState,
    Signal,
    SlotId,
    TurnId,
)
from cafe_norte.errors import ServiceError
from cafe_norte.observability.contracts import StageTiming, UsageRecord
from cafe_norte.persistence.contracts import (
    EventRecord,
    Lease,
    SummaryJob,
    Transaction,
    TurnRecord,
)


class MemoryTransaction:
    def __init__(self) -> None:
        self._ops: list[Callable[[], None]] = []
        self.committed = False

    def enlist(self, op: Callable[[], None]) -> None:
        self._ops.append(op)

    async def commit(self) -> None:
        ops, self._ops = self._ops, []
        for op in ops:
            op()
        self.committed = True

    async def rollback(self) -> None:
        self._ops = []


def _tx(tx: Transaction) -> MemoryTransaction:
    if not isinstance(tx, MemoryTransaction):
        raise TypeError("MemoryStore repositories need a MemoryTransaction")
    return tx


class MemorySessions:
    def __init__(self) -> None:
        self._states: dict[SessionId, SessionState] = {}

    async def create(self, state: SessionState, *, access_hash: str) -> None:
        if state.session_id in self._states:
            raise ServiceError("session exists", code="conflict")
        self._states[state.session_id] = state

    async def get(self, session_id: SessionId) -> SessionState | None:
        return self._states.get(session_id)

    async def save(self, tx: Transaction, state: SessionState, *, expected_revision: int) -> None:
        def apply() -> None:
            current = self._states.get(state.session_id)
            if current is None:
                raise ServiceError("session missing", code="not_found")
            if current.candidate.revision != expected_revision:
                raise ServiceError("revision mismatch", code="conflict")
            self._states[state.session_id] = state

        _tx(tx).enlist(apply)

    async def delete(self, session_id: SessionId) -> None:
        self._states.pop(session_id, None)

    async def expired(self, before: datetime, limit: int) -> tuple[SessionId, ...]:
        raise NotImplementedError


class MemoryTurns:
    def __init__(self) -> None:
        self._turns: dict[SessionId, list[TurnRecord]] = {}

    def _conflicts(self, turn: TurnRecord) -> bool:
        return any(
            t.input_id == turn.input_id and t.role == turn.role
            for t in self._turns.get(turn.session_id, [])
        )

    async def append(self, tx: Transaction, turn: TurnRecord) -> None:
        """Unique on ``(session_id, input_id, role)``; checked now and again at commit."""
        if self._conflicts(turn):
            raise ServiceError("duplicate input_id", code="conflict")

        def apply() -> None:
            if self._conflicts(turn):
                raise ServiceError("duplicate input_id", code="conflict")
            self._turns.setdefault(turn.session_id, []).append(turn)

        _tx(tx).enlist(apply)

    async def recent(self, session_id: SessionId, limit: int) -> tuple[TurnRecord, ...]:
        """The last ``limit`` turns in chronological order."""
        turns = self._turns.get(session_id, [])
        return tuple(turns[-limit:]) if limit else ()

    async def mark_delivered(
        self,
        tx: Transaction,
        session_id: SessionId,
        turn_id: TurnId,
        *,
        delivered_text: str,
        interrupted: bool,
    ) -> None:
        def apply() -> None:
            turns = self._turns.get(session_id, [])
            for index, turn in enumerate(turns):
                if turn.turn_id == turn_id and turn.role == "assistant":
                    turns[index] = turn.model_copy(
                        update={"delivered_text": delivered_text, "interrupted": interrupted}
                    )

        _tx(tx).enlist(apply)


class MemoryEvents:
    def __init__(self) -> None:
        self._events: dict[SessionId, list[EventRecord]] = {}
        self.usage: list[UsageRecord] = []
        self.timings: list[StageTiming] = []
        self.signals: list[tuple[SessionId, Signal]] = []
        self._changed = asyncio.Condition()

    async def append(self, tx: Transaction, event: EventRecord) -> None:
        def apply() -> None:
            stored = self._events.setdefault(event.session_id, [])
            if any(e.seq == event.seq for e in stored):
                raise ServiceError("duplicate seq", code="conflict")
            stored.append(event)
            stored.sort(key=lambda e: e.seq)
            self._notify()

        _tx(tx).enlist(apply)

    def _notify(self) -> None:
        async def wake() -> None:
            async with self._changed:
                self._changed.notify_all()

        asyncio.get_running_loop().create_task(wake())

    async def since(self, session_id: SessionId, seq: int) -> AsyncIterator[EventRecord]:
        """Stored events after ``seq``, then each new one as it is committed. Never ends."""
        last = seq
        while True:
            pending = [e for e in self._events.get(session_id, []) if e.seq > last]
            for event in pending:
                last = event.seq
                yield event
            async with self._changed:
                await self._changed.wait_for(partial(self._has_after, session_id, last))

    def _has_after(self, session_id: SessionId, seq: int) -> bool:
        return any(e.seq > seq for e in self._events.get(session_id, []))

    def last_seq(self, session_id: SessionId) -> int:
        events = self._events.get(session_id, [])
        return events[-1].seq if events else 0

    async def record_usage(self, tx: Transaction, usage: UsageRecord) -> None:
        _tx(tx).enlist(lambda: self.usage.append(usage))

    async def record_timing(self, tx: Transaction, timing: StageTiming) -> None:
        _tx(tx).enlist(lambda: self.timings.append(timing))

    async def record_signal(self, tx: Transaction, session_id: SessionId, signal: Signal) -> None:
        _tx(tx).enlist(lambda: self.signals.append((session_id, signal)))


class _CalendarLater:
    async def seed(self, slots: Sequence[InterviewSlot]) -> None:
        raise NotImplementedError

    async def available(
        self, config_id: ConfigId, *, after: datetime, limit: int
    ) -> tuple[InterviewSlot, ...]:
        raise NotImplementedError

    async def reserve(
        self,
        tx: Transaction,
        slot_id: SlotId,
        session_id: SessionId,
        confirmation: Confirmation,
        idempotency_key: str,
    ) -> Booking:
        raise NotImplementedError

    async def booking_by_key(self, idempotency_key: str) -> Booking | None:
        raise NotImplementedError


class _LeasesLater:
    async def claim(self, session_id: SessionId, owner: str, ttl_seconds: int) -> Lease | None:
        raise NotImplementedError

    async def renew(self, lease: Lease, ttl_seconds: int) -> Lease | None:
        raise NotImplementedError

    async def release(self, lease: Lease) -> None:
        raise NotImplementedError


class MemoryAdmission:
    """Voice capacity for one process: a set of active session ids. Postgres makes it
    cross-container; the spend reservation is recorded, not enforced, until pricing lands."""

    def __init__(self) -> None:
        self._active: dict[SessionId, float] = {}

    async def acquire(self, session_id: SessionId, *, max_active: int, reserve_eur: float) -> bool:
        if session_id in self._active:
            return True
        if len(self._active) >= max_active:
            return False
        self._active[session_id] = reserve_eur
        return True

    async def release(self, session_id: SessionId, *, actual_eur: float) -> None:
        self._active.pop(session_id, None)

    @property
    def active(self) -> frozenset[SessionId]:
        return frozenset(self._active)


class _SummaryJobsLater:
    async def enqueue(self, tx: Transaction, session_id: SessionId) -> None:
        raise NotImplementedError

    async def claim_next(self, owner: str, *, max_attempts: int) -> SummaryJob | None:
        raise NotImplementedError

    async def finish(self, job: SummaryJob, *, ok: bool) -> None:
        raise NotImplementedError


class _ResumeTokensLater:
    async def issue(self, session_id: SessionId, token_hash: str, expires_at: datetime) -> None:
        raise NotImplementedError

    async def redeem(self, token_hash: str, now: datetime) -> SessionId | None:
        raise NotImplementedError


class _ExportsLater:
    async def write_snapshot(self, tx: Transaction, session_id: SessionId, json_text: str) -> None:
        raise NotImplementedError

    async def read_snapshot(self, session_id: SessionId) -> str | None:
        raise NotImplementedError


class MemoryStore:
    def __init__(self) -> None:
        self.sessions = MemorySessions()
        self.turns = MemoryTurns()
        self.events = MemoryEvents()
        self.calendar = _CalendarLater()
        self.leases = _LeasesLater()
        self.admission = MemoryAdmission()
        self.summary_jobs = _SummaryJobsLater()
        self.resume_tokens = _ResumeTokensLater()
        self.exports = _ExportsLater()

    def transaction(self) -> AbstractAsyncContextManager[Transaction]:
        return self._transaction()

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[Transaction]:
        """Commits on clean exit unless already committed; rolls back on an exception."""
        tx = MemoryTransaction()
        try:
            yield tx
        except BaseException:
            await tx.rollback()
            raise
        else:
            if not tx.committed:
                await tx.commit()

    async def check_ready(self) -> bool:
        return True
