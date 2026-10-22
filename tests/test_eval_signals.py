"""The signals suite, offline: the synthetic fixture, the Jev client over a scripted transport,
each system over fakes, and the scores computed by hand."""

import argparse
import json
from pathlib import Path

import httpx
import pytest
from evals import jev as jev_module
from evals.contracts import Ratio, SignalCase, SignalPrediction
from evals.jev import ChoiceQuestion, JevClient, JevError
from evals.signals import (
    QUESTIONS,
    JevClassifier,
    LlmClassifier,
    ProductionClassifier,
    RegexClassifier,
    estimate_eur,
    llm_prompt,
    load_cases,
    signals_main,
)
from evals.signals_report import (
    REQUESTED,
    SHOULD_STAY,
    language_scores,
    render_markdown,
    sentiment_scores,
    stability,
    summarize,
)

from cafe_norte.model.contracts import ModelEvent, ModelFinished, ModelText, ModelUsage
from cafe_norte.model.fake import FakeModel
from cafe_norte.observability.cost import load_prices

PRICES = load_prices()
CASES = load_cases()


def case(**overrides: object) -> SignalCase:
    fields: dict[str, object] = {
        "id": "c1",
        "session_language": "es",
        "ana": "¿Qué días puedes trabajar?",
        "text": "De lunes a viernes.",
        "sentiment": "neutral",
        "reply_language": "es",
        "kind": "stay",
    }
    return SignalCase.model_validate(fields | overrides)


def prediction(case_id: str = "c1", repetition: int = 1, **overrides: object) -> SignalPrediction:
    fields: dict[str, object] = {
        "case_id": case_id,
        "system": "jev",
        "repetition": repetition,
        "milliseconds": 100,
    }
    return SignalPrediction.model_validate(fields | overrides)


# ---- the fixture ---------------------------------------------------------------------------------


def test_the_fixture_covers_every_label_kind_and_language() -> None:
    assert len({c.id for c in CASES}) == len(CASES) >= 100
    assert {c.sentiment for c in CASES} == {"neutral", "positive", "frustrated", "uncertain"}
    assert {c.kind for c in CASES} == SHOULD_STAY | REQUESTED | {"written_other"}
    assert {c.session_language for c in CASES} == {"es", "en"}
    for sentiment in ("frustrated", "uncertain", "positive"):
        assert sum(c.sentiment == sentiment for c in CASES) >= 10


def test_a_kind_decides_whether_the_case_switches() -> None:
    for c in CASES:
        assert c.switch == (c.kind not in SHOULD_STAY), c.id


def test_only_selects_cases_and_rejects_unknown_ids() -> None:
    assert [c.id for c in load_cases(only=["es-01", "en-01"])] == ["es-01", "en-01"]
    with pytest.raises(ValueError, match="nope"):
        load_cases(only=["nope"])


# ---- the Jev client ------------------------------------------------------------------------------

ANSWER = {
    "id": "d1",
    "model": "typesafe/jev-1.14-20261014",
    "provider": "TypeSafe",
    "answers": {
        "sentiment": {
            "type": "choice",
            "choice": "frustrated",
            "confidence": 0.8,
            "probabilities": {
                "neutral": 0.1,
                "positive": 0.0,
                "frustrated": 0.85,
                "uncertain": 0.05,
            },
        },
        "reply_language": {
            "type": "choice",
            "choice": "en",
            "probabilities": {"es": 0.08, "en": 0.92},
        },
    },
    "usage": {"input_tokens": 300, "output_tokens": 0, "cost": 0.0000126},
}


def client(*responses: httpx.Response, sent: list[dict[str, object]] | None = None) -> JevClient:
    queue = list(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(json.loads(request.content))
        return queue.pop(0)

    return JevClient("test-key", transport=httpx.MockTransport(handle))


async def test_the_request_carries_the_state_and_choice_questions() -> None:
    sent: list[dict[str, object]] = []
    jev = client(httpx.Response(200, json=ANSWER), sent=sent)
    decision = await jev.decide({"candidate_said": "hola"}, QUESTIONS)
    assert sent[0]["model"] == "typesafe/jev-1.14"
    assert sent[0]["state"] == {"candidate_said": "hola"}
    questions = sent[0]["questions"]
    assert isinstance(questions, dict)
    assert questions["reply_language"]["type"] == "choice"
    assert set(questions["sentiment"]["criteria"]) == {
        "neutral",
        "positive",
        "frustrated",
        "uncertain",
    }
    assert decision.answers["reply_language"].probabilities["en"] == 0.92
    assert decision.cost_usd == 0.0000126
    assert decision.model.startswith("typesafe/jev-1.14")


async def test_a_missing_cost_is_priced_from_the_input_tokens() -> None:
    body = ANSWER | {"usage": {"input_tokens": 1_000_000, "output_tokens": 0}}
    decision = await client(httpx.Response(200, json=body)).decide({}, QUESTIONS)
    assert decision.cost_usd == pytest.approx(0.042)


async def test_a_rate_limit_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jev_module, "RETRY_SECONDS", 0)
    jev = client(httpx.Response(429, text="slow down"), httpx.Response(200, json=ANSWER))
    assert (await jev.decide({}, QUESTIONS)).answers["sentiment"].choice == "frustrated"


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(400, text="bad question"), "400"),
        (httpx.Response(402, text="no credits"), "402"),
        (httpx.Response(200, text="not json"), "malformed"),
        (httpx.Response(200, json=ANSWER | {"answers": {}}), "malformed"),
    ],
)
async def test_a_failed_call_raises_with_its_code(response: httpx.Response, code: str) -> None:
    with pytest.raises(JevError) as raised:
        await client(response).decide({}, QUESTIONS)
    assert raised.value.code == code


# ---- the systems ---------------------------------------------------------------------------------


async def test_jev_answers_both_questions_with_probabilities_and_cost() -> None:
    jev = client(httpx.Response(200, json=ANSWER))
    found = await JevClassifier(jev, usd_per_eur=1.0).classify(case(), 1)
    assert (found.sentiment, found.reply_language, found.error) == ("frustrated", "en", None)
    assert found.language_probabilities == {"es": 0.08, "en": 0.92}
    assert found.cost_eur == 0.0000126


async def test_jev_answering_outside_the_criteria_is_an_error() -> None:
    body = json.loads(json.dumps(ANSWER))
    body["answers"]["reply_language"]["choice"] = "fr"
    found = await JevClassifier(client(httpx.Response(200, json=body)), 1.0).classify(case(), 1)
    assert found.error == "unknown_choice" and found.reply_language is None


async def test_jev_failing_is_recorded_not_raised() -> None:
    found = await JevClassifier(client(httpx.Response(503), httpx.Response(503)), 1.0).classify(
        case(), 1
    )
    assert found.error == "503"


async def test_regex_switches_on_a_request_and_not_on_a_mention() -> None:
    regex = RegexClassifier()
    asked = await regex.classify(case(text="¿Podemos hablar en inglés, por favor?"), 1)
    mentioned = await regex.classify(case(text="¿Hace falta saber inglés para el puesto?"), 1)
    assert (asked.reply_language, mentioned.reply_language) == ("en", "es")
    assert asked.sentiment is None


def reply(text: str) -> FakeModel:
    usage = ModelUsage(input_tokens=600, output_tokens=20, model_id="gpt-4o-mini-2024-07-18")
    events: list[ModelEvent] = [ModelText(text=text), usage, ModelFinished(reason="stop")]
    model = FakeModel([events])
    model.model_id = "gpt-4o-mini"
    return model


async def test_the_llm_system_parses_a_fenced_answer_and_prices_it() -> None:
    model = reply('```json\n{"sentiment": "uncertain", "reply_language": "en"}\n```')
    found = await LlmClassifier(model, PRICES).classify(case(), 1)
    assert (found.sentiment, found.reply_language, found.error) == ("uncertain", "en", None)
    assert found.cost_eur is not None and found.cost_eur > 0
    sent = model.calls[0]
    assert json.loads(sent[1].content)["candidate_said"] == "De lunes a viernes."


async def test_the_llm_system_records_a_malformed_answer() -> None:
    found = await LlmClassifier(reply("frustrated"), PRICES).classify(case(), 1)
    assert found.error == "malformed" and found.sentiment is None


async def test_the_production_system_keeps_the_evidence_rule() -> None:
    backed = reply('{"sentiment": "frustrated", "evidence_text": "lunes"}')
    unbacked = reply('{"sentiment": "frustrated", "evidence_text": "never said"}')
    assert (await ProductionClassifier(backed, PRICES).classify(case(), 1)).sentiment == (
        "frustrated"
    )
    dropped = await ProductionClassifier(unbacked, PRICES).classify(case(), 1)
    assert (dropped.sentiment, dropped.error) == ("neutral", None)


def test_the_llm_is_asked_every_option_jev_is_asked() -> None:
    prompt = llm_prompt()
    for question in QUESTIONS.values():
        assert question.instructions in prompt
        for option, meaning in question.criteria.items():
            assert f"- {option}: {meaning}" in prompt


def test_a_question_serializes_as_a_choice() -> None:
    question = ChoiceQuestion(instructions="Pick.", criteria={"a": "A"})
    assert question.wire() == {"type": "choice", "instructions": "Pick.", "criteria": {"a": "A"}}


# ---- the scores ----------------------------------------------------------------------------------


def test_sentiment_scores_count_by_label_and_the_actionable_pair() -> None:
    cases = [
        case(id="a", sentiment="frustrated"),
        case(id="b", sentiment="uncertain"),
        case(id="c", sentiment="neutral"),
        case(id="d", sentiment="neutral"),
    ]
    predictions = [
        prediction("a", sentiment="frustrated"),
        prediction("b", sentiment="frustrated"),  # wrong label, still actionable
        prediction("c", sentiment="uncertain"),  # a false alarm
        prediction("d", error="timeout"),  # scored as neutral
    ]
    scores = sentiment_scores(list(zip(cases, predictions, strict=True)))
    assert scores.accuracy == Ratio(k=2, n=4)
    assert scores.recall["frustrated"] == Ratio(k=1, n=1)
    assert scores.precision["frustrated"] == Ratio(k=1, n=2)
    assert scores.actionable_recall == Ratio(k=2, n=2)
    assert scores.actionable_precision == Ratio(k=2, n=3)
    assert scores.confusion["neutral"]["uncertain"] == 1
    assert scores.brier is None and scores.sweep == ()


def test_language_scores_split_false_switches_from_missed_requests() -> None:
    cases = [
        case(id="stay", kind="stay"),
        case(id="mention", kind="mention", text="¿Hace falta inglés?"),
        case(id="asked", kind="explicit", reply_language="en"),
        case(id="wrote", kind="written_other", reply_language="en"),
    ]
    predictions = [
        prediction("stay", reply_language="es", language_probabilities={"es": 0.9, "en": 0.1}),
        prediction("mention", reply_language="en", language_probabilities={"es": 0.4, "en": 0.6}),
        prediction("asked", reply_language="en", language_probabilities={"es": 0.05, "en": 0.95}),
        prediction("wrote", error="timeout"),  # the session language: a miss here
    ]
    scores = language_scores(list(zip(cases, predictions, strict=True)))
    assert scores.accuracy == Ratio(k=2, n=4)
    assert scores.false_switches == Ratio(k=1, n=2)
    assert scores.missed_requests == Ratio(k=0, n=1)
    assert scores.by_kind["written_other"] == Ratio(k=0, n=1)
    at_70 = next(r for r in scores.sweep if r.threshold == 0.7)
    assert (at_70.caught, at_70.false_alarms) == (Ratio(k=1, n=1), Ratio(k=0, n=2))
    assert scores.brier == pytest.approx((0.02 + 0.72 + 0.005) / 3)


def test_stability_counts_cases_answered_the_same_every_time() -> None:
    predictions = [
        prediction("a", 1, sentiment="neutral"),
        prediction("a", 2, sentiment="neutral"),
        prediction("b", 1, sentiment="neutral"),
        prediction("b", 2, sentiment="frustrated"),
    ]
    assert stability(predictions) == Ratio(k=1, n=2)
    assert stability(predictions[:1]) is None


def test_a_summary_reports_latency_cost_and_errors() -> None:
    cases = [case(id="a"), case(id="b")]
    predictions = [
        prediction("a", sentiment="neutral", reply_language="es", milliseconds=100, cost_eur=1e-5),
        prediction("b", error="timeout", milliseconds=9000),
    ]
    summary = summarize("jev", "typesafe/jev-1.14", cases, predictions)
    assert summary.errors == Ratio(k=1, n=2)
    assert (summary.p50_ms, summary.p95_ms) == (100, 100)
    assert summary.eur_per_1000_turns == pytest.approx(0.01)
    assert summary.sentiment is not None and summary.language is not None


def test_regex_has_no_sentiment_and_production_no_language() -> None:
    cases = [case()]
    regex = summarize("regex", "explicit_controls", cases, [prediction(system="regex")])
    production = summarize("production", "gpt-4o-mini", cases, [prediction(system="production")])
    assert regex.sentiment is None and regex.language is not None
    assert production.language is None and production.sentiment is not None


# ---- the command ---------------------------------------------------------------------------------


def args(tmp_path: Path, *, yes: bool, systems: list[str]) -> argparse.Namespace:
    return argparse.Namespace(
        only=["es-49", "es-67"],
        systems=systems,
        repeat=1,
        signal_model="openai/gpt-4o-mini",
        yes=yes,
        out=str(tmp_path),
    )


def test_without_yes_only_the_free_regex_runs_and_nothing_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert signals_main(args(tmp_path, yes=False, systems=["regex", "jev"]), env={}) == 0
    out = capsys.readouterr().out
    assert "Nothing paid was called" in out and "| regex |" in out
    assert list(tmp_path.iterdir()) == []


def test_jev_without_its_key_stops_before_calling(tmp_path: Path) -> None:
    assert signals_main(args(tmp_path, yes=True, systems=["jev"]), env={}) == 2


def test_the_estimate_prices_the_llm_and_jev() -> None:
    eur, unpriced = estimate_eur(["production", "llm", "jev"], "openai/gpt-4o-mini", 100, PRICES)
    assert unpriced == [] and 0 < eur < 0.05


def test_the_report_names_every_system() -> None:
    from evals.contracts import SignalsReport

    cases = [case()]
    summary = summarize("regex", "explicit_controls", cases, [prediction(system="regex")])
    report = SignalsReport(
        generated_at="2026-10-22T10:00:00+00:00",
        cases=1,
        repeat=1,
        prompt_version="ana_v17",
        systems=(summary,),
        predictions=(prediction(system="regex"),),
    )
    assert "| regex | explicit_controls |" in render_markdown(report, cases)
