"""The export schema is generated from the Pydantic model, and the tool schemas from the args."""

from cafe_norte.conversation.tools import ARGUMENT_MODELS, tool_schemas
from cafe_norte.persistence.export import ExportDocument
from tests.support import ROOT


def test_example_export_is_a_complete_s01_session() -> None:
    """Keep a previously serialized session readable as the export model evolves."""
    document = ExportDocument.model_validate_json(
        (ROOT / "tests" / "fixtures" / "session_export.json").read_text()
    )
    assert document.schema_version == "1"
    assert (document.session.lifecycle, document.session.outcome) == ("completed", "reserved")
    assert document.session.ended_at is not None
    confirmed = {c.target.kind for c in document.confirmations if c.status == "confirmed"}
    assert confirmed == {"field", "brief", "slot"}
    assert {c.assurance for c in document.confirmations if c.status == "confirmed"} == {"heard"}
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
