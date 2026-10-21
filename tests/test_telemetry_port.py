"""The telemetry port and the fakes beside it: what runtime tests assert against."""

import json
from datetime import UTC, datetime

import pytest

from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import ConfigId, SessionId, TurnId
from cafe_norte.observability.contracts import Span, StructuredEvent, Telemetry
from cafe_norte.observability.events import StdoutTelemetry
from cafe_norte.observability.fakes import NullTelemetry, RecordingTelemetry
from tests.support import CONFIG_DIR

CONFIGURATION = load_configurations(CONFIG_DIR)[ConfigId("chamberi_barista_v1")]
SID = SessionId("s1")
TID = TurnId("t1")


def open_turn(telemetry: Telemetry) -> Span:
    return telemetry.turn(
        session_id=SID, turn_id=TID, configuration=CONFIGURATION, channel="text", language="es"
    )


def test_spans_nest_by_the_parent_they_were_opened_under() -> None:
    telemetry = RecordingTelemetry()
    with open_turn(telemetry) as root:
        with root.child("invoke-agent", "agent") as agent:
            with agent.child("step", "chain", round=1) as step:
                step.child("chat", "generation", attempt=1).end()
                step.child("search_knowledge", "retriever").end()
        root.child("write-assistant-turn", "span").end()
    assert telemetry.outline() == [
        "handle-candidate-turn",
        "  invoke-agent [agent]",
        "    step [chain]",
        "      chat [generation]",
        "      search_knowledge [retriever]",
        "  write-assistant-turn",
    ]
    assert all(span.ended for span in telemetry.spans)
    assert telemetry.span("step").metadata == {"round": 1}


def test_the_root_carries_the_session_and_the_turn() -> None:
    telemetry = RecordingTelemetry()
    open_turn(telemetry).end()
    root = telemetry.spans[0]
    assert root.kind == "span"
    assert root.metadata == {
        "session_id": "s1",
        "turn_id": "t1",
        "config_id": "chamberi_barista_v1",
        "channel": "text",
        "language": "es",
    }


def test_usage_content_and_failure_are_recorded_on_the_span() -> None:
    telemetry = RecordingTelemetry()
    with open_turn(telemetry) as root:
        chat = root.child("chat", "generation")
        chat.set_usage(model_id="m", input_tokens=120, output_tokens=14)
        chat.set_content(input="hola", output="buenas")
        chat.fail("timeout")
        chat.end()
    span = telemetry.span("chat")
    assert span.usage == ("m", 120, 14)
    assert span.content == ("hola", "buenas")
    assert span.failure == "timeout"


def test_leaving_a_span_with_an_exception_marks_it_failed_and_does_not_swallow_it() -> None:
    telemetry = RecordingTelemetry()
    with pytest.raises(RuntimeError), open_turn(telemetry) as root, root.child("tool", "tool"):
        raise RuntimeError("boom")
    assert telemetry.span("tool").failure == "RuntimeError"
    assert all(span.ended for span in telemetry.spans)


def test_events_are_kept_in_order() -> None:
    telemetry = RecordingTelemetry()
    event = StructuredEvent(
        at=datetime(2026, 10, 21, tzinfo=UTC),
        severity="INFO",
        session_id=SID,
        turn_id=TID,
        event="model_round",
        payload={"attempt": 1},
    )
    telemetry.emit(event)
    assert telemetry.events == [event]


def test_the_null_telemetry_accepts_everything_and_keeps_nothing() -> None:
    telemetry = NullTelemetry()
    with open_turn(telemetry) as root:
        root.child("chat", "generation").set_usage(model_id="m", input_tokens=1, output_tokens=1)
        root.annotate(outcome="ok")
    telemetry.emit(
        StructuredEvent(
            at=datetime(2026, 10, 21, tzinfo=UTC),
            severity="INFO",
            session_id=None,
            turn_id=None,
            event="answer_cut",
            payload={},
        )
    )


def test_stdout_telemetry_writes_events_as_json_lines_and_traces_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    telemetry = StdoutTelemetry()
    with open_turn(telemetry) as root:
        root.child("chat", "generation").end()
    telemetry.emit(
        StructuredEvent(
            at=datetime(2026, 10, 21, tzinfo=UTC),
            severity="WARNING",
            session_id=SID,
            turn_id=TID,
            event="turn_failed",
            payload={"code": "timeout"},
        )
    )
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "turn_failed"


def test_leaving_a_span_keeps_the_code_it_was_failed_with() -> None:
    telemetry = RecordingTelemetry()
    with pytest.raises(RuntimeError), open_turn(telemetry) as root, root.child("chat") as chat:
        chat.fail("timeout")
        raise RuntimeError("boom")
    assert telemetry.span("chat").failure == "timeout"


def test_an_abandoned_generator_is_not_a_failure() -> None:
    telemetry = RecordingTelemetry()
    with pytest.raises(GeneratorExit), open_turn(telemetry) as root, root.child("chat"):
        raise GeneratorExit
    assert telemetry.span("chat").failure is None and telemetry.span("chat").ended
