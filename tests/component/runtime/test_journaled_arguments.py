"""Tool arguments in the journal (KI-06, D44)."""

import json

from cafe_norte.conversation.contracts import (
    ToolStarted,
)
from cafe_norte.conversation.signals import ModelSignalAnalyzer
from cafe_norte.model.contracts import (
    ModelText,
    ModelUsage,
    ToolCall,
)
from cafe_norte.model.fake import FakeModel
from tests.support.harness import (
    STOP,
    WANTS_TOOLS,
    Harness,
    readback_pending,
    says,
    with_date_read_back,
)


async def test_a_tool_call_is_journaled_with_its_arguments_redacted() -> None:
    call = ToolCall(
        call_id="p1",
        name="update_candidate",
        arguments_json=json.dumps(
            {"patch": {"phone": "612 345 678"}, "evidence_text": "Mi móvil es 612 345 678"}
        ),
    )
    h = Harness([[call, WANTS_TOOLS], says("")])
    await h.open_session()
    await h.run("Mi móvil es 612 345 678")
    started = [json.loads(e.payload_json) for e in await h.journal() if e.kind == "tool_started"]
    assert started[0]["name"] == "update_candidate"
    assert "[phone]" in started[0]["arguments"] and "612" not in started[0]["arguments"]
    assert '"patch"' in started[0]["arguments"]


async def test_the_runtimes_own_call_is_journaled_with_its_arguments() -> None:
    h = with_date_read_back(says("Perfecto."))
    await h.open_session()
    await readback_pending(h)
    events = await h.run("Sí.", "in-2")
    started = [e for e in events if isinstance(e, ToolStarted)]
    assert started[0].arguments == '{"answer": "affirm"}'


def test_a_journaled_tool_start_from_before_arguments_still_reads() -> None:
    assert ToolStarted.model_validate_json('{"type": "tool_started", "name": "x"}').arguments == ""


async def test_the_classifiers_tokens_are_recorded_under_the_turn_it_classified() -> None:
    usage = ModelUsage(input_tokens=210, output_tokens=12, model_id="fake-2024-07-18")
    verdict = ModelText(text='{"sentiment": "neutral", "evidence_text": ""}')
    analyzer = ModelSignalAnalyzer(FakeModel([[verdict, usage, STOP]]))
    h = Harness([says("Hola.")], signals=analyzer)
    await h.open_session()
    events = await h.run("Hola.")
    await h.runtime.settle()
    source = events[0].turn_id  # type: ignore[union-attr]
    measured = [u for u in await h.usage() if not u.estimated]  # the turn's own is not
    assert {(u.turn_id, u.unit_detail, u.quantity, u.estimated) for u in measured} == {
        (source, "fake:input", 210, False),
        (source, "fake:output", 12, False),
    }
