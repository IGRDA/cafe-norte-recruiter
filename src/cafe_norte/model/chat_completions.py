"""Streaming Chat Completions adapter (Groq): luzia's wire parsing, plus several calls per turn."""

from collections.abc import AsyncIterator
from datetime import datetime

import httpx

from cafe_norte.model.contracts import ModelEvent, ModelMessage, ToolSchema


class ChatCompletionsModel:
    """Single-choice streaming completion with tool calls and usage.

    The HTTP client is bound for the application lifespan. Unknown tools, oversized arguments,
    malformed chunks and EOF before completion raise ``ModelError``. The provider's own tools
    are never requested."""

    def __init__(self, *, model_id: str, base_url: str, api_key: str) -> None:
        raise NotImplementedError

    def bind_client(self, client: httpx.AsyncClient | None) -> None:
        raise NotImplementedError

    @property
    def model_id(self) -> str:
        raise NotImplementedError

    def stream(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSchema, ...],
        *,
        deadline: datetime,
    ) -> AsyncIterator[ModelEvent]:
        raise NotImplementedError
