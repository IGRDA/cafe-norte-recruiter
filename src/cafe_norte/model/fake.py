"""Deterministic scripted model for tests and CI evaluations. Executes nothing."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import datetime

from cafe_norte.model.contracts import ModelError, ModelEvent, ModelMessage, ToolSchema


class FakeModel:
    """Replays one scripted event list per call, in order. When the scripts run out it replays
    ``fallback`` if given, otherwise raises ``ModelError``.

    Scripts are written by tests and by evals/cases/scenarios/*.yaml (``fake_script``)."""

    model_id = "fake"

    def __init__(
        self,
        scripts: Sequence[Sequence[ModelEvent]],
        *,
        delay_seconds: float = 0,
        fallback: Sequence[ModelEvent] | None = None,
    ) -> None:
        self._scripts = [tuple(script) for script in scripts]
        self._fallback = tuple(fallback) if fallback is not None else None
        self._delay = delay_seconds
        self._calls: list[tuple[ModelMessage, ...]] = []
        self._tools: list[tuple[ToolSchema, ...]] = []

    async def stream(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSchema, ...],
        *,
        deadline: datetime,
    ) -> AsyncIterator[ModelEvent]:
        self._calls.append(messages)
        self._tools.append(tools)
        if self._scripts:
            script = self._scripts.pop(0)
        elif self._fallback is not None:
            script = self._fallback
        else:
            raise ModelError("fake model script exhausted", code="provider_unavailable")
        for event in script:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield event

    @property
    def calls(self) -> tuple[tuple[ModelMessage, ...], ...]:
        """Every message tuple the runtime sent, for assertions on prompt assembly."""
        return tuple(self._calls)

    @property
    def advertised_tools(self) -> tuple[tuple[ToolSchema, ...], ...]:
        return tuple(self._tools)
