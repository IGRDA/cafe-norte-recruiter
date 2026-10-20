"""Apply ``migrations/*.sql`` in order, once, under an advisory lock.

``python -m cafe_norte.persistence.migrate`` reads ``CAFE_NORTE_DATABASE_URL``. CI runs it with
the migration role before switching traffic; a failure prevents promotion."""

from pathlib import Path

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


async def apply_pending(dsn: str, directory: Path = MIGRATIONS_DIR) -> tuple[str, ...]:
    """Return the names applied in this run."""
    raise NotImplementedError


def main() -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
