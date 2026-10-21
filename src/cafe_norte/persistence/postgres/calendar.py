"""The simulated calendar: a slot is taken exactly when a booking row names it, and the
reservation is decided under the slot's row lock."""

from collections.abc import Sequence
from datetime import datetime

from cafe_norte.domain.contracts import (
    Booking,
    ConfigId,
    Confirmation,
    InterviewSlot,
    SessionId,
    SlotId,
)
from cafe_norte.errors import ServiceError
from cafe_norte.persistence.contracts import Transaction
from cafe_norte.persistence.postgres.codecs import (
    BOOKING_COLUMNS,
    SLOT_COLUMNS,
    booking_from_row,
    slot_from_row,
    slot_params,
)
from cafe_norte.persistence.postgres.support import (
    Connect,
    Connection,
    connection,
    fetch_all,
    fetch_one,
    reading,
    writing,
)

SLOT_WITH_BOOKING = "from interview_slots s left join bookings b on b.slot_id = s.slot_id"
BOOKING_WITH_SLOT = "from bookings b join interview_slots s on s.slot_id = b.slot_id"


async def select_booking_by_key(conn: Connection, idempotency_key: str) -> Booking | None:
    row = await fetch_one(
        conn,
        f"select {BOOKING_COLUMNS} {BOOKING_WITH_SLOT} where b.idempotency_key = %s",
        (idempotency_key,),
    )
    return None if row is None else booking_from_row(row)


class PostgresCalendar:
    def __init__(self, connect: Connect) -> None:
        self._connect = connect

    async def seed(self, slots: Sequence[InterviewSlot]) -> None:
        """Insert unknown slots; an existing one, booked or not, is left as it is."""
        async with writing(self._connect) as conn:
            async with conn.cursor() as cursor:
                await cursor.executemany(
                    "insert into interview_slots "
                    "(slot_id, config_id, starts_at_utc, duration_minutes) values "
                    "(%(slot_id)s, %(config_id)s, %(starts_at_utc)s, %(duration_minutes)s) "
                    "on conflict (slot_id) do nothing",
                    [slot_params(slot) for slot in slots],
                )

    async def available(
        self, config_id: ConfigId, *, after: datetime, limit: int
    ) -> tuple[InterviewSlot, ...]:
        async with reading(self._connect) as conn:
            rows = await fetch_all(
                conn,
                f"select {SLOT_COLUMNS} {SLOT_WITH_BOOKING} where s.config_id = %s "
                "and s.starts_at_utc > %s and b.slot_id is null order by s.starts_at_utc limit %s",
                (config_id, after, limit),
            )
        return tuple(slot_from_row(row) for row in rows)

    async def get(self, slot_id: SlotId) -> InterviewSlot | None:
        async with reading(self._connect) as conn:
            row = await fetch_one(
                conn, f"select {SLOT_COLUMNS} {SLOT_WITH_BOOKING} where s.slot_id = %s", (slot_id,)
            )
        return None if row is None else slot_from_row(row)

    async def reserve(
        self,
        tx: Transaction,
        slot_id: SlotId,
        session_id: SessionId,
        confirmation: Confirmation,
        idempotency_key: str,
    ) -> Booking:
        """Lock the slot row, then decide: the same key returns the original booking, a taken
        slot or a second booking for the session is a ``conflict``. A concurrent reserver waits
        on the lock and sees the winner's row."""
        conn = connection(tx)
        locked = await fetch_one(
            conn, "select slot_id from interview_slots where slot_id = %s for update", (slot_id,)
        )
        if locked is None:
            raise ServiceError("slot taken", code="conflict")
        known = await select_booking_by_key(conn, idempotency_key)
        if known is not None:
            return known
        taken = await fetch_one(conn, "select 1 from bookings where slot_id = %s", (slot_id,))
        if taken is not None:
            raise ServiceError("slot taken", code="conflict")
        row = await fetch_one(
            conn,
            "with booked as ("
            "  insert into bookings (session_id, slot_id, confirmation_id, idempotency_key) "
            "  values (%s, %s, %s, %s) returning *) "
            f"select {BOOKING_COLUMNS} from booked b "
            "join interview_slots s on s.slot_id = b.slot_id",
            (session_id, slot_id, confirmation.confirmation_id, idempotency_key),
        )
        assert row is not None  # an insert with returning always yields its row
        return booking_from_row(row)

    async def booking_by_key(self, idempotency_key: str) -> Booking | None:
        async with reading(self._connect) as conn:
            return await select_booking_by_key(conn, idempotency_key)
