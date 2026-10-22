"""Voice admission as rows: a place is held from ``acquire`` until ``release`` or until the row
is older than the admission ttl, so a crashed container frees its place by itself. Each row
names the instance that acquired it, so a restarted instance releases its own left-over places
at once instead of waiting for the ttl (D55)."""

from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.postgres.support import Connect, fetch_one, writing


class PostgresAdmission:
    def __init__(self, connect: Connect, *, ttl_seconds: float, owner: str) -> None:
        self._connect = connect
        self._ttl_seconds = ttl_seconds
        self._owner = owner

    async def acquire(self, session_id: SessionId, *, max_active: int, reserve_eur: float) -> bool:
        """Count under a table lock, so two acquirers cannot both see a free place."""
        async with writing(self._connect) as conn:
            await conn.execute("lock table admission in share row exclusive mode")
            params = {
                "session_id": session_id,
                "ttl": self._ttl_seconds,
                "max_active": max_active,
                "reserve_eur": reserve_eur,
                "owner": self._owner,
            }
            held = await fetch_one(
                conn,
                "select 1 from admission where session_id = %(session_id)s "
                "and released_at is null "
                "and acquired_at > now() - %(ttl)s * interval '1 second'",
                params,
            )
            if held is not None:
                return True
            row = await fetch_one(
                conn,
                "insert into admission (session_id, reserved_eur, owner) "
                "select %(session_id)s, %(reserve_eur)s, %(owner)s where ("
                "  select count(*) from admission where released_at is null "
                "  and acquired_at > now() - %(ttl)s * interval '1 second'"
                ") < %(max_active)s returning id",
                params,
            )
            return row is not None

    async def release(self, session_id: SessionId, *, actual_eur: float) -> None:
        async with writing(self._connect) as conn:
            await conn.execute(
                "update admission set released_at = now(), actual_eur = %s "
                "where session_id = %s and released_at is null",
                (actual_eur, session_id),
            )

    async def release_left_over(self) -> int:
        async with writing(self._connect) as conn:
            cursor = await conn.execute(
                "update admission set released_at = now() where owner = %s and released_at is null",
                (self._owner,),
            )
            return cursor.rowcount
