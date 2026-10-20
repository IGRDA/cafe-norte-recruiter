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
