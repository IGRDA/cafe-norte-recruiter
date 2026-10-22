"""Session ownership leases: one row per session, claimed while nobody else holds it live,
with a generation that fences every write made under it."""

from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.contracts import Lease
from cafe_norte.persistence.postgres.codecs import LEASE_COLUMNS, lease_from_row
from cafe_norte.persistence.postgres.support import Connect, fetch_one, writing


class PostgresLeases:
    def __init__(self, connect: Connect) -> None:
        self._connect = connect

    async def claim(self, session_id: SessionId, owner: str, ttl_seconds: int) -> Lease | None:
        """Succeeds when the session exists and no live lease of another owner exists; the
        generation grows by one on every claim. One statement, so two claimers cannot both win."""
        async with writing(self._connect) as conn:
            row = await fetch_one(
                conn,
                "insert into leases (session_id, owner, generation, expires_at) "
                "select session_id, %(owner)s, 1, now() + %(ttl)s * interval '1 second' "
                "from sessions where session_id = %(session_id)s "
                "on conflict (session_id) do update set owner = excluded.owner, "
                "generation = leases.generation + 1, expires_at = excluded.expires_at "
                "where leases.expires_at <= now() or leases.owner = excluded.owner "
                f"returning {LEASE_COLUMNS}",
                {"session_id": session_id, "owner": owner, "ttl": ttl_seconds},
            )
        return None if row is None else lease_from_row(row)

    async def release(self, lease: Lease) -> None:
        """Expire, never delete: the generation keeps growing, so a writer fenced on an old
        one can never pass again."""
        async with writing(self._connect) as conn:
            await conn.execute(
                "update leases set expires_at = now() where session_id = %(session_id)s "
                "and owner = %(owner)s and generation = %(generation)s",
                lease.model_dump(),
            )
