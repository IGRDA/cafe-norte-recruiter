"""Closing a session: the hook and what a closed session refuses."""

from cafe_norte.conversation.contracts import (
    TurnFinished,
)
from cafe_norte.domain.contracts import (
    SessionId,
)
from cafe_norte.model.contracts import (
    ModelText,
    ModelUsage,
    ToolCall,
)
from tests.support.builders import SESSION
from tests.support.harness import (
    STOP,
    WANTS_TOOLS,
    Harness,
    says,
)


async def test_a_terminal_state_from_a_tool_or_from_end_runs_the_close_hook_once() -> None:
    closed: list[SessionId] = []

    async def on_closed(session_id: SessionId) -> None:
        closed.append(session_id)

    end = ToolCall(call_id="e1", name="end_session", arguments_json='{"reason": "not_interested"}')
    h = Harness([[end, WANTS_TOOLS], says("Adiós.")], on_closed=on_closed)
    await h.open_session()
    await h.run("no me interesa")
    await h.runtime.settle()
    assert closed == [SESSION]
    await h.runtime.end(SESSION, "stop")  # already terminal: nothing happens
    await h.runtime.settle()
    assert closed == [SESSION]

    other = Harness([], on_closed=on_closed)
    await other.open_session()
    await other.runtime.end(SESSION, "limit")
    await other.runtime.settle()
    assert closed == [SESSION, SESSION]


async def test_token_usage_is_recorded_under_the_configured_model_not_the_echoed_snapshot() -> None:
    """Providers echo a dated snapshot id; the price table is keyed by the id we configured."""
    usage = ModelUsage(input_tokens=120, output_tokens=14, model_id="fake-2024-07-18")
    h = Harness([[ModelText(text="Hola."), usage, STOP]])
    await h.open_session()
    events = await h.run("Hola")
    finished = events[-1]
    assert isinstance(finished, TurnFinished)
    assert {(u.unit_detail, u.quantity) for u in finished.usage} == {
        ("fake:input", 120),
        ("fake:output", 14),
    }
