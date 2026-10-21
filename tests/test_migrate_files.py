"""The migration files and the pure half of the applier: ordered, numbered, applied once."""

import re
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.persistence.migrate import MIGRATIONS_DIR, migration_files, pending

NAME = re.compile(r"^\d{4}_[a-z0-9_]+\.sql$")


def test_migration_files_are_numbered_consecutively_from_0001() -> None:
    files = migration_files(MIGRATIONS_DIR)
    assert files, "no migration files"
    assert all(NAME.match(f.name) for f in files)
    assert [int(f.name[:4]) for f in files] == list(range(1, len(files) + 1))


def test_migration_files_are_sorted_by_name_whatever_the_directory_order(tmp_path: Path) -> None:
    for name in ("0002_b.sql", "0001_a.sql", "notes.md", "0003_c.sql"):
        (tmp_path / name).write_text("select 1;")
    assert [f.name for f in migration_files(tmp_path)] == ["0001_a.sql", "0002_b.sql", "0003_c.sql"]


@given(st.lists(st.text(min_size=1), unique=True), st.frozensets(st.text(min_size=1)))
def test_pending_keeps_the_order_and_drops_what_was_applied(
    names: list[str], applied: frozenset[str]
) -> None:
    files = tuple(Path(n) for n in names)
    assert pending(files, applied) == tuple(f for f in files if f.name not in applied)
