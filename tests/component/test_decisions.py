"""OpenRouter's Decisions API adapter over a scripted transport: the request it sends, the
decision it returns, and every failure as a ``ModelError`` with a stable code (D52)."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from cafe_norte.model import decisions
from cafe_norte.model.contracts import ChoiceQuestion, ModelError
from cafe_norte.model.decisions import DecisionsModel
from cafe_norte.model.select import decision_model_from_env

QUESTIONS = {
    "sentiment": ChoiceQuestion(
        instructions="The tone.", criteria={"neutral": "Plain.", "frustrated": "Annoyed."}
    ),
    "language": ChoiceQuestion(
        instructions="Keep or switch.", criteria={"keep": "Stay.", "switch": "Change."}
    ),
}
ANSWER = {
    "id": "d1",
    "model": "typesafe/jev-1.14-20261014",
    "provider": "TypeSafe",
    "answers": {
        "sentiment": {
            "type": "choice",
            "choice": "frustrated",
            "confidence": 0.8,
            "probabilities": {"neutral": 0.15, "frustrated": 0.85},
        },
        "language": {
            "type": "choice",
            "choice": "switch",
            "probabilities": {"keep": 0.08, "switch": 0.92},
        },
    },
    "usage": {"input_tokens": 300, "output_tokens": 0, "cost": 0.0000126},
}


def model(
    *responses: httpx.Response, sent: list[dict[str, object]] | None = None
) -> DecisionsModel:
    queue = list(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        if sent is not None:
            sent.append(json.loads(request.content))
        return queue.pop(0)

    return DecisionsModel(api_key="test-key", transport=httpx.MockTransport(handle))


def soon() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=5)


async def test_the_request_carries_the_state_and_choice_questions() -> None:
    sent: list[dict[str, object]] = []
    jev = model(httpx.Response(200, json=ANSWER), sent=sent)
    decision = await jev.decide({"candidate_said": "hola"}, QUESTIONS, deadline=soon())
    assert sent[0]["model"] == "typesafe/jev-1.14"
    assert sent[0]["state"] == {"candidate_said": "hola"}
    assert sent[0]["questions"] == {
        name: {"type": "choice", "instructions": q.instructions, "criteria": q.criteria}
        for name, q in QUESTIONS.items()
    }
    assert decision.answers["language"].probabilities["switch"] == 0.92
    assert (decision.model_id, decision.input_tokens) == ("typesafe/jev-1.14-20261014", 300)


async def test_a_rate_limit_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decisions, "RETRY_SECONDS", 0)
    jev = model(httpx.Response(429, text="slow down"), httpx.Response(200, json=ANSWER))
    decision = await jev.decide({}, QUESTIONS, deadline=soon())
    assert decision.answers["sentiment"].choice == "frustrated"


@pytest.mark.parametrize(
    ("responses", "code"),
    [
        ([httpx.Response(400, text="bad question")], "provider_rejected"),
        ([httpx.Response(402, text="no credits")], "provider_rejected"),
        ([httpx.Response(503), httpx.Response(503)], "provider_unavailable"),
        ([httpx.Response(429), httpx.Response(429)], "busy"),
        ([httpx.Response(200, text="not json")], "invalid_response"),
        ([httpx.Response(200, json=ANSWER | {"answers": {}})], "invalid_response"),
    ],
)
async def test_a_failed_call_raises_with_a_stable_code(
    responses: list[httpx.Response], code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(decisions, "RETRY_SECONDS", 0)
    with pytest.raises(ModelError) as raised:
        await model(*responses).decide({}, QUESTIONS, deadline=soon())
    assert raised.value.code == code


async def test_an_answer_outside_the_criteria_is_invalid() -> None:
    body = json.loads(json.dumps(ANSWER))
    body["answers"]["language"]["choice"] = "fr"
    with pytest.raises(ModelError) as raised:
        await model(httpx.Response(200, json=body)).decide({}, QUESTIONS, deadline=soon())
    assert raised.value.code == "invalid_response"


async def test_a_timeout_is_a_timeout() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    jev = DecisionsModel(api_key="k", transport=httpx.MockTransport(slow))
    with pytest.raises(ModelError) as raised:
        await jev.decide({}, QUESTIONS, deadline=soon())
    assert raised.value.code == "timeout"


def test_the_selector_needs_openrouter_and_its_key() -> None:
    chosen = decision_model_from_env("openrouter/typesafe/jev-1.14", {"OPENROUTER_API_KEY": "k"})
    assert chosen.model_id == "typesafe/jev-1.14"
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        decision_model_from_env("openrouter/typesafe/jev-1.14", {})
    with pytest.raises(ValueError, match="unknown"):
        decision_model_from_env("openai/gpt-4o-mini", {"OPENROUTER_API_KEY": "k"})
