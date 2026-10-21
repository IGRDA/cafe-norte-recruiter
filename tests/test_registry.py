"""``ToolRegistry``: names, argument validation, and what the model gets back."""

from datetime import UTC, datetime

from pydantic import BaseModel

from cafe_norte.conversation.contracts import ToolContext, ToolOutcome
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.tools import UpdateCandidateArgs
from cafe_norte.domain.contracts import SessionId, TurnId
from cafe_norte.model.contracts import ToolCall

CONTEXT = ToolContext(
    session_id=SessionId("s"),
    turn_id=TurnId("t"),
    now=datetime(2026, 10, 20, tzinfo=UTC),
    language="es",
    lease_generation=None,
)


class Recorder:
    def __init__(self) -> None:
        self.received: list[BaseModel] = []

    async def __call__(self, context: ToolContext, arguments: BaseModel) -> ToolOutcome:
        self.received.append(arguments)
        return ToolOutcome(ok=True, model_text="done", summary="done")


def test_only_registered_tools_are_advertised() -> None:
    registry = ToolRegistry({"update_candidate": Recorder()})
    assert [s.name for s in registry.schemas()] == ["update_candidate"]
    assert "evidence_text" in registry.schemas()[0].parameters["properties"]


async def test_valid_arguments_reach_the_handler_as_the_typed_model() -> None:
    handler = Recorder()
    registry = ToolRegistry({"update_candidate": handler})
    call = ToolCall(
        call_id="c",
        name="update_candidate",
        arguments_json='{"patch": {"name": "Lucía"}, "evidence_text": "soy Lucía"}',
    )
    outcome = await registry.dispatch(call, CONTEXT)
    assert outcome.ok
    assert isinstance(handler.received[0], UpdateCandidateArgs)
    assert handler.received[0].patch.name == "Lucía"


async def test_an_unknown_tool_is_refused_without_calling_anything() -> None:
    handler = Recorder()
    registry = ToolRegistry({"update_candidate": handler})
    outcome = await registry.dispatch(
        ToolCall(call_id="c", name="drop_tables", arguments_json="{}"), CONTEXT
    )
    assert not outcome.ok and outcome.summary == "unknown_tool"
    assert "update_candidate" in outcome.model_text
    assert handler.received == []


async def test_malformed_arguments_are_explained_to_the_model() -> None:
    handler = Recorder()
    registry = ToolRegistry({"update_candidate": handler})
    outcome = await registry.dispatch(
        ToolCall(call_id="c", name="update_candidate", arguments_json='{"patch": {"name": ""}}'),
        CONTEXT,
    )
    assert not outcome.ok
    assert outcome.summary.startswith("invalid_arguments:")
    assert "evidence_text" in outcome.model_text and "patch.name" in outcome.model_text
    assert handler.received == []


async def test_unknown_keys_in_arguments_are_rejected() -> None:
    registry = ToolRegistry({"update_candidate": Recorder()})
    call = ToolCall(
        call_id="c",
        name="update_candidate",
        arguments_json='{"patch": {"name": "L"}, "evidence_text": "L", "session_id": "x"}',
    )
    outcome = await registry.dispatch(call, CONTEXT)
    assert not outcome.ok and "session_id" in outcome.model_text
