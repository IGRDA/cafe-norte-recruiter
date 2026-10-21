"""The export schema is generated from the Pydantic model, and the tool schemas from the args."""

import json
from pathlib import Path

from cafe_norte.conversation.tools import ARGUMENT_MODELS, tool_schemas
from cafe_norte.persistence.export import ExportDocument

ROOT = Path(__file__).resolve().parents[1]


def test_export_schema_file_matches_the_model() -> None:
    generated = ExportDocument.model_json_schema()
    on_disk = json.loads((ROOT / "examples" / "session_export.schema.json").read_text())
    assert on_disk == generated, "run `make export-schema`"


def test_example_export_is_a_complete_s01_session() -> None:
    """`make export-example` regenerates it; ids are random, so the check is on content."""
    document = ExportDocument.model_validate_json(
        (ROOT / "examples" / "session_export.example.json").read_text()
    )
    assert document.schema_version == "1"
    assert (document.session.lifecycle, document.session.outcome) == ("completed", "reserved")
    assert document.session.ended_at is not None
    confirmed = {c.target.kind for c in document.confirmations if c.status == "confirmed"}
    assert confirmed == {"field", "brief", "slot"}
    assert document.summary.brief and document.summary.brief in {
        c.presentation_text for c in document.confirmations
    }
    assert document.booking is not None and document.booking.simulated
    assert document.metrics.turns == 9 and document.versions.commit_sha == "local"


def test_export_schema_names_every_required_section() -> None:
    schema = ExportDocument.model_json_schema()
    expected = {
        "schema_version",
        "session",
        "candidate",
        "transcript",
        "confirmations",
        "booking",
        "review_flags",
        "retrieval_events",
        "signals",
        "summary",
        "metrics",
        "versions",
    }
    assert expected <= set(schema["properties"])


def test_every_allowlisted_tool_has_one_generated_schema() -> None:
    schemas = tool_schemas()
    assert [s.name for s in schemas] == list(ARGUMENT_MODELS)
    for s in schemas:
        assert s.parameters.get("additionalProperties") is False
