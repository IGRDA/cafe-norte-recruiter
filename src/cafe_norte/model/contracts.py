"""Model port: provider-neutral messages, tool schemas as data, and typed stream events."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from cafe_norte.errors import ErrorCode, ServiceError


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolSchema(Frozen):
    """A tool as advertised to the provider. ``parameters`` is JSON Schema generated from the
    tool's Pydantic argument model in conversation/tools.py; nothing is hand-written twice."""

    name: str
    description: str
    parameters: dict[str, Any]


class ToolCall(Frozen):
    """A fully assembled call the model asks for. ``arguments_json`` is validated by the
    runtime, never by the adapter. ``call_id`` is echoed back in the tool message."""

    call_id: str
    name: str
    arguments_json: str


class ModelMessage(Frozen):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCall, ...] = ()  # assistant messages that asked for tools
    tool_call_id: str = ""  # tool messages answering one call


class ModelText(Frozen):
    text: str


class ModelUsage(Frozen):
    """Tokens billed for one call, reasoning included, as reported by the provider."""

    input_tokens: int
    output_tokens: int
    model_id: str


class ModelFinished(Frozen):
    reason: Literal["stop", "tool_calls", "length"]


ModelEvent = ModelText | ToolCall | ModelUsage | ModelFinished


class ModelError(ServiceError):
    def __init__(self, detail: str = "", *, code: ErrorCode = "invalid_response") -> None:
        super().__init__(detail, code=code)


class Model(Protocol):
    """One streamed completion.

    Yields ``ModelText`` deltas and fully assembled ``ToolCall`` items in provider order, an
    optional ``ModelUsage``, then exactly one ``ModelFinished``. Stops yielding at ``deadline``
    with ``ModelError(code="timeout")``. Cancellation propagates and closes the connection.
    Provider-side tools (search, code execution) are never enabled."""

    @property
    def model_id(self) -> str: ...

    def stream(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSchema, ...],
        *,
        deadline: datetime,
    ) -> AsyncIterator[ModelEvent]: ...
