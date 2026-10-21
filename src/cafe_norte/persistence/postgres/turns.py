"""Turns: appended in order, read back by insertion order, the assistant record updated with
what was actually played."""

from cafe_norte.domain.contracts import SessionId, TurnId
from cafe_norte.persistence.contracts import Transaction, TurnRecord
from cafe_norte.persistence.postgres.codecs import TURN_COLUMNS, turn_from_row, turn_params
from cafe_norte.persistence.postgres.support import (
    Connect,
    Connection,
    connection,
    fetch_all,
    reading,
)


async def select_turns(
    conn: Connection, session_id: SessionId, limit: int
) -> tuple[TurnRecord, ...]:
    """The last ``limit`` turns in chronological order."""
    if limit <= 0:
        return ()
    rows = await fetch_all(
        conn,
        f"select {TURN_COLUMNS} from turns where session_id = %s order by id desc limit %s",
        (session_id, limit),
    )
    return tuple(turn_from_row(row) for row in reversed(rows))


class PostgresTurns:
    def __init__(self, connect: Connect) -> None:
        self._connect = connect

    async def append(self, tx: Transaction, turn: TurnRecord) -> None:
        await connection(tx).execute(
            f"insert into turns ({TURN_COLUMNS}) values ("
            "%(turn_id)s, %(session_id)s, %(input_id)s, %(role)s, %(channel)s, %(language)s, "
            "%(text)s, %(delivered_text)s, %(interrupted)s, %(started_at)s, %(finished_at)s)",
            turn_params(turn),
        )

    async def recent(self, session_id: SessionId, limit: int) -> tuple[TurnRecord, ...]:
        async with reading(self._connect) as conn:
            return await select_turns(conn, session_id, limit)

    async def mark_delivered(
        self,
        tx: Transaction,
        session_id: SessionId,
        turn_id: TurnId,
        *,
        delivered_text: str,
        interrupted: bool,
    ) -> None:
        await connection(tx).execute(
            "update turns set delivered_text = %s, interrupted = %s "
            "where session_id = %s and turn_id = %s and role = 'assistant'",
            (delivered_text, interrupted, session_id, turn_id),
        )
