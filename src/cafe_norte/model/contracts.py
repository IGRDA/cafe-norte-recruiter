"""Model port: provider-neutral messages, tool schemas as data, and typed stream events."""

from collections.abc import AsyncGenerator
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
    cached_input_tokens: int = 0  # of input_tokens, read from the provider's prompt cache


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
    with ``ModelError(code="timeout")``. It is an async generator: ``aclose()`` cancels the
    call and closes the connection; the runtime uses that to cut runaway output and barge-in.
    Provider-side tools (search, code execution) are never enabled."""

    @property
    def model_id(self) -> str: ...

    def stream(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSchema, ...],
        *,
        deadline: datetime,
    ) -> AsyncGenerator[ModelEvent, None]: ...


# ---- decision models -----------------------------------------------------------------------


class ChoiceQuestion(Frozen):
    """One typed question for a decision model: ``criteria`` maps each option to what it
    means, and the model answers with one option and a probability for each."""

    instructions: str
    criteria: dict[str, str]


class ChoiceAnswer(Frozen):
    choice: str  # always one of the question's options; the adapter checks
    probabilities: dict[str, float] = {}


class Decision(Frozen):
    answers: dict[str, ChoiceAnswer]  # one per question asked
    model_id: str  # the dated version that answered
    input_tokens: int
    output_tokens: int


class DecisionModel(Protocol):
    """A model that answers typed questions about a state with probabilities and no text
    (TypeSafe's Jev). Raises ``ModelError`` with a stable code, as ``Model`` does."""

    @property
    def model_id(self) -> str: ...

    async def decide(
        self,
        state: dict[str, str],
        questions: dict[str, ChoiceQuestion],
        *,
        deadline: datetime,
    ) -> Decision: ...
