"""Telemetry fakes: ``NullTelemetry`` for runs that trace nothing, ``RecordingTelemetry`` for
tests that assert on what a turn emitted."""

import asyncio
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

from cafe_norte.domain.contracts import Channel, SessionId, StoreConfiguration, TurnId
from cafe_norte.errors import Language
from cafe_norte.observability.contracts import (
    ROOT_SPAN_NAME,
    ObservationKind,
    Span,
    SpanValue,
    StructuredEvent,
)


class NullSpan:
    """Accepts everything and keeps nothing; its children are itself."""

    def child(self, name: str, kind: ObservationKind = "span", **metadata: SpanValue) -> Span:
        return self

    def annotate(self, **metadata: SpanValue) -> None:
        pass

    def set_usage(self, *, model_id: str, input_tokens: int, output_tokens: int) -> None:
        pass

    def set_content(self, *, input: str | None = None, output: str | None = None) -> None:
        pass

    def first_output(self) -> None:
        pass

    def fail(self, code: str) -> None:
        pass

    def warn(self, code: str) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> Span:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        pass


class NullTelemetry:
    def emit(self, event: StructuredEvent) -> None:
        pass

    def turn(
        self,
        *,
        session_id: SessionId,
        turn_id: TurnId,
        configuration: StoreConfiguration,
        channel: Channel,
        language: Language,
    ) -> Span:
        return NullSpan()


@dataclass
class RecordedSpan:
    name: str
    kind: ObservationKind
    parent: int | None
    metadata: dict[str, SpanValue]
    usage: tuple[str, int, int] | None = None
    content: tuple[str | None, str | None] | None = None
    first_output: bool = False
    failure: str | None = None
    warning: str | None = None
    ended: bool = False


@dataclass
class RecordingTelemetry:
    events: list[StructuredEvent] = field(default_factory=list)
    spans: list[RecordedSpan] = field(default_factory=list)

    def emit(self, event: StructuredEvent) -> None:
        self.events.append(event)

    def turn(
        self,
        *,
        session_id: SessionId,
        turn_id: TurnId,
        configuration: StoreConfiguration,
        channel: Channel,
        language: Language,
    ) -> Span:
        return self._open(
            ROOT_SPAN_NAME,
            "span",
            None,
            {
                "session_id": session_id,
                "turn_id": turn_id,
                "config_id": configuration.config_id,
                "channel": channel,
                "language": language,
            },
        )

    def span(self, name: str) -> RecordedSpan:
        """The first span with this name."""
        return next(span for span in self.spans if span.name == name)

    def outline(self) -> list[str]:
        """The trace as a tree of names, two spaces per level, the kind in brackets unless it
        is a plain span."""
        depth: dict[int, int] = {}
        lines: list[str] = []
        for index, span in enumerate(self.spans):
            depth[index] = 0 if span.parent is None else depth[span.parent] + 1
            label = span.name if span.kind == "span" else f"{span.name} [{span.kind}]"
            lines.append("  " * depth[index] + label)
        return lines

    def _open(
        self, name: str, kind: ObservationKind, parent: int | None, metadata: dict[str, Any]
    ) -> Span:
        self.spans.append(RecordedSpan(name, kind, parent, dict(metadata)))
        return _RecordingSpan(self, len(self.spans) - 1)


class _RecordingSpan(NullSpan):
    def __init__(self, owner: RecordingTelemetry, index: int) -> None:
        self._owner = owner
        self._index = index

    @property
    def _record(self) -> RecordedSpan:
        return self._owner.spans[self._index]

    def child(self, name: str, kind: ObservationKind = "span", **metadata: SpanValue) -> Span:
        return self._owner._open(name, kind, self._index, metadata)

    def annotate(self, **metadata: SpanValue) -> None:
        self._record.metadata.update(metadata)

    def set_usage(self, *, model_id: str, input_tokens: int, output_tokens: int) -> None:
        self._record.usage = (model_id, input_tokens, output_tokens)

    def set_content(self, *, input: str | None = None, output: str | None = None) -> None:
        before_input, before_output = self._record.content or (None, None)
        self._record.content = (
            input if input is not None else before_input,
            output if output is not None else before_output,
        )

    def first_output(self) -> None:
        self._record.first_output = True

    def fail(self, code: str) -> None:
        self._record.failure = code

    def warn(self, code: str) -> None:
        self._record.warning = code

    def end(self) -> None:
        self._record.ended = True

    def __enter__(self) -> Span:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None and issubclass(exc_type, asyncio.CancelledError):
            if self._record.warning is None and self._record.failure is None:
                self.warn(exc_type.__name__)  # the candidate talked over Ana: not an error
        elif (
            exc_type is not None
            and not issubclass(exc_type, GeneratorExit)  # an abandoned stream, not an error
            and self._record.failure is None  # a code given on purpose wins
        ):
            self.fail(exc_type.__name__)
        self.end()
