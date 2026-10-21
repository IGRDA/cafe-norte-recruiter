"""The export snapshot stored when a session closes: one JSONB document per session."""

import json

from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.contracts import Transaction
from cafe_norte.persistence.postgres.support import Connect, connection, fetch_one, reading


class PostgresExports:
    def __init__(self, connect: Connect) -> None:
        self._connect = connect

    async def write_snapshot(self, tx: Transaction, session_id: SessionId, json_text: str) -> None:
        """Upsert: a session closed again (a correction, then another close) keeps the latest."""
        version = str(json.loads(json_text).get("schema_version", ""))
        await connection(tx).execute(
            "insert into exports (session_id, schema_version, snapshot, taken_at) "
            "values (%s, %s, %s::jsonb, now()) on conflict (session_id) do update "
            "set schema_version = excluded.schema_version, snapshot = excluded.snapshot, "
            "taken_at = now()",
            (session_id, version, json_text),
        )

    async def read_snapshot(self, session_id: SessionId) -> str | None:
        async with reading(self._connect) as conn:
            row = await fetch_one(
                conn,
                "select snapshot::text as snapshot from exports where session_id = %s",
                (session_id,),
            )
        return None if row is None else str(row["snapshot"])
