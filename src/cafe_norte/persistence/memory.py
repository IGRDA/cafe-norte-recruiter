"""In-memory Store for offline tests and local runs. Same semantics, one process, no durability.

Writes taken through a transaction are buffered and applied on ``commit``; conditional checks
(revision, uniqueness) run again at commit time so a conflict surfaces exactly where Postgres
would raise it. Repositories of later stages come from ``later.py`` and raise
``NotImplementedError``.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import partial

from cafe_norte.domain.contracts import (
    Booking,
    ConfigId,
    Confirmation,
    InterviewSlot,
    SessionId,
    SessionState,
    SlotId,
    TurnId,
)
from cafe_norte.errors import ServiceError
from cafe_norte.observability.contracts import StageTiming, UsageRecord, VersionStamp
from cafe_norte.persistence.contracts import (
    SNAPSHOT_TURNS,
    EventRecord,
    Lease,
    SessionSnapshot,
    Transaction,
    TurnRecord,
)
from cafe_norte.persistence.export import confirmations_from_events
from cafe_norte.persistence.later import SummaryJobsLater


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
        self._seq: dict[SessionId, int] = {}
        self.fence: Callable[[SessionId, int], bool] = lambda session_id, generation: True
        self.cascade: list[Callable[[SessionId], None]] = []  # what delete takes with it
        self.fail_next_save: ServiceError | None = None  # a scripted outage, for one save

    def _fenced(self, session_id: SessionId, lease_generation: int | None) -> None:
        if lease_generation is not None and not self.fence(session_id, lease_generation):
            raise ServiceError("stale lease", code="conflict")

    async def create(self, state: SessionState, *, access_hash: str) -> None:
        if state.session_id in self._states:
            raise ServiceError("session exists", code="conflict")
        self._states[state.session_id] = state

    async def get(self, session_id: SessionId) -> SessionState | None:
        return self._states.get(session_id)

    async def save(
        self,
        tx: Transaction,
        state: SessionState,
        *,
        expected_revision: int,
        lease_generation: int | None = None,
    ) -> None:
        if self.fail_next_save is not None:  # raised at the call, as a dropped connection is
            error, self.fail_next_save = self.fail_next_save, None
            raise error

        def apply() -> None:
            current = self._states.get(state.session_id)
            if current is None:
                raise ServiceError("session missing", code="not_found")
            if current.candidate.revision != expected_revision:
                raise ServiceError("revision mismatch", code="conflict")
            self._fenced(state.session_id, lease_generation)
            self._states[state.session_id] = state

        _tx(tx).enlist(apply)

    async def next_seq(
        self, tx: Transaction, session_id: SessionId, *, lease_generation: int | None = None
    ) -> int:
        """Counted at once, not at commit: a rolled-back transaction leaves a gap, which the
        sequence tolerates (``since`` asks for "after seq", never "exactly seq")."""
        if session_id not in self._states:
            raise ServiceError("session missing", code="not_found")
        self._fenced(session_id, lease_generation)
        self._seq[session_id] = self._seq.get(session_id, 0) + 1
        return self._seq[session_id]

    async def delete(self, session_id: SessionId) -> None:
        self._states.pop(session_id, None)
        self._seq.pop(session_id, None)
        for forget in self.cascade:
            forget(session_id)

    async def expired(self, before: datetime, limit: int) -> tuple[SessionId, ...]:
        """Sessions created before ``before``, oldest first: what retention deletes."""
        old = sorted(
            (s for s in self._states.values() if s.created_at < before), key=lambda s: s.created_at
        )
        return tuple(s.session_id for s in old[:limit])

    async def count_created_since(self, since: datetime) -> int:
        return sum(1 for s in self._states.values() if s.created_at >= since)


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

    def forget(self, session_id: SessionId) -> None:
        self._turns.pop(session_id, None)

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

    def forget(self, session_id: SessionId) -> None:
        self._events.pop(session_id, None)
        self.usage = [u for u in self.usage if u.session_id != session_id]
        self.timings = [t for t in self.timings if t.session_id != session_id]

    def last_seq(self, session_id: SessionId) -> int:
        events = self._events.get(session_id, [])
        return events[-1].seq if events else 0

    def all(self, session_id: SessionId) -> tuple[EventRecord, ...]:
        return tuple(self._events.get(session_id, []))

    async def record_usage(self, tx: Transaction, usage: UsageRecord) -> None:
        _tx(tx).enlist(lambda: self.usage.append(usage))

    async def record_timing(self, tx: Transaction, timing: StageTiming) -> None:
        _tx(tx).enlist(lambda: self.timings.append(timing))


class MemoryCalendar:
    """Slots and bookings of one process. ``clock`` stands in for Postgres ``now()`` on the
    committed booking; the uniqueness checks run on enlist and again on commit."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._slots: dict[SlotId, InterviewSlot] = {}
        self._by_key: dict[str, Booking] = {}
        self._by_session: dict[SessionId, Booking] = {}

    async def seed(self, slots: Sequence[InterviewSlot]) -> None:
        """Insert unknown slots; an existing one, occupied or not, is left as it is."""
        for slot in slots:
            self._slots.setdefault(slot.slot_id, slot)

    async def available(
        self, config_id: ConfigId, *, after: datetime, limit: int
    ) -> tuple[InterviewSlot, ...]:
        free = sorted(
            (
                s
                for s in self._slots.values()
                if s.config_id == config_id and s.status == "available" and s.starts_at_utc > after
            ),
            key=lambda s: s.starts_at_utc,
        )
        return tuple(free[:limit])

    async def get(self, slot_id: SlotId) -> InterviewSlot | None:
        return self._slots.get(slot_id)

    def _refusal(self, slot_id: SlotId, session_id: SessionId) -> str | None:
        slot = self._slots.get(slot_id)
        if slot is None or slot.status != "available":
            return "slot taken"
        if session_id in self._by_session:
            return "session already booked"
        return None

    async def reserve(
        self,
        tx: Transaction,
        slot_id: SlotId,
        session_id: SessionId,
        confirmation: Confirmation,
        idempotency_key: str,
    ) -> Booking:
        """The same key returns the original booking; a taken slot or a second booking for the
        session is a ``conflict``, checked now and again at commit."""
        known = self._by_key.get(idempotency_key)
        if known is not None:
            return known
        refusal = self._refusal(slot_id, session_id)
        if refusal is not None:
            raise ServiceError(refusal, code="conflict")
        slot = self._slots[slot_id]
        booking = Booking(
            slot_id=slot_id,
            config_id=slot.config_id,
            starts_at_utc=slot.starts_at_utc,
            confirmation_id=confirmation.confirmation_id,
            idempotency_key=idempotency_key,
            committed_at=self._clock(),
        )

        def apply() -> None:
            refusal = self._refusal(slot_id, session_id)
            if refusal is not None:
                raise ServiceError(refusal, code="conflict")
            self._slots[slot_id] = slot.model_copy(update={"status": "reserved"})
            self._by_key[idempotency_key] = booking
            self._by_session[session_id] = booking

        _tx(tx).enlist(apply)
        return booking

    async def booking_by_key(self, idempotency_key: str) -> Booking | None:
        return self._by_key.get(idempotency_key)

    def forget(self, session_id: SessionId) -> None:
        """The session's simulated reservation goes with it; the slot is free again."""
        booking = self._by_session.pop(session_id, None)
        if booking is None:
            return
        del self._by_key[booking.idempotency_key]
        slot = self._slots[booking.slot_id]
        self._slots[booking.slot_id] = slot.model_copy(update={"status": "available"})


class MemoryLeases:
    """One lease per session; ``clock`` decides expiry, as ``now()`` does in Postgres."""

    def __init__(self, clock: Callable[[], datetime], sessions: MemorySessions) -> None:
        self._clock = clock
        self._sessions = sessions
        self._leases: dict[SessionId, Lease] = {}

    def _live(self, session_id: SessionId) -> Lease | None:
        lease = self._leases.get(session_id)
        return lease if lease is not None and lease.expires_at > self._clock() else None

    async def claim(self, session_id: SessionId, owner: str, ttl_seconds: int) -> Lease | None:
        if session_id not in self._sessions._states:
            return None
        live = self._live(session_id)
        if live is not None and live.owner != owner:
            return None
        previous = self._leases.get(session_id)
        lease = Lease(
            session_id=session_id,
            owner=owner,
            generation=(previous.generation if previous else 0) + 1,
            expires_at=self._clock() + timedelta(seconds=ttl_seconds),
        )
        self._leases[session_id] = lease
        return lease

    async def renew(self, lease: Lease, ttl_seconds: int) -> Lease | None:
        live = self._live(lease.session_id)
        if live != lease:
            return None
        renewed = lease.model_copy(
            update={"expires_at": self._clock() + timedelta(seconds=ttl_seconds)}
        )
        self._leases[lease.session_id] = renewed
        return renewed

    async def release(self, lease: Lease) -> None:
        """Expire, never forget: the generation keeps growing across claims."""
        if self._leases.get(lease.session_id) == lease:
            self._leases[lease.session_id] = lease.model_copy(update={"expires_at": self._clock()})

    def forget(self, session_id: SessionId) -> None:
        self._leases.pop(session_id, None)

    def generation_is_live(self, session_id: SessionId, generation: int) -> bool:
        live = self._live(session_id)
        return live is not None and live.generation == generation


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

    async def release_left_over(self) -> int:
        left_over = len(self._active)
        self._active.clear()
        return left_over

    @property
    def active(self) -> frozenset[SessionId]:
        return frozenset(self._active)

    def forget(self, session_id: SessionId) -> None:
        self._active.pop(session_id, None)


class MemoryResumeTokens:
    def __init__(self) -> None:
        self._tokens: dict[str, tuple[SessionId, datetime]] = {}

    async def issue(self, session_id: SessionId, token_hash: str, expires_at: datetime) -> None:
        if token_hash in self._tokens:
            raise ServiceError("token exists", code="conflict")
        self._tokens[token_hash] = (session_id, expires_at)

    async def redeem(self, token_hash: str, now: datetime) -> SessionId | None:
        found = self._tokens.get(token_hash)
        if found is None or found[1] <= now:
            return None
        return found[0]

    def forget(self, session_id: SessionId) -> None:
        self._tokens = {h: v for h, v in self._tokens.items() if v[0] != session_id}


class MemoryExports:
    def __init__(self) -> None:
        self._snapshots: dict[SessionId, str] = {}

    async def write_snapshot(self, tx: Transaction, session_id: SessionId, json_text: str) -> None:
        _tx(tx).enlist(lambda: self._snapshots.__setitem__(session_id, json_text))

    async def read_snapshot(self, session_id: SessionId) -> str | None:
        return self._snapshots.get(session_id)

    def forget(self, session_id: SessionId) -> None:
        self._snapshots.pop(session_id, None)


class MemoryStore:
    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.sessions = MemorySessions()
        self.turns = MemoryTurns()
        self.events = MemoryEvents()
        self.calendar = MemoryCalendar(clock)
        self.leases = MemoryLeases(clock, self.sessions)
        self.sessions.fence = self.leases.generation_is_live
        self.admission = MemoryAdmission()
        self.summary_jobs = SummaryJobsLater()
        self.resume_tokens = MemoryResumeTokens()
        self.exports = MemoryExports()
        self._maintaining = False
        self.sessions.cascade = [
            self.turns.forget,
            self.events.forget,
            self.calendar.forget,
            self.leases.forget,
            self.admission.forget,
            self.resume_tokens.forget,
            self.exports.forget,
        ]

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

    async def open(self) -> None:
        """Nothing to connect to."""

    async def close(self) -> None:
        """Nothing to release."""

    async def check_ready(self) -> bool:
        return True

    def maintenance(self) -> AbstractAsyncContextManager[bool]:
        return self._maintenance()

    @asynccontextmanager
    async def _maintenance(self) -> AsyncIterator[bool]:
        if self._maintaining:
            yield False
            return
        self._maintaining = True
        try:
            yield True
        finally:
            self._maintaining = False

    async def snapshot(
        self, session_id: SessionId, *, versions: VersionStamp, taken_at: datetime
    ) -> SessionSnapshot | None:
        state = await self.sessions.get(session_id)
        if state is None:
            return None
        events = self.events.all(session_id)
        return SessionSnapshot(
            state=state,
            turns=await self.turns.recent(session_id, SNAPSHOT_TURNS),
            confirmations=confirmations_from_events(events),
            events=events,
            usage=tuple(u for u in self.events.usage if u.session_id == session_id),
            timings=tuple(t for t in self.events.timings if t.session_id == session_id),
            versions=versions,
            taken_at=taken_at,
        )
