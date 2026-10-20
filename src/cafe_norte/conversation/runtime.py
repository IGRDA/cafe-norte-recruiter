"""The runtime implementation behind the ``ConversationRuntime`` port."""

from collections.abc import AsyncIterator
from typing import Literal

from cafe_norte.conversation.contracts import (
    RuntimeEvent,
    SignalAnalyzer,
    TurnInput,
)
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.domain.contracts import ConfigId, SessionId, StoreConfiguration, TurnId
from cafe_norte.knowledge.contracts import Retriever
from cafe_norte.model.contracts import Model
from cafe_norte.persistence.contracts import Store


class Limits:
    """Per-turn and per-session bounds, all configurable from the environment."""

    __slots__ = ("llm_first_output_seconds", "max_tool_rounds", "session_seconds", "tool_seconds")

    def __init__(
        self,
        *,
        max_tool_rounds: int = 4,
        llm_first_output_seconds: float = 6.0,
        tool_seconds: float = 10.0,
        session_seconds: float = 480.0,
    ) -> None:
        self.max_tool_rounds = max_tool_rounds
        self.llm_first_output_seconds = llm_first_output_seconds
        self.tool_seconds = tool_seconds
        self.session_seconds = session_seconds


class Runtime:
    def __init__(
        self,
        *,
        model: Model,
        tools: ToolRegistry,
        retriever: Retriever,
        store: Store,
        configurations: dict[ConfigId, StoreConfiguration],
        signals: SignalAnalyzer | None,
        limits: Limits,
        owner: str,
    ) -> None:
        raise NotImplementedError

    def run_turn(self, turn: TurnInput) -> AsyncIterator[RuntimeEvent]:
        raise NotImplementedError

    async def delivered(self, turn_id: TurnId, *, text: str, complete: bool) -> None:
        raise NotImplementedError

    async def end(
        self, session_id: SessionId, reason: Literal["stop", "limit", "shutdown"]
    ) -> None:
        raise NotImplementedError
