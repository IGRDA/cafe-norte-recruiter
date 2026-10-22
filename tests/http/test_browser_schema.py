"""The page's TypeScript types come from one JSON Schema of the API contracts (D61)."""

import json

from cafe_norte.api.contracts import browser_schema
from tests.support import ROOT


def test_browser_schema_file_matches_the_contracts() -> None:
    """The page's TypeScript types are generated from this file (D61); web's own test checks
    the generated types against it."""
    on_disk = json.loads((ROOT / "web" / "src" / "api" / "contracts.schema.json").read_text())
    assert on_disk == browser_schema(), "run `make export-schema`"


def test_browser_schema_requires_every_field_the_page_reads() -> None:
    definitions = browser_schema()["$defs"]
    event = definitions["TurnStarted"]
    assert set(event["required"]) == set(event["properties"])  # ``type`` narrows the union
    assert "expected_revision" not in definitions["TurnRequest"]["required"]  # a request default
    assert all("title" not in field for field in event["properties"].values())
