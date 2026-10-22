"""Sessions: one JSONB document per session, a conditional update on its revision, and the
event sequence the store hands out."""

from datetime import datetime

from cafe_norte.domain.contracts import SessionId, SessionState
from cafe_norte.errors import ServiceError
from cafe_norte.persistence.contracts import Transaction
from cafe_norte.persistence.postgres.codecs import session_params, state_from_row
from cafe_norte.persistence.postgres.support import (
    Connect,
    Connection,
    connection,
    fetch_all,
    fetch_one,
    reading,
    writing,
)

# With a generation, the write also needs a live lease of that generation.
FENCE = (
    "and (%(generation)s::integer is null or exists (select 1 from leases l "
    "where l.session_id = sessions.session_id and l.generation = %(generation)s "
    "and l.expires_at > now()))"
)


async def _refusal(conn: Connection, session_id: SessionId) -> ServiceError:
    """Why a conditional write touched no row: the session is missing, or the revision or the
    lease it was fenced on is stale."""
    exists = await fetch_one(conn, "select 1 from sessions where session_id = %s", (session_id,))
    if exists is None:
        return ServiceError("session missing", code="not_found")
    return ServiceError("revision or lease mismatch", code="conflict")


async def select_state(conn: Connection, session_id: SessionId) -> SessionState | None:
    row = await fetch_one(
        conn, "select state_json from sessions where session_id = %s", (session_id,)
    )
    return None if row is None else state_from_row(row)


class PostgresSessions:
    def __init__(self, connect: Connect) -> None:
        self._connect = connect

    async def create(self, state: SessionState, *, access_hash: str) -> None:
        async with writing(self._connect) as conn:
            await conn.execute(
                "insert into sessions (session_id, state_json, access_hash, created_at) "
                "values (%(session_id)s, %(state_json)s::jsonb, %(access_hash)s, %(created_at)s)",
                session_params(state, access_hash=access_hash),
            )

    async def get(self, session_id: SessionId) -> SessionState | None:
        async with reading(self._connect) as conn:
            return await select_state(conn, session_id)

    async def save(
        self,
        tx: Transaction,
        state: SessionState,
        *,
        expected_revision: int,
        lease_generation: int | None = None,
    ) -> None:
        conn = connection(tx)
        cursor = await conn.execute(
            "update sessions set state_json = %(state_json)s::jsonb, updated_at = now() "
            f"where session_id = %(session_id)s and revision = %(revision)s {FENCE}",
            {
                "state_json": state.model_dump_json(),
                "session_id": state.session_id,
                "revision": expected_revision,
                "generation": lease_generation,
            },
        )
        if cursor.rowcount == 1:
            return
        raise await _refusal(conn, state.session_id)

    async def next_seq(
        self, tx: Transaction, session_id: SessionId, *, lease_generation: int | None = None
    ) -> int:
        conn = connection(tx)
        row = await fetch_one(
            conn,
            "update sessions set next_seq = next_seq + 1 "
            f"where session_id = %(session_id)s {FENCE} returning next_seq",
            {"session_id": session_id, "generation": lease_generation},
        )
        if row is None:
            raise await _refusal(conn, session_id)
        return int(row["next_seq"])

    async def delete(self, session_id: SessionId) -> None:
        async with writing(self._connect) as conn:
            await conn.execute("delete from sessions where session_id = %s", (session_id,))

    async def expired(self, before: datetime, limit: int) -> tuple[SessionId, ...]:
        """Sessions created before ``before``, oldest first: what retention deletes."""
        async with reading(self._connect) as conn:
            rows = await fetch_all(
                conn,
                "select session_id from sessions where created_at < %s "
                "order by created_at limit %s",
                (before, limit),
            )
        return tuple(SessionId(row["session_id"]) for row in rows)
