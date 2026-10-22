"""OpenRouter's Decisions API: TypeSafe's Jev behind the ``DecisionModel`` port.

An alpha endpoint (https://openrouter.ai/docs/api/api-reference/alphadecisions): a state and
``choice`` questions in, one probability per option out, no text. Only ``choice`` questions
are sent. A 429 or a 5xx is retried once; every other failure is a ``ModelError``."""

import asyncio
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from cafe_norte.errors import ErrorCode
from cafe_norte.model.contracts import ChoiceAnswer, ChoiceQuestion, Decision, ModelError

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_MODEL = "typesafe/jev-1.14"
RETRY_SECONDS = 2.0  # one retry after a 429 or a 5xx


class _Reply(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    class _Answer(BaseModel):
        model_config = ConfigDict(frozen=True, extra="ignore")

        choice: str
        probabilities: dict[str, float] = {}

    class _Usage(BaseModel):
        model_config = ConfigDict(frozen=True, extra="ignore")

        input_tokens: int
        output_tokens: int

    answers: dict[str, _Answer]
    model: str
    usage: _Usage


class DecisionsModel:
    """One HTTP client for the process; ``model_id`` is the requested model (it prices the
    tokens), ``Decision.model_id`` the dated version that answered."""

    def __init__(
        self,
        *,
        api_key: str,
        model_id: str = JEV_MODEL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model_id = model_id
        self._client = httpx.AsyncClient(
            transport=transport, headers={"Authorization": f"Bearer {api_key}"}
        )

    @property
    def model_id(self) -> str:
        return self._model_id

    async def decide(
        self,
        state: dict[str, str],
        questions: dict[str, ChoiceQuestion],
        *,
        deadline: datetime,
    ) -> Decision:
        body = {
            "model": self._model_id,
            "state": state,
            "questions": {
                name: {"type": "choice", "instructions": q.instructions, "criteria": q.criteria}
                for name, q in questions.items()
            },
        }
        for attempt in (1, 2):
            timeout = max((deadline - datetime.now(UTC)).total_seconds(), 0.1)
            try:
                response = await self._client.post(DECISIONS_URL, json=body, timeout=timeout)
            except httpx.TimeoutException as error:
                raise ModelError("decision timeout", code="timeout") from error
            except httpx.HTTPError as error:
                raise ModelError(type(error).__name__, code="provider_unavailable") from error
            status = response.status_code
            if (status == 429 or status >= 500) and attempt == 1:
                await asyncio.sleep(RETRY_SECONDS)
                continue
            if status != 200:
                code: ErrorCode = (
                    "busy"
                    if status == 429
                    else "provider_rejected"
                    if status < 500
                    else "provider_unavailable"
                )
                detail = response.text[:300].replace("\n", " ")
                raise ModelError(f"HTTP {status}: {detail}", code=code)
            break
        try:
            reply = _Reply.model_validate_json(response.content)
        except ValidationError as error:
            raise ModelError(f"malformed decision: {str(error)[:200]}") from error
        for name, question in questions.items():
            answer = reply.answers.get(name)
            if answer is None or answer.choice not in question.criteria:
                raise ModelError(f"no valid answer for {name}")
        return Decision(
            answers={
                name: ChoiceAnswer(
                    choice=reply.answers[name].choice,
                    probabilities=reply.answers[name].probabilities,
                )
                for name in questions
            },
            model_id=reply.model,
            input_tokens=reply.usage.input_tokens,
            output_tokens=reply.usage.output_tokens,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
