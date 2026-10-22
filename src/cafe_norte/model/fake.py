"""Deterministic scripted model for tests and CI evaluations. Executes nothing."""

import asyncio
from collections.abc import AsyncGenerator, Callable, Sequence
from datetime import datetime

from cafe_norte.errors import ErrorCode
from cafe_norte.model.contracts import (
    ChoiceQuestion,
    Decision,
    ModelError,
    ModelEvent,
    ModelMessage,
    ToolSchema,
)

# A model that decides from what it is sent: the messages and the tools offered this round.
Policy = Callable[[tuple[ModelMessage, ...], tuple[ToolSchema, ...]], Sequence[ModelEvent]]


class FakeModel:
    """Replays one scripted event list per call, in order. When the scripts run out it replays
    ``fallback`` if given, otherwise raises ``ModelError``. With a ``policy`` it answers each
    call with what the policy decides instead, for tests whose model must react to the prompt.

    Scripts are written by tests and by evals/cases/scenarios/*.yaml (``fake_script``)."""

    model_id = "fake"

    def __init__(
        self,
        scripts: Sequence[Sequence[ModelEvent]],
        *,
        delay_seconds: float = 0,
        fallback: Sequence[ModelEvent] | None = None,
        policy: Policy | None = None,
    ) -> None:
        self._scripts = [tuple(script) for script in scripts]
        self._fallback = tuple(fallback) if fallback is not None else None
        self._delay = delay_seconds
        self._policy = policy
        self._calls: list[tuple[ModelMessage, ...]] = []
        self._tools: list[tuple[ToolSchema, ...]] = []
        self._failures: list[ErrorCode] = []

    def fail_next(self, code: ErrorCode = "provider_unavailable") -> None:
        """The next call raises ``ModelError`` instead of replaying a script; the scripts stay
        for the call after it. A provider outage for one turn."""
        self._failures.append(code)

    async def stream(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSchema, ...],
        *,
        deadline: datetime,
    ) -> AsyncGenerator[ModelEvent, None]:
        self._calls.append(messages)
        self._tools.append(tools)
        if self._failures:
            raise ModelError("scripted provider failure", code=self._failures.pop(0))
        if self._policy is not None:
            script = tuple(self._policy(messages, tools))
        elif self._scripts:
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


DecisionReply = Decision | ModelError | Callable[[dict[str, str]], Decision]


class FakeDecisionModel:
    """Replays scripted decisions in order; a ``ModelError`` in the script is raised instead,
    and a callable is answered from the state it is asked about (a verdict relative to the
    session language). Records every state it was asked about."""

    model_id = "fake-decision"

    def __init__(self, replies: Sequence[DecisionReply], *, delay_seconds: float = 0):
        self._replies = list(replies)
        self._delay = delay_seconds
        self.states: list[dict[str, str]] = []

    async def decide(
        self,
        state: dict[str, str],
        questions: dict[str, ChoiceQuestion],
        *,
        deadline: datetime,
    ) -> Decision:
        self.states.append(state)
        if self._delay:
            await asyncio.sleep(self._delay)
        if not self._replies:
            raise ModelError("fake decision script exhausted", code="provider_unavailable")
        reply = self._replies.pop(0)
        if isinstance(reply, ModelError):
            raise reply
        return reply if isinstance(reply, Decision) else reply(state)
