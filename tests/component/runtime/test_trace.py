"""The trace of a turn, and the conversation tail it carries."""

import json

from cafe_norte.conversation.runtime import Limits, conversation_tail
from cafe_norte.model.contracts import (
    ModelMessage,
    ModelText,
    ModelUsage,
    ToolCall,
)
from cafe_norte.model.fake import FakeModel
from cafe_norte.observability.fakes import RecordedSpan
from tests.support.builders import SESSION
from tests.support.harness import (
    FAST_DEADLINE,
    STOP,
    WANTS_TOOLS,
    Harness,
    name_call,
    says,
)

SEARCH = ToolCall(
    call_id="k1",
    name="search_knowledge",
    arguments_json=json.dumps(
        {"question": "¿Dónde estáis?", "queries": ["dirección del local"], "topic": "any"}
    ),
)
END = ToolCall(call_id="e1", name="end_session", arguments_json='{"reason": "not_interested"}')


def roots(h: Harness) -> list[RecordedSpan]:
    return [span for span in h.telemetry.spans if span.parent is None]


async def test_a_turn_is_one_trace_shaped_like_the_agent_loop() -> None:
    h = Harness([[name_call(), WANTS_TOOLS], says("Hola.")])
    await h.open_session()
    await h.run("Soy Lucía")
    assert h.telemetry.outline() == [
        "handle-candidate-turn",
        "  write-user-turn",
        "  invoke-agent [agent]",
        "    step [chain]",
        "      chat [generation]",
        "      update_candidate [tool]",
        "    step [chain]",
        "      chat [generation]",
        "  write-assistant-turn",
    ]
    assert all(span.ended for span in h.telemetry.spans)
    assert [s.metadata.get("round") for s in h.telemetry.spans if s.name == "step"] == [1, 2]


async def test_the_root_names_the_turn_and_summarises_it_without_the_words() -> None:
    h = Harness([[name_call(), WANTS_TOOLS], says("Hola.")])
    await h.open_session()
    await h.run("Soy Lucía")
    (root,) = roots(h)
    assert root.metadata["session_id"] == SESSION and root.metadata["channel"] == "text"
    assert root.metadata["outcome"] == "finished"
    assert (root.metadata["tools_called"], root.metadata["rounds"]) == (1, 2)
    assert (root.metadata["chars_in"], root.metadata["chars_out"]) == (len("Soy Lucía"), 5)
    assert root.content == ("Soy Lucía", "Hola.")  # the adapter drops this unless content is on
    assert root.failure is None


async def test_a_generation_carries_the_tokens_under_the_configured_model() -> None:
    usage = ModelUsage(input_tokens=120, output_tokens=14, model_id="fake-2024-07-18")
    h = Harness([[ModelText(text="Hola."), usage, STOP]])
    await h.open_session()
    await h.run("Hola")
    chat = h.telemetry.span("chat")
    assert chat.usage == ("fake", 120, 14)
    assert chat.content == ("user: Hola", "Hola.")
    assert chat.metadata["attempt"] == 1 and "first_output_ms" in chat.metadata


async def test_a_knowledge_lookup_is_a_retriever_and_a_write_is_a_plain_tool() -> None:
    h = Harness([[SEARCH, name_call(), WANTS_TOOLS], says("Calle Mayor.")])
    await h.open_session()
    await h.run("¿Dónde estáis? Soy Lucía")
    kinds = {s.name: s.kind for s in h.telemetry.spans}
    assert kinds["search_knowledge"] == "retriever" and kinds["update_candidate"] == "tool"
    update = h.telemetry.span("update_candidate")
    assert update.metadata["ok"] is True
    assert update.content is not None
    assert json.loads(update.content[0] or "")["patch"] == {"name": "Lucía"}


async def test_a_retried_round_is_one_generation_that_says_so() -> None:
    h = Harness([says("Vale, apuntado.")], limits=FAST_DEADLINE, slow_calls=1)
    await h.open_session()
    await h.run("De lunes a viernes")
    (chat,) = [s for s in h.telemetry.spans if s.name == "chat"]
    assert chat.metadata["attempt"] == 2 and chat.metadata["silent_attempts"] == 1
    assert chat.failure is None


async def test_a_failed_turn_marks_the_root_and_the_round_and_ends_every_span() -> None:
    h = Harness([], limits=Limits(llm_first_output_seconds=0.05))
    h.runtime._model = FakeModel([], delay_seconds=0.2, fallback=says("tarde"))
    await h.open_session()
    await h.run("Hola")
    (root,) = roots(h)
    assert root.failure == "timeout" and root.metadata["outcome"] == "failed"
    assert h.telemetry.span("chat").failure == "timeout"
    assert all(span.ended for span in h.telemetry.spans)


async def test_a_turn_on_an_ended_session_is_a_failed_root_and_nothing_else() -> None:
    h = Harness([[END, WANTS_TOOLS], says("Adiós.")])
    await h.open_session()
    await h.run("No me interesa", "in-1")
    await h.run("¿Hola?", "in-2")
    last = roots(h)[-1]
    assert last.failure == "session_ended" and last.ended
    assert [s for s in h.telemetry.spans if s.parent == h.telemetry.spans.index(last)] == []


async def test_a_failed_store_write_fails_its_span() -> None:
    h = Harness([says("Hola."), says("Hola.")])
    await h.open_session()
    await h.run("Hola", "same")
    await h.run("Hola", "same")  # the channel repeated an input id: the user-turn write conflicts
    second = roots(h)[-1]
    assert second.failure == "conflict"
    write = [s for s in h.telemetry.spans if s.name == "write-user-turn"][-1]
    assert write.failure is not None and write.ended


async def test_each_generation_records_the_conversation_the_model_saw() -> None:
    """Without the system prompt: prompt_version already pins that."""
    h = Harness([[name_call(), WANTS_TOOLS], says("Hola.")])
    await h.open_session()
    await h.run("Soy Lucía")
    first, second = [s for s in h.telemetry.spans if s.name == "chat"]
    assert first.content is not None and first.content[0] == "user: Soy Lucía"
    assert second.content is not None and second.content[0] is not None
    seen = second.content[0].splitlines()
    assert seen[0] == "user: Soy Lucía"
    assert seen[1] == "assistant:  [call update_candidate]"
    assert seen[2].startswith("tool: Saved: name")


async def test_a_generation_is_marked_when_its_first_output_arrives() -> None:
    h = Harness([says("Hola.")])
    await h.open_session()
    await h.run("Hola")
    assert h.telemetry.span("chat").first_output is True


def message(role: str, content: str) -> ModelMessage:
    return ModelMessage(role=role, content=content)


def test_the_conversation_tail_keeps_the_latest_messages_within_its_budget() -> None:
    messages = [
        message("system", "x" * 5000),
        message("user", "primero " + "a" * 50),
        message("assistant", "segundo " + "b" * 50),
        message("user", "tercero"),
    ]
    assert conversation_tail(messages, budget=40) == "user: tercero"
    assert conversation_tail(messages, budget=10_000).splitlines()[0].startswith("user: primero")
    assert "system" not in conversation_tail(messages, budget=10_000)


def test_the_latest_message_is_kept_even_when_it_alone_exceeds_the_budget() -> None:
    assert conversation_tail([message("user", "z" * 100)], budget=10) == "user: " + "z" * 100
