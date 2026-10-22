"""TypeSafe's Jev through OpenRouter's Decisions API: typed questions in, probabilities out.

An evaluation adapter for the signals suite; nothing in ``cafe_norte`` calls it. Only
``choice`` questions are used. The request and response follow
https://openrouter.ai/docs/api/api-reference/alphadecisions (an alpha endpoint)."""

import asyncio
from collections.abc import Mapping

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_MODEL = "typesafe/jev-1.14"
# https://openrouter.ai/typesafe/jev-1.14 : $0.042 / 1M input tokens, output free (2026-10-16).
USD_PER_INPUT_TOKEN = 0.042 / 1_000_000
RETRY_SECONDS = 2.0  # one retry after a 429 or a 5xx


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class ChoiceQuestion(_Model):
    """``criteria`` maps each option to what it means; Jev picks one."""

    instructions: str
    criteria: dict[str, str]

    def wire(self) -> dict[str, object]:
        return {"type": "choice", "instructions": self.instructions, "criteria": self.criteria}


class ChoiceAnswer(_Model):
    choice: str
    probabilities: dict[str, float] = {}
    confidence: float | None = None


class _Usage(_Model):
    input_tokens: int
    output_tokens: int
    cost: float | None = None


class _Response(_Model):
    answers: dict[str, ChoiceAnswer]
    model: str
    usage: _Usage


class Decision(_Model):
    answers: dict[str, ChoiceAnswer]
    model: str  # the dated version that answered
    input_tokens: int
    cost_usd: float  # as reported, or priced from the input tokens


class JevError(Exception):
    """The call did not produce a decision; ``code`` is the HTTP status or a short reason."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class JevClient:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = JEV_MODEL,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def decide(
        self, state: Mapping[str, str], questions: Mapping[str, ChoiceQuestion]
    ) -> Decision:
        body = {
            "model": self.model,
            "state": dict(state),
            "questions": {name: q.wire() for name, q in questions.items()},
        }
        for attempt in (1, 2):
            try:
                response = await self._client.post(DECISIONS_URL, json=body)
            except httpx.TimeoutException as error:
                raise JevError("timeout", code="timeout") from error
            except httpx.HTTPError as error:
                raise JevError(type(error).__name__, code="transport") from error
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt == 1:
                await asyncio.sleep(RETRY_SECONDS)
                continue
            if response.status_code != 200:
                detail = response.text[:300].replace("\n", " ")
                raise JevError(detail, code=str(response.status_code))
            break
        try:
            parsed = _Response.model_validate_json(response.content)
        except ValidationError as error:
            raise JevError(str(error)[:300], code="malformed") from error
        missing = set(questions) - set(parsed.answers)
        if missing:
            raise JevError(f"no answer for {sorted(missing)}", code="malformed")
        cost = parsed.usage.cost
        return Decision(
            answers=parsed.answers,
            model=parsed.model,
            input_tokens=parsed.usage.input_tokens,
            cost_usd=cost if cost is not None else parsed.usage.input_tokens * USD_PER_INPUT_TOKEN,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
