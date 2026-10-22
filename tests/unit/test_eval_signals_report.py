"""The signals suite's scores, pure: predictions and labels in, k/n rates, sweeps and a
report out (evals/signals_report.py)."""

import pytest
from evals.contracts import Ratio, SignalsReport
from evals.signals_report import (
    language_scores,
    render_markdown,
    sentiment_scores,
    stability,
    summarize,
)

from tests.support.evals import signal_case, signal_prediction


def test_sentiment_scores_count_by_label_and_the_actionable_pair() -> None:
    cases = [
        signal_case(id="a", sentiment="frustrated"),
        signal_case(id="b", sentiment="uncertain"),
        signal_case(id="c", sentiment="neutral"),
        signal_case(id="d", sentiment="neutral"),
    ]
    predictions = [
        signal_prediction("a", sentiment="frustrated"),
        signal_prediction("b", sentiment="frustrated"),  # wrong label, still actionable
        signal_prediction("c", sentiment="uncertain"),  # a false alarm
        signal_prediction("d", error="timeout"),  # scored as neutral
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
        signal_case(id="stay", kind="stay"),
        signal_case(id="mention", kind="mention", text="¿Hace falta inglés?"),
        signal_case(id="asked", kind="explicit", reply_language="en"),
        signal_case(id="wrote", kind="written_other", reply_language="en"),
    ]
    predictions = [
        signal_prediction(
            "stay", reply_language="es", language_probabilities={"es": 0.9, "en": 0.1}
        ),
        signal_prediction(
            "mention", reply_language="en", language_probabilities={"es": 0.4, "en": 0.6}
        ),
        signal_prediction(
            "asked", reply_language="en", language_probabilities={"es": 0.05, "en": 0.95}
        ),
        signal_prediction("wrote", error="timeout"),  # the session language: a miss here
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
        signal_prediction("a", 1, sentiment="neutral"),
        signal_prediction("a", 2, sentiment="neutral"),
        signal_prediction("b", 1, sentiment="neutral"),
        signal_prediction("b", 2, sentiment="frustrated"),
    ]
    assert stability(predictions) == Ratio(k=1, n=2)
    assert stability(predictions[:1]) is None


def test_a_summary_reports_latency_cost_and_errors() -> None:
    cases = [signal_case(id="a"), signal_case(id="b")]
    predictions = [
        signal_prediction(
            "a", sentiment="neutral", reply_language="es", milliseconds=100, cost_eur=1e-5
        ),
        signal_prediction("b", error="timeout", milliseconds=9000),
    ]
    summary = summarize("jev", "typesafe/jev-1.14", cases, predictions)
    assert summary.errors == Ratio(k=1, n=2)
    assert (summary.p50_ms, summary.p95_ms) == (100, 100)
    assert summary.eur_per_1000_turns == pytest.approx(0.01)
    assert summary.sentiment is not None and summary.language is not None


def test_regex_has_no_sentiment_and_production_no_language() -> None:
    cases = [signal_case()]
    regex = summarize("regex", "explicit_controls", cases, [signal_prediction(system="regex")])
    production = summarize(
        "production", "gpt-4o-mini", cases, [signal_prediction(system="production")]
    )
    assert regex.sentiment is None and regex.language is not None
    assert production.language is None and production.sentiment is not None


def test_the_report_names_every_system() -> None:
    cases = [signal_case()]
    summary = summarize("regex", "explicit_controls", cases, [signal_prediction(system="regex")])
    report = SignalsReport(
        generated_at="2026-10-22T10:00:00+00:00",
        cases=1,
        repeat=1,
        prompt_version="ana_v17",
        systems=(summary,),
        predictions=(signal_prediction(system="regex"),),
    )
    assert "| regex | explicit_controls |" in render_markdown(report, cases)
