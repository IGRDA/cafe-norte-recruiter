"""Apply ``migrations/*.sql`` in order, once, under an advisory lock.

``PostgresStore.open()`` calls ``apply_pending`` before serving; ``python -m
cafe_norte.persistence.migrate`` runs the same function by hand from ``CAFE_NORTE_DATABASE_URL``.
The applier bootstraps ``schema_migrations`` itself, since it must read that table before it can
apply ``0001``. Each file runs in one transaction with the simple query protocol (no parameters),
so a file may hold several statements; a failure rolls that file back and stops."""

import asyncio
import os
import sys
from collections.abc import Collection, Sequence
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
LOCK_KEY = 7_423_001  # one advisory lock for every applier of this database

BOOTSTRAP = """
create table if not exists schema_migrations (
    name text primary key,
    applied_at timestamptz not null default now()
)
"""


def migration_files(directory: Path) -> tuple[Path, ...]:
    """Every ``*.sql`` file of the directory, by name: ``0001_…`` before ``0002_…``."""
    return tuple(sorted(directory.glob("*.sql"), key=lambda path: path.name))


def pending(files: Sequence[Path], applied: Collection[str]) -> tuple[Path, ...]:
    """The files not yet recorded, in order. Pure."""
    return tuple(path for path in files if path.name not in applied)


async def apply_pending(dsn: str, directory: Path = MIGRATIONS_DIR) -> tuple[str, ...]:
    """Return the names applied in this run."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute("select pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            await conn.execute(BOOTSTRAP)
            rows = await (await conn.execute("select name from schema_migrations")).fetchall()
            await conn.commit()
            applied: list[str] = []
            for path in pending(migration_files(directory), {row[0] for row in rows}):
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute("insert into schema_migrations (name) values (%s)", (path.name,))
                await conn.commit()
                applied.append(path.name)
            return tuple(applied)
        finally:
            await conn.rollback()  # a failed file leaves an aborted transaction behind
            await conn.execute("select pg_advisory_unlock(%s)", (LOCK_KEY,))
            await conn.commit()


def main() -> int:
    dsn = os.environ.get("CAFE_NORTE_DATABASE_URL")
    if not dsn:
        print("CAFE_NORTE_DATABASE_URL is not set", file=sys.stderr)
        return 2
    applied = asyncio.run(apply_pending(dsn))
    print("\n".join(applied) if applied else "nothing to apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
