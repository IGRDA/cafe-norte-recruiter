"""OpenTelemetry export to Langfuse: one trace per turn, spans for the model rounds, the tools
and the store writes. Without both Langfuse keys nothing is traced and events still go to
stdout (D36)."""

import base64
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from types import TracebackType

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import StatusCode, Tracer
from opentelemetry.util.types import AttributeValue

from cafe_norte.domain.contracts import Channel, SessionId, StoreConfiguration, TurnId
from cafe_norte.errors import Language
from cafe_norte.observability import events
from cafe_norte.observability.contracts import (
    ROOT_SPAN_NAME,
    ObservationKind,
    PriceTable,
    ProcessVersions,
    Span,
    SpanValue,
    StructuredEvent,
    Telemetry,
    UsageRecord,
    stamp,
)
from cafe_norte.observability.cost import estimate, load_prices
from cafe_norte.observability.events import StdoutTelemetry, redact

DEFAULT_BASE_URL = "https://cloud.langfuse.com"  # Langfuse Cloud EU (D05)
DEFAULT_ENVIRONMENT = "development"

# Limits (docs/architecture.md): a slow Langfuse never holds the app up.
FLUSH_TIMEOUT_MS = 5_000  # bound on the flush at shutdown
EXPORT_TIMEOUT_MS = 5_000  # one export request
MAX_QUEUE_SPANS = 2_048  # spans kept while exporting; beyond it the oldest are dropped
SCHEDULE_DELAY_MS = 2_000  # how often a batch is sent

_OBSERVATION = "langfuse.observation."


def traces_endpoint(env: Mapping[str, str]) -> str:
    base = (env.get("LANGFUSE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    return f"{base}/api/public/otel/v1/traces"


def auth_headers(env: Mapping[str, str]) -> dict[str, str]:
    credentials = f"{env['LANGFUSE_PUBLIC_KEY']}:{env['LANGFUSE_SECRET_KEY']}"
    return {
        "Authorization": "Basic " + base64.b64encode(credentials.encode()).decode(),
        "x-langfuse-ingestion-version": "4",
    }


def configure(
    env: Mapping[str, str],
    process: ProcessVersions,
    *,
    prices: PriceTable | None = None,
    exporter: SpanExporter | None = None,
) -> tuple[Telemetry, Callable[[], None]]:
    """The telemetry to hand the runtime and the shutdown hook that flushes it, bounded.
    ``exporter`` replaces the OTLP one in tests."""
    if not (env.get("LANGFUSE_PUBLIC_KEY") and env.get("LANGFUSE_SECRET_KEY")):
        return StdoutTelemetry(), lambda: None
    environment = env.get("CAFE_NORTE_ENVIRONMENT") or DEFAULT_ENVIRONMENT
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "cafe-norte",
                "service.version": process.commit_sha,
                "deployment.environment": environment,
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            exporter
            or OTLPSpanExporter(
                endpoint=traces_endpoint(env),
                headers=auth_headers(env),
                timeout=EXPORT_TIMEOUT_MS // 1000,
            ),
            max_queue_size=MAX_QUEUE_SPANS,
            schedule_delay_millis=SCHEDULE_DELAY_MS,
            export_timeout_millis=EXPORT_TIMEOUT_MS,
        )
    )
    telemetry = OtelTelemetry(
        provider.get_tracer("cafe_norte"),
        process,
        prices if prices is not None else load_prices(),
        content=env.get("CAFE_NORTE_TRACE_CONTENT", "").strip().lower() == "on",
        environment=environment,
    )

    def shutdown() -> None:
        provider.force_flush(timeout_millis=FLUSH_TIMEOUT_MS)
        provider.shutdown()

    return telemetry, shutdown


class OtelTelemetry:
    def __init__(
        self,
        tracer: Tracer,
        process: ProcessVersions,
        prices: PriceTable,
        *,
        content: bool,
        environment: str,
    ) -> None:
        self._tracer = tracer
        self._process = process
        self._prices = prices
        self._content = content
        self._environment = environment

    def emit(self, event: StructuredEvent) -> None:
        events.emit(event)

    def turn(
        self,
        *,
        session_id: SessionId,
        turn_id: TurnId,
        configuration: StoreConfiguration,
        channel: Channel,
        language: Language,
    ) -> Span:
        versions = stamp(configuration, self._process)
        metadata = {**versions.model_dump(), "turn_id": turn_id, "channel": channel}
        metadata["language"] = language
        # Langfuse filters on the trace attributes of each observation, so every span has them.
        shared: dict[str, AttributeValue] = {
            "langfuse.trace.name": ROOT_SPAN_NAME,
            "langfuse.session.id": session_id,
            "session.id": session_id,
            "langfuse.release": self._process.commit_sha,
            "langfuse.environment": self._environment,
            "langfuse.version": versions.prompt_version,
            "langfuse.trace.tags": (channel, language, versions.config_id),
            **{f"langfuse.trace.metadata.{key}": value for key, value in metadata.items()},
        }
        span = self._tracer.start_span(
            ROOT_SPAN_NAME,
            context=Context(),  # a turn is its own trace, whatever span is active around it
            attributes={**shared, f"{_OBSERVATION}type": "span"},
        )
        return _OtelSpan(self._tracer, span, shared, self._prices, session_id, self._content)


class _OtelSpan:
    def __init__(
        self,
        tracer: Tracer,
        span: trace.Span,
        shared: dict[str, AttributeValue],
        prices: PriceTable,
        session_id: SessionId,
        content: bool,
    ) -> None:
        self._tracer = tracer
        self._span = span
        self._shared = shared
        self._prices = prices
        self._session_id = session_id
        self._content = content
        self._ended = False
        self._failed = False

    def child(self, name: str, kind: ObservationKind = "span", **metadata: SpanValue) -> Span:
        span = self._tracer.start_span(
            name,
            context=trace.set_span_in_context(self._span),
            attributes={**self._shared, f"{_OBSERVATION}type": kind, **_metadata(metadata)},
        )
        return _OtelSpan(
            self._tracer, span, self._shared, self._prices, self._session_id, self._content
        )

    def annotate(self, **metadata: SpanValue) -> None:
        self._span.set_attributes(_metadata(metadata))

    def set_usage(self, *, model_id: str, input_tokens: int, output_tokens: int) -> None:
        self._span.set_attribute(f"{_OBSERVATION}model.name", model_id)
        self._span.set_attribute(
            f"{_OBSERVATION}usage_details",
            json.dumps(
                {
                    "input": input_tokens,
                    "output": output_tokens,
                    "total": input_tokens + output_tokens,
                }
            ),
        )
        # Our own euros, from the table the export is priced with, so the two agree. Left out
        # when the model has no price: a missing cost is better than a wrong one.
        costs: dict[str, float] = {}
        for direction, quantity in (("input", input_tokens), ("output", output_tokens)):
            record = UsageRecord(
                session_id=self._session_id,
                turn_id=None,
                kind="llm_tokens",
                quantity=quantity,
                unit_detail=f"{model_id}:{direction}",
                estimated=False,
            )
            priced = estimate(self._session_id, [record], self._prices)
            if priced.missing_prices:
                return
            costs[direction] = priced.marginal_eur
        costs["total"] = costs["input"] + costs["output"]
        self._span.set_attribute(f"{_OBSERVATION}cost_details", json.dumps(costs))
        self._span.set_attributes(
            _metadata({"cost_currency": "EUR", "price_table_version": self._prices.version})
        )

    def set_content(self, *, input: str | None = None, output: str | None = None) -> None:
        if not self._content:
            return
        for name, text in (("input", input), ("output", output)):
            if text is not None:
                self._span.set_attribute(
                    f"{_OBSERVATION}{name}", json.dumps(redact(text), ensure_ascii=False)
                )

    def first_output(self) -> None:
        self._span.set_attribute(
            f"{_OBSERVATION}completion_start_time", datetime.now(UTC).isoformat()
        )

    def fail(self, code: str) -> None:
        self._failed = True
        self._span.set_attributes(
            {f"{_OBSERVATION}level": "ERROR", f"{_OBSERVATION}status_message": code}
        )
        self._span.set_status(StatusCode.ERROR, code)

    def end(self) -> None:
        if not self._ended:
            self._ended = True
            self._span.end()

    def __enter__(self) -> Span:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if (
            exc_type is not None
            and not issubclass(exc_type, GeneratorExit)  # an abandoned stream, not an error
            and not self._failed  # a code given on purpose wins
        ):
            self.fail(exc_type.__name__)
        self.end()


def _metadata(metadata: Mapping[str, SpanValue]) -> dict[str, AttributeValue]:
    return {f"{_OBSERVATION}metadata.{key}": value for key, value in metadata.items()}
