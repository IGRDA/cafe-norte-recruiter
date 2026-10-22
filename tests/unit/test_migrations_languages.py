"""The database language constraint must accept every language supported by the runtime."""

import re

from cafe_norte.errors import SWITCHABLE
from tests.support import ROOT

MIGRATIONS = ROOT / "src" / "cafe_norte" / "persistence" / "migrations"


def test_the_latest_turns_language_check_lists_every_switchable_language() -> None:
    checks = [
        match
        for path in sorted(MIGRATIONS.glob("*.sql"))
        for match in re.findall(r"language in \(([^)]*)\)", path.read_text())
    ]
    latest = {code.strip().strip("'") for code in checks[-1].split(",")}
    assert latest == set(SWITCHABLE), "add a migration that widens turns_language_check"
