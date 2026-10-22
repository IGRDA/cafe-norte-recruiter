"""The applier against a real database: from scratch, once, recorded."""

from pathlib import Path

import psycopg
import pytest

from cafe_norte.persistence.migrate import apply_pending, main

pytestmark = pytest.mark.postgres

MIGRATIONS = (
    "0001_initial.sql",
    "0002_leases_admission_resume.sql",
    "0003_exports_and_cascades.sql",
    "0004_admission_owner.sql",
    "0005_turn_languages.sql",
)
TABLES = {
    "sessions",
    "turns",
    "events",
    "interview_slots",
    "bookings",
    "usage",
    "timings",
    "leases",
    "admission",
    "resume_tokens",
    "exports",
}


async def tables(url: str) -> set[str]:
    async with await psycopg.AsyncConnection.connect(url) as conn:
        rows = await (
            await conn.execute(
                "select table_name from information_schema.tables where table_schema = 'public'"
            )
        ).fetchall()
    return {row[0] for row in rows}


async def test_apply_pending_creates_the_schema_once_and_records_it(empty_database: str) -> None:
    assert await apply_pending(empty_database) == MIGRATIONS
    assert TABLES | {"schema_migrations"} <= await tables(empty_database)
    assert await apply_pending(empty_database) == ()
    async with await psycopg.AsyncConnection.connect(empty_database) as conn:
        rows = await (await conn.execute("select name from schema_migrations")).fetchall()
    assert tuple(row[0] for row in rows) == MIGRATIONS


async def test_a_failing_file_is_rolled_back_and_the_lock_is_released(
    empty_database: str, tmp_path: Path
) -> None:
    (tmp_path / "0001_ok.sql").write_text("create table ok (id int);")
    (tmp_path / "0002_bad.sql").write_text("create table bad (id int); select no_such_thing();")
    with pytest.raises(psycopg.Error):
        await apply_pending(empty_database, tmp_path)
    assert "ok" in await tables(empty_database) and "bad" not in await tables(empty_database)
    (tmp_path / "0002_bad.sql").write_text("create table bad (id int);")
    assert await apply_pending(empty_database, tmp_path) == ("0002_bad.sql",)


def test_main_needs_the_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAFE_NORTE_DATABASE_URL", raising=False)
    assert main() == 2
