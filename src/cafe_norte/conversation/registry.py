"""Name to handler, argument validation, repair budget."""

from collections.abc import Mapping

from pydantic import BaseModel, ValidationError

from cafe_norte.conversation.contracts import ToolContext, ToolHandler, ToolOutcome
from cafe_norte.conversation.tools import ARGUMENT_MODELS, ToolName, tool_schemas
from cafe_norte.model.contracts import ToolCall, ToolSchema


class ToolRegistry:
    """Rejects unknown names, validates ``arguments_json`` against the tool's model, and calls
    the handler. A validation failure returns a ``ToolOutcome`` the model can repair from,
    at most once per turn; the runtime counts. Only tools with a handler are advertised."""

    def __init__(self, handlers: Mapping[ToolName, ToolHandler]) -> None:
        self._handlers: dict[str, ToolHandler] = {name: h for name, h in handlers.items()}
        self._models: dict[str, type[BaseModel]] = {
            name: ARGUMENT_MODELS[name] for name in handlers
        }
        self._schemas = tuple(s for s in tool_schemas() if s.name in self._handlers)

    def schemas(self) -> tuple[ToolSchema, ...]:
        return self._schemas

    async def dispatch(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        handler = self._handlers.get(call.name)
        if handler is None:
            available = ", ".join(sorted(self._handlers))
            return ToolOutcome(
                ok=False,
                model_text=f"Unknown tool '{call.name}'. Available tools: {available}.",
                summary="unknown_tool",
            )
        try:
            arguments = self._models[call.name].model_validate_json(call.arguments_json)
        except ValidationError as error:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
                for e in error.errors()
            )
            return ToolOutcome(
                ok=False,
                model_text=f"Invalid arguments for {call.name}: {problems}. Fix them and retry.",
                summary=f"invalid_arguments:{len(error.errors())}",
            )
        return await handler(context, arguments)
