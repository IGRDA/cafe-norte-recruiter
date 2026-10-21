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
    fetch_one,
    reading,
    writing,
)


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

    async def save(self, tx: Transaction, state: SessionState, *, expected_revision: int) -> None:
        conn = connection(tx)
        cursor = await conn.execute(
            "update sessions set state_json = %s::jsonb, updated_at = now() "
            "where session_id = %s and revision = %s",
            (state.model_dump_json(), state.session_id, expected_revision),
        )
        if cursor.rowcount == 1:
            return
        exists = await fetch_one(
            conn, "select 1 from sessions where session_id = %s", (state.session_id,)
        )
        if exists is None:
            raise ServiceError("session missing", code="not_found")
        raise ServiceError("revision mismatch", code="conflict")

    async def next_seq(self, tx: Transaction, session_id: SessionId) -> int:
        row = await fetch_one(
            connection(tx),
            "update sessions set next_seq = next_seq + 1 where session_id = %s returning next_seq",
            (session_id,),
        )
        if row is None:
            raise ServiceError("session missing", code="not_found")
        return int(row["next_seq"])

    async def delete(self, session_id: SessionId) -> None:
        async with writing(self._connect) as conn:
            await conn.execute("delete from sessions where session_id = %s", (session_id,))

    async def expired(self, before: datetime, limit: int) -> tuple[SessionId, ...]:
        raise NotImplementedError  # retention stage
