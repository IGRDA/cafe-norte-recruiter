"""The Groq adapter against a scripted HTTP transport: wire format in, typed events out."""

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from cafe_norte.conversation.tools import tool_schemas
from cafe_norte.model.chat_completions import ChatCompletionsModel
from cafe_norte.model.contracts import (
    ModelError,
    ModelEvent,
    ModelFinished,
    ModelMessage,
    ModelText,
    ModelUsage,
    ToolCall,
)

URL = "https://groq.test/v1/chat/completions"
TOOLS = tuple(s for s in tool_schemas() if s.name == "update_candidate")
DEADLINE = timedelta(seconds=5)


def sse(*chunks: dict[str, Any], done: bool = True) -> str:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks)
    return body + ("data: [DONE]\n\n" if done else "")


def delta(**fields: Any) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": fields, "finish_reason": None}]}


def tool_delta(index: int, *, id: str | None = None, **function: str) -> dict[str, Any]:
    call: dict[str, Any] = {"index": index, "function": function}
    if id is not None:
        call["id"] = id
    return delta(tool_calls=[call])


def finish(reason: str) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}


async def run(
    body: str, *, status: int = 200, messages: tuple[ModelMessage, ...] | None = None
) -> tuple[list[ModelEvent], list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, text=body)

    model = ChatCompletionsModel(model_id="openai/gpt-oss-120b", base_url=URL, api_key="k")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model.bind_client(client)
        deadline = datetime.now(UTC) + DEADLINE
        sent = messages or (ModelMessage(role="user", content="hola"),)
        events = [e async for e in model.stream(sent, TOOLS, deadline=deadline)]
    return events, requests


async def test_text_deltas_usage_and_finish_are_typed_in_order() -> None:
    usage = {"prompt_tokens": 10, "completion_tokens": 3}
    events, requests = await run(
        sse(
            delta(role="assistant", content="Hola"),
            delta(content=", Lucía."),
            finish("stop"),
            {"choices": [], "usage": usage, "model": "m"},
        )
    )
    assert events == [
        ModelText(text="Hola"),
        ModelText(text=", Lucía."),
        ModelUsage(input_tokens=10, output_tokens=3, model_id="m"),
        ModelFinished(reason="stop"),
    ]
    sent = json.loads(requests[0].content)
    assert sent["stream"] is True
    assert sent["tools"][0]["function"]["name"] == "update_candidate"
    assert requests[0].headers["authorization"] == "Bearer k"


async def test_tool_call_fragments_are_assembled_by_index() -> None:
    events, _ = await run(
        sse(
            tool_delta(0, id="call_1", name="update_candidate", arguments='{"patch": '),
            tool_delta(0, arguments='{"name": "Lucía"}, "evidence_text": "soy Lucía"}'),
            finish("tool_calls"),
        )
    )
    assert events == [
        ToolCall(
            call_id="call_1",
            name="update_candidate",
            arguments_json='{"patch": {"name": "Lucía"}, "evidence_text": "soy Lucía"}',
        ),
        ModelFinished(reason="tool_calls"),
    ]


async def test_reasoning_deltas_are_never_surfaced_as_text() -> None:
    body = sse(delta(reasoning="thinking..."), delta(content="Hola."), finish("stop"))
    events, _ = await run(body)
    assert [e for e in events if isinstance(e, ModelText)] == [ModelText(text="Hola.")]


async def test_assistant_tool_calls_and_tool_results_are_sent_in_wire_format() -> None:
    call = ToolCall(call_id="c1", name="update_candidate", arguments_json="{}")
    messages = (
        ModelMessage(role="assistant", content="", tool_calls=(call,)),
        ModelMessage(role="tool", content="Saved.", tool_call_id="c1"),
    )
    _, requests = await run(sse(delta(content="ok"), finish("stop")), messages=messages)
    sent = json.loads(requests[0].content)["messages"]
    function = {"name": "update_candidate", "arguments": "{}"}
    assert sent[0] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": function}],
    }
    assert sent[1] == {"role": "tool", "content": "Saved.", "tool_call_id": "c1"}


async def test_no_tools_means_no_tools_key_in_the_request() -> None:
    model = ChatCompletionsModel(model_id="m", base_url=URL, api_key="k")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=sse(delta(content="ok"), finish("stop")))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model.bind_client(client)
        deadline = datetime.now(UTC) + DEADLINE
        _ = [e async for e in model.stream((), (), deadline=deadline)]
    assert "tools" not in json.loads(requests[0].content)


UNKNOWN_TOOL = sse(tool_delta(0, id="x", name="rm_rf", arguments="{}"), finish("tool_calls"))
GROQ_TOOL_USE_FAILED = (
    sse(delta(reasoning="hm"), done=False)
    + 'event: error\ndata: {"error": {"message": "Tool call validation failed: '
    '/patch/name expected string", "type": "invalid_request_error", "code": "tool_use_failed"}}\n\n'
)


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        (sse(delta(content="Hola"), done=False), 200, "invalid_response"),
        ("data: {not json}\n\n", 200, "invalid_response"),
        (UNKNOWN_TOOL, 200, "invalid_response"),
        (GROQ_TOOL_USE_FAILED, 200, "invalid_response"),
        (sse(finish("content_filter")), 200, "invalid_response"),
        ('{"error": "bad key"}', 401, "provider_rejected"),
        ("oops", 503, "provider_unavailable"),
    ],
)
async def test_bad_provider_output_raises_a_coded_model_error(
    body: str, status: int, code: str
) -> None:
    with pytest.raises(ModelError) as raised:
        await run(body, status=status)
    assert raised.value.code == code


TOOL_USE_FAILED_WITH_GENERATION = (
    sse(delta(reasoning="hm"), done=False)
    + "event: error\ndata: "
    + json.dumps(
        {
            "error": {
                "message": "Tool call validation failed: /evidence_text minLength",
                "type": "invalid_request_error",
                "code": "tool_use_failed",
                "failed_generation": json.dumps(
                    {
                        "name": "update_candidate",
                        "arguments": {
                            "evidence_text": "",
                            "patch": {"work_authorization": "sí"},
                        },
                    }
                ),
            }
        }
    )
    + "\n\n"
)


async def test_a_rejected_tool_call_with_its_generation_becomes_a_repairable_call() -> None:
    """Groq validates arguments before we do; the model's bad call must still reach the
    registry so the usual repair message goes back to it instead of failing the turn."""
    events, _ = await run(TOOL_USE_FAILED_WITH_GENERATION)
    assert events == [
        ToolCall(
            call_id="rejected_0",
            name="update_candidate",
            arguments_json=json.dumps({"evidence_text": "", "patch": {"work_authorization": "sí"}}),
        ),
        ModelFinished(reason="tool_calls"),
    ]


async def test_a_provider_error_event_keeps_its_code_and_message() -> None:
    with pytest.raises(ModelError) as raised:
        await run(GROQ_TOOL_USE_FAILED)
    assert "tool_use_failed" in str(raised.value) and "/patch/name" in str(raised.value)


async def test_a_rate_limit_is_retried_once_after_the_providers_hint() -> None:
    attempts: list[float] = []
    body_429 = '{"error": {"message": "Rate limit reached. Please try again in 0.05s."}}'

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(time.monotonic())
        if len(attempts) == 1:
            return httpx.Response(429, text=body_429)
        return httpx.Response(200, text=sse(delta(content="Hola."), finish("stop")))

    model = ChatCompletionsModel(model_id="m", base_url=URL, api_key="k")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model.bind_client(client)
        deadline = datetime.now(UTC) + DEADLINE
        events = [e async for e in model.stream((), (), deadline=deadline)]
    assert events == [ModelText(text="Hola."), ModelFinished(reason="stop")]
    assert len(attempts) == 2 and attempts[1] - attempts[0] >= 0.05


async def test_a_second_rate_limit_is_busy_not_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text='{"error": {"message": "try again in 0.01s"}}')

    model = ChatCompletionsModel(model_id="m", base_url=URL, api_key="k")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model.bind_client(client)
        with pytest.raises(ModelError) as raised:
            _ = [e async for e in model.stream((), (), deadline=datetime.now(UTC) + DEADLINE)]
    assert raised.value.code == "busy"


async def test_a_transport_timeout_is_a_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    model = ChatCompletionsModel(model_id="m", base_url=URL, api_key="k")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model.bind_client(client)
        with pytest.raises(ModelError) as raised:
            deadline = datetime.now(UTC) + DEADLINE
            _ = [e async for e in model.stream((), (), deadline=deadline)]
    assert raised.value.code == "timeout"


async def test_cached_input_tokens_are_read_from_the_usage_details() -> None:
    """OpenAI reports the prompt cache inside prompt_tokens; ~5k of each call's tokens repeat."""
    usage = {
        "prompt_tokens": 5000,
        "completion_tokens": 40,
        "prompt_tokens_details": {"cached_tokens": 4608},
    }
    events, _ = await run(sse(finish("stop"), {"choices": [], "usage": usage, "model": "m"}))
    assert (
        ModelUsage(input_tokens=5000, output_tokens=40, cached_input_tokens=4608, model_id="m")
        in events
    )
