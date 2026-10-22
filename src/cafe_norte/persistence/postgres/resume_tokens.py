"""Reusable private resume tokens: store only hashes and reject tokens after expiry."""

from datetime import datetime

from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.postgres.support import Connect, fetch_one, writing


class PostgresResumeTokens:
    def __init__(self, connect: Connect) -> None:
        self._connect = connect

    async def issue(self, session_id: SessionId, token_hash: str, expires_at: datetime) -> None:
        async with writing(self._connect) as conn:
            await conn.execute(
                "insert into resume_tokens (token_hash, session_id, expires_at) "
                "values (%s, %s, %s)",
                (token_hash, session_id, expires_at),
            )

    async def redeem(self, token_hash: str, now: datetime) -> SessionId | None:
        """The session of a live token, recording the first redemption; ``None`` otherwise."""
        async with writing(self._connect) as conn:
            row = await fetch_one(
                conn,
                "update resume_tokens set redeemed_at = coalesce(redeemed_at, %(now)s) "
                "where token_hash = %(token_hash)s and expires_at > %(now)s returning session_id",
                {"token_hash": token_hash, "now": now},
            )
        return None if row is None else SessionId(row["session_id"])
