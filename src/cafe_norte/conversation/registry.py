"""Name to handler, argument validation, repair budget."""

from collections.abc import Mapping

from cafe_norte.conversation.contracts import ToolContext, ToolHandler, ToolOutcome
from cafe_norte.conversation.tools import ToolName
from cafe_norte.model.contracts import ToolCall, ToolSchema


class ToolRegistry:
    """Rejects unknown names, validates ``arguments_json`` against the tool's model, and calls
    the handler. A validation failure returns a ``ToolOutcome`` the model can repair from,
    at most once per turn; the runtime counts."""

    def __init__(self, handlers: Mapping[ToolName, ToolHandler]) -> None:
        raise NotImplementedError

    def schemas(self) -> tuple[ToolSchema, ...]:
        raise NotImplementedError

    async def dispatch(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        raise NotImplementedError
