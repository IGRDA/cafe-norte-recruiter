"""Deterministic scripted model for tests and CI evaluations. Executes nothing."""

from collections.abc import AsyncIterator, Sequence
from datetime import datetime

from cafe_norte.model.contracts import ModelEvent, ModelMessage, ToolSchema


class FakeModel:
    """Replays one scripted event list per call, in order; raises when the script runs out.

    Scripts are written by tests and by evals/cases/scenarios/*.yaml (``fake_script``)."""

    model_id = "fake"

    def __init__(
        self, scripts: Sequence[Sequence[ModelEvent]], *, delay_seconds: float = 0
    ) -> None:
        raise NotImplementedError

    def stream(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSchema, ...],
        *,
        deadline: datetime,
    ) -> AsyncIterator[ModelEvent]:
        raise NotImplementedError

    @property
    def calls(self) -> tuple[tuple[ModelMessage, ...], ...]:
        """Every message tuple the runtime sent, for assertions on prompt assembly."""
        raise NotImplementedError
