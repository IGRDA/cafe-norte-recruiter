"""The Postgres-backed suite can reach its database. Keeps the CI service container honest
until the first repository tests land; skipped without CAFE_NORTE_TEST_DATABASE_URL."""

import psycopg
import pytest

pytestmark = pytest.mark.postgres


async def test_database_answers_and_is_postgres_16(test_database_url: str) -> None:
    async with await psycopg.AsyncConnection.connect(test_database_url) as conn:
        row = await (
            await conn.execute("select current_setting('server_version_num')::int")
        ).fetchone()
    assert row is not None and row[0] >= 160000
