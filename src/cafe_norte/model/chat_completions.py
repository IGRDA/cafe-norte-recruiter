"""Streaming Chat Completions adapter (Groq): luzia's wire parsing, plus several calls per turn."""

import asyncio
import json
import re
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from cafe_norte.errors import ErrorCode
from cafe_norte.model.contracts import (
    ModelError,
    ModelEvent,
    ModelFinished,
    ModelMessage,
    ModelText,
    ModelUsage,
    ToolCall,
    ToolSchema,
)

MAX_ARGUMENTS_BYTES = 16 * 1024
MAX_RETRY_WAIT_SECONDS = 8.0
_RETRY_HINT = re.compile(r"try again in ([0-9.]+)\s*s", re.IGNORECASE)
_FINISH: dict[str, Literal["stop", "tool_calls", "length"]] = {
    "stop": "stop",
    "tool_calls": "tool_calls",
    "length": "length",
}


class ChatCompletionsModel:
    """Single-choice streaming completion with tool calls and usage.

    The HTTP client is bound for the application lifespan. Unknown tools, oversized arguments,
    malformed chunks and EOF before completion raise ``ModelError``. The provider's own tools
    are never requested. Reasoning deltas are ignored; their tokens show up in usage."""

    def __init__(self, *, model_id: str, base_url: str, api_key: str) -> None:
        self._model_id = model_id
        self._base_url = base_url
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    def bind_client(self, client: httpx.AsyncClient | None) -> None:
        self._client = client

    @property
    def model_id(self) -> str:
        return self._model_id

    async def stream(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSchema, ...],
        *,
        deadline: datetime,
    ) -> AsyncGenerator[ModelEvent, None]:
        timeout = max((deadline - datetime.now(UTC)).total_seconds(), 0.1)
        body: dict[str, Any] = {
            "model": self._model_id,
            "messages": [_wire(m) for m in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            body["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept": "text/event-stream"}
        known = {t.name for t in tools}
        client = self._client or httpx.AsyncClient()
        try:
            for attempt in (1, 2):
                async with client.stream(
                    "POST", self._base_url, json=body, headers=headers, timeout=timeout
                ) as response:
                    if response.status_code == 200:
                        async for event in _parse(response.aiter_lines(), known):
                            yield event
                        return
                    await response.aread()
                    detail = response.text[:300].replace("\n", " ")
                    if response.status_code == 429 and attempt == 1:
                        # Rate limited: wait what the provider asks, once, then retry.
                        await asyncio.sleep(_retry_wait(detail))
                        continue
                    code: ErrorCode = (
                        "busy"
                        if response.status_code == 429
                        else "provider_rejected"
                        if response.status_code < 500
                        else "provider_unavailable"
                    )
                    raise ModelError(f"HTTP {response.status_code}: {detail}", code=code)
        except httpx.TimeoutException as error:
            raise ModelError("provider timeout", code="timeout") from error
        except httpx.HTTPError as error:
            raise ModelError(
                f"transport: {type(error).__name__}", code="provider_unavailable"
            ) from error
        finally:
            if client is not self._client:
                await client.aclose()


async def _parse(
    lines: AsyncIterator[str], known_tools: set[str]
) -> AsyncGenerator[ModelEvent, None]:
    pending: dict[int, dict[str, str]] = {}
    finish: str | None = None
    usage: ModelUsage | None = None
    async for line in lines:
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError as error:
            raise ModelError("malformed chunk", code="invalid_response") from error
        if "error" in chunk:
            rejected = _rejected_tool_call(chunk["error"], len(pending))
            if rejected is not None:
                # The provider refused the call against the schema. Hand it over anyway so
                # the registry's validation message reaches the model and it can repair.
                yield rejected
                yield ModelFinished(reason="tool_calls")
                return
            raise ModelError(_error_detail(chunk["error"]), code="invalid_response")
        raw_usage = chunk.get("usage") or chunk.get("x_groq", {}).get("usage")
        if raw_usage:
            cached = (raw_usage.get("prompt_tokens_details") or {}).get("cached_tokens")
            usage = ModelUsage(
                input_tokens=int(raw_usage.get("prompt_tokens", 0)),
                output_tokens=int(raw_usage.get("completion_tokens", 0)),
                cached_input_tokens=int(cached or 0),
                model_id=str(chunk.get("model", "")),
            )
        for choice in chunk.get("choices", []):
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                yield ModelText(text=content)
            for call in delta.get("tool_calls") or []:
                entry = pending.setdefault(
                    int(call.get("index", 0)), {"id": "", "name": "", "arguments": ""}
                )
                entry["id"] = call.get("id") or entry["id"]
                function = call.get("function") or {}
                entry["name"] = function.get("name") or entry["name"]
                entry["arguments"] += function.get("arguments") or ""
                if len(entry["arguments"]) > MAX_ARGUMENTS_BYTES:
                    raise ModelError("tool arguments too large", code="invalid_response")
            if choice.get("finish_reason"):
                finish = str(choice["finish_reason"])
    if finish is None:
        raise ModelError("stream ended before finish_reason", code="invalid_response")
    for index in sorted(pending):
        entry = pending[index]
        if entry["name"] not in known_tools:
            raise ModelError(f"unknown tool {entry['name']!r}", code="invalid_response")
        yield ToolCall(
            call_id=entry["id"] or f"call_{index}",
            name=entry["name"],
            arguments_json=entry["arguments"] or "{}",
        )
    if usage is not None:
        yield usage
    reason = _FINISH.get(finish)
    if reason is None:
        raise ModelError(f"finish_reason {finish!r}", code="invalid_response")
    yield ModelFinished(reason=reason)


def _retry_wait(detail: str) -> float:
    match = _RETRY_HINT.search(detail)
    hinted = float(match.group(1)) if match else 1.0
    return min(max(hinted, 0.05), MAX_RETRY_WAIT_SECONDS)


def _rejected_tool_call(error: Any, index: int) -> ToolCall | None:
    """Groq's ``tool_use_failed`` carries the generation it refused; when it names a tool and
    has arguments, it is returned as a call the registry will reject with a usable message."""
    if not isinstance(error, dict) or error.get("code") != "tool_use_failed":
        return None
    try:
        generation = json.loads(error.get("failed_generation") or "")
    except json.JSONDecodeError:
        return None
    if not isinstance(generation, dict) or not isinstance(generation.get("name"), str):
        return None
    arguments = generation.get("arguments", {})
    return ToolCall(
        call_id=f"rejected_{index}",
        name=generation["name"],
        arguments_json=arguments if isinstance(arguments, str) else json.dumps(arguments),
    )


def _error_detail(error: Any) -> str:
    """Groq sends ``event: error`` mid-stream, e.g. ``tool_use_failed`` when the model's
    arguments do not match the schema; the stream then ends without a finish reason."""
    if isinstance(error, dict):
        return f"provider error {error.get('code', '')}: {str(error.get('message', ''))[:300]}"
    return f"provider error: {str(error)[:300]}"


def _wire(message: ModelMessage) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        wire["content"] = message.content or None
        wire["tool_calls"] = [
            {
                "id": c.call_id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.arguments_json},
            }
            for c in message.tool_calls
        ]
    if message.role == "tool":
        wire["tool_call_id"] = message.tool_call_id
    return wire
