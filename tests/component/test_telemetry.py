"""The OpenTelemetry adapter: one trace per turn, shaped for Langfuse, nothing sent in tests."""

import asyncio
import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from cafe_norte.domain.contracts import SessionId, TurnId
from cafe_norte.observability.contracts import (
    Price,
    PriceTable,
    ProcessVersions,
    Span,
    StructuredEvent,
    Telemetry,
)
from cafe_norte.observability.events import StdoutTelemetry
from cafe_norte.observability.telemetry import (
    DEFAULT_BASE_URL,
    auth_headers,
    configure,
    traces_endpoint,
)
from tests.support.builders import CONFIG

PROCESS = ProcessVersions(
    model_id="gpt-4o-mini",
    prompt_version="ana_v9",
    schema_version="1",
    commit_sha="abc1234",
    stt_model="nova-3",
    tts_model="eleven_flash_v2_5",
    voice_id="voice-1",
)
KEYS = {"LANGFUSE_PUBLIC_KEY": "pk-lf-test", "LANGFUSE_SECRET_KEY": "sk-lf-test"}
PRICES = PriceTable(
    version="test-1",
    verified_on=datetime(2026, 10, 21, tzinfo=UTC),
    prices=(
        Price(kind="llm_tokens", unit_detail="gpt-4o-mini:input", eur_per_unit=0.000001),
        Price(kind="llm_tokens", unit_detail="gpt-4o-mini:output", eur_per_unit=0.000004),
    ),
)


class Traced:
    """A configured adapter over an in-memory exporter."""

    def __init__(self, extra_env: dict[str, str] | None = None) -> None:
        self.exporter = InMemorySpanExporter()
        env = {**KEYS, **(extra_env or {})}
        self.telemetry: Telemetry
        self.shutdown: Callable[[], None]
        self.telemetry, self.shutdown = configure(
            env, PROCESS, prices=PRICES, exporter=self.exporter
        )

    def turn(self) -> Span:
        return self.telemetry.turn(
            session_id=SessionId("s1"),
            turn_id=TurnId("t1"),
            configuration=CONFIG,
            channel="voice",
            language="es",
        )

    def finished(self) -> dict[str, ReadableSpan]:
        self.shutdown()
        return {span.name: span for span in self.exporter.get_finished_spans()}


def attributes(span: ReadableSpan) -> dict[str, object]:
    return dict(span.attributes or {})


# ---- configuration -------------------------------------------------------------------------------


def test_the_endpoint_defaults_to_langfuse_eu_and_follows_the_base_url() -> None:
    assert DEFAULT_BASE_URL == "https://cloud.langfuse.com"
    assert traces_endpoint({}) == "https://cloud.langfuse.com/api/public/otel/v1/traces"
    custom = {"LANGFUSE_BASE_URL": "https://langfuse.example.org/"}
    assert traces_endpoint(custom) == "https://langfuse.example.org/api/public/otel/v1/traces"


def test_the_headers_carry_basic_auth_and_the_ingestion_version() -> None:
    headers = auth_headers(KEYS)
    expected = base64.b64encode(b"pk-lf-test:sk-lf-test").decode()
    assert headers == {
        "Authorization": f"Basic {expected}",
        "x-langfuse-ingestion-version": "4",
    }


@pytest.mark.parametrize(
    "env",
    [{}, {"LANGFUSE_PUBLIC_KEY": "pk-lf-test"}, {"LANGFUSE_SECRET_KEY": "sk-lf-test"}],
)
def test_without_both_keys_nothing_is_traced_and_events_still_go_to_stdout(
    env: dict[str, str],
) -> None:
    telemetry, shutdown = configure(env, PROCESS)
    assert isinstance(telemetry, StdoutTelemetry)
    shutdown()  # a no-op that must not raise


# ---- the trace -----------------------------------------------------------------------------------


def test_a_turn_is_one_trace_with_the_spans_nested_under_their_parents() -> None:
    traced = Traced()
    with traced.turn() as root:
        with root.child("invoke-agent", "agent") as agent, agent.child("step", "chain") as step:
            step.child("chat", "generation").end()
            step.child("search_knowledge", "retriever").end()
        root.child("write-assistant-turn").end()
    spans = traced.finished()

    assert set(spans) == {
        "handle-candidate-turn",
        "invoke-agent",
        "step",
        "chat",
        "search_knowledge",
        "write-assistant-turn",
    }
    assert len({span.context.trace_id for span in spans.values()}) == 1

    def parent_of(name: str) -> str | None:
        parent = spans[name].parent
        if parent is None:
            return None
        return next(n for n, s in spans.items() if s.context.span_id == parent.span_id)

    assert parent_of("handle-candidate-turn") is None
    assert parent_of("invoke-agent") == "handle-candidate-turn"
    assert parent_of("step") == "invoke-agent"
    assert parent_of("chat") == "step"
    assert parent_of("search_knowledge") == "step"
    assert parent_of("write-assistant-turn") == "handle-candidate-turn"


def test_each_span_is_typed_for_langfuse() -> None:
    traced = Traced()
    with traced.turn() as root:
        with root.child("invoke-agent", "agent") as agent:
            agent.child("chat", "generation").end()
            agent.child("update_candidate", "tool").end()
    spans = traced.finished()
    kinds = {n: attributes(s)["langfuse.observation.type"] for n, s in spans.items()}
    assert kinds == {
        "handle-candidate-turn": "span",
        "invoke-agent": "agent",
        "chat": "generation",
        "update_candidate": "tool",
    }


def test_a_new_turn_starts_a_new_trace_even_inside_another_active_span() -> None:
    traced = Traced()
    outer = trace.get_tracer("outer").start_span("outer")
    with trace.use_span(outer, end_on_exit=True):
        traced.turn().end()
    root = traced.finished()["handle-candidate-turn"]
    assert root.parent is None


def test_every_span_names_the_trace_session_release_and_environment() -> None:
    traced = Traced({"CAFE_NORTE_ENVIRONMENT": "production"})
    with traced.turn() as root:
        root.child("chat", "generation").end()
    for span in traced.finished().values():
        attrs = attributes(span)
        assert attrs["langfuse.trace.name"] == "handle-candidate-turn"
        assert attrs["langfuse.session.id"] == "s1"
        assert attrs["session.id"] == "s1"
        assert attrs["langfuse.release"] == "abc1234"
        assert attrs["langfuse.environment"] == "production"
        assert attrs["langfuse.version"] == "ana_v9"
        assert attrs["langfuse.trace.tags"] == ("voice", "es", "chamberi_barista_v1")


def test_the_environment_defaults_to_development() -> None:
    traced = Traced()
    traced.turn().end()
    assert attributes(traced.finished()["handle-candidate-turn"])["langfuse.environment"] == (
        "development"
    )


def test_every_span_carries_the_whole_version_stamp_as_filterable_metadata() -> None:
    traced = Traced()
    traced.turn().end()
    attrs = attributes(traced.finished()["handle-candidate-turn"])
    prefix = "langfuse.trace.metadata."
    assert {k.removeprefix(prefix): v for k, v in attrs.items() if k.startswith(prefix)} == {
        "config_id": "chamberi_barista_v1",
        "config_version": CONFIG.version,
        "kb_version": CONFIG.kb_version,
        "prompt_version": "ana_v9",
        "schema_version": "1",
        "model_id": "gpt-4o-mini",
        "stt_model": "nova-3",
        "tts_model": "eleven_flash_v2_5",
        "voice_id": "voice-1",
        "commit_sha": "abc1234",
        "turn_id": "t1",
        "channel": "voice",
        "language": "es",
    }


def test_metadata_and_annotations_land_under_the_observation_prefix() -> None:
    traced = Traced()
    with traced.turn() as root:
        root.child("step", "chain", round=2).end()
        root.annotate(outcome="finished", tools_called=1)
    spans = traced.finished()
    assert attributes(spans["step"])["langfuse.observation.metadata.round"] == 2
    root_attrs = attributes(spans["handle-candidate-turn"])
    assert root_attrs["langfuse.observation.metadata.outcome"] == "finished"
    assert root_attrs["langfuse.observation.metadata.tools_called"] == 1


# ---- usage and cost ------------------------------------------------------------------------------


def test_a_generation_carries_model_tokens_and_our_euro_cost() -> None:
    traced = Traced()
    with traced.turn() as root:
        chat = root.child("chat", "generation")
        chat.set_usage(model_id="gpt-4o-mini", input_tokens=1000, output_tokens=500)
        chat.end()
    attrs = attributes(traced.finished()["chat"])
    assert attrs["langfuse.observation.model.name"] == "gpt-4o-mini"
    assert json.loads(str(attrs["langfuse.observation.usage_details"])) == {
        "input": 1000,
        "output": 500,
        "total": 1500,
    }
    cost = json.loads(str(attrs["langfuse.observation.cost_details"]))
    assert cost == pytest.approx({"input": 0.001, "output": 0.002, "total": 0.003})
    assert attrs["langfuse.observation.metadata.cost_currency"] == "EUR"
    assert attrs["langfuse.observation.metadata.price_table_version"] == "test-1"


def test_a_model_without_a_price_sends_tokens_and_no_cost() -> None:
    traced = Traced()
    with traced.turn() as root:
        chat = root.child("chat", "generation")
        chat.set_usage(model_id="unknown", input_tokens=10, output_tokens=5)
        chat.end()
    attrs = attributes(traced.finished()["chat"])
    assert "langfuse.observation.usage_details" in attrs
    assert "langfuse.observation.cost_details" not in attrs


# ---- content -------------------------------------------------------------------------------------


def test_content_is_not_exported_unless_the_operator_turns_it_on() -> None:
    traced = Traced()
    with traced.turn() as root:
        root.set_content(input="Soy Lucía", output="Encantada")
    attrs = attributes(traced.finished()["handle-candidate-turn"])
    assert "langfuse.observation.input" not in attrs
    assert "langfuse.observation.output" not in attrs


def test_content_on_exports_the_text_redacted() -> None:
    traced = Traced({"CAFE_NORTE_TRACE_CONTENT": "on"})
    with traced.turn() as root:
        root.set_content(input="Soy Lucía, escribe a lucia@example.com", output="Encantada")
    attrs = attributes(traced.finished()["handle-candidate-turn"])
    assert json.loads(str(attrs["langfuse.observation.input"])) == "Soy Lucía, escribe a [email]"
    assert json.loads(str(attrs["langfuse.observation.output"])) == "Encantada"


@pytest.mark.parametrize("value", ["off", "", "true", "1", "ON "])
def test_only_the_word_on_turns_content_on(value: str) -> None:
    traced = Traced({"CAFE_NORTE_TRACE_CONTENT": value})
    with traced.turn() as root:
        root.set_content(input="hola")
    attrs = attributes(traced.finished()["handle-candidate-turn"])
    assert ("langfuse.observation.input" in attrs) is (value.strip().lower() == "on")


# ---- failure and shutdown ------------------------------------------------------------------------


def test_a_failed_span_is_an_error_with_its_code() -> None:
    traced = Traced()
    with traced.turn() as root:
        chat = root.child("chat", "generation")
        chat.fail("timeout")
        chat.end()
    span = traced.finished()["chat"]
    attrs = attributes(span)
    assert attrs["langfuse.observation.level"] == "ERROR"
    assert attrs["langfuse.observation.status_message"] == "timeout"
    assert span.status.status_code == trace.StatusCode.ERROR


def test_an_exception_inside_a_span_marks_it_failed_and_propagates() -> None:
    traced = Traced()
    with pytest.raises(RuntimeError), traced.turn() as root, root.child("tool", "tool"):
        raise RuntimeError("boom")
    spans = traced.finished()
    assert attributes(spans["tool"])["langfuse.observation.status_message"] == "RuntimeError"
    assert spans["tool"].end_time is not None and spans["handle-candidate-turn"].end_time


def test_shutdown_exports_what_is_still_queued() -> None:
    traced = Traced()
    traced.turn().end()
    traced.shutdown()
    assert [s.name for s in traced.exporter.get_finished_spans()] == ["handle-candidate-turn"]


def test_events_still_go_to_stdout_when_tracing_is_on(capsys: pytest.CaptureFixture[str]) -> None:
    traced = Traced()
    traced.telemetry.emit(
        StructuredEvent(
            at=datetime(2026, 10, 21, tzinfo=UTC),
            severity="WARNING",
            session_id=SessionId("s1"),
            turn_id=TurnId("t1"),
            event="turn_failed",
            payload={"code": "timeout"},
        )
    )
    assert json.loads(capsys.readouterr().out)["event"] == "turn_failed"


def test_leaving_a_span_keeps_the_code_it_was_failed_with() -> None:
    traced = Traced()
    with pytest.raises(RuntimeError), traced.turn() as root, root.child("chat") as chat:
        chat.fail("timeout")
        raise RuntimeError("boom")
    attrs = attributes(traced.finished()["chat"])
    assert attrs["langfuse.observation.status_message"] == "timeout"


def test_an_abandoned_generator_is_not_an_error_in_the_trace() -> None:
    traced = Traced()
    with pytest.raises(GeneratorExit), traced.turn() as root, root.child("chat"):
        raise GeneratorExit
    attrs = attributes(traced.finished()["chat"])
    assert "langfuse.observation.level" not in attrs


def test_the_first_output_becomes_the_completion_start_time() -> None:
    traced = Traced()
    with traced.turn() as root:
        chat = root.child("chat", "generation")
        chat.first_output()
        chat.end()
    span = traced.finished()["chat"]
    start = datetime.fromisoformat(
        str(attributes(span)["langfuse.observation.completion_start_time"])
    )
    assert span.start_time is not None and span.end_time is not None
    assert span.start_time <= int(start.timestamp() * 1e9) <= span.end_time


def test_a_generation_without_output_has_no_completion_start_time() -> None:
    traced = Traced()
    with traced.turn() as root:
        root.child("chat", "generation").end()
    assert "langfuse.observation.completion_start_time" not in attributes(traced.finished()["chat"])


def test_input_and_output_set_apart_are_both_exported_when_content_is_on() -> None:
    traced = Traced({"CAFE_NORTE_TRACE_CONTENT": "on"})
    with traced.turn() as root:
        chat = root.child("chat", "generation")
        chat.set_content(input="hola")
        chat.set_content(output="buenas")
        chat.end()
    attrs = attributes(traced.finished()["chat"])
    assert json.loads(str(attrs["langfuse.observation.input"])) == "hola"
    assert json.loads(str(attrs["langfuse.observation.output"])) == "buenas"


def test_a_warned_span_is_a_warning_with_its_code_and_not_an_error() -> None:
    traced = Traced()
    with traced.turn() as root:
        tool = root.child("update_candidate", "tool")
        tool.warn("evidence_not_said")
        tool.end()
    span = traced.finished()["update_candidate"]
    attrs = attributes(span)
    assert attrs["langfuse.observation.level"] == "WARNING"
    assert attrs["langfuse.observation.status_message"] == "evidence_not_said"
    assert span.status.status_code != trace.StatusCode.ERROR


def test_a_cancelled_span_is_a_warning_and_the_cancellation_propagates() -> None:
    traced = Traced()
    with (
        pytest.raises(asyncio.CancelledError),
        traced.turn() as root,
        root.child("chat", "generation"),
    ):
        raise asyncio.CancelledError
    attrs = attributes(traced.finished()["chat"])
    assert attrs["langfuse.observation.level"] == "WARNING"
