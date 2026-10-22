"""Scores for the signals suite, pure: predictions and labels in, a report out.

A failed call is scored as what the runtime would do with no verdict (neutral, the session
language) and counted under ``errors``. Rates are k/n; medians and percentiles over the calls
that answered."""

import json
import math
from collections.abc import Sequence
from typing import get_args

from cafe_norte.conversation.signals import SOFT_SENTIMENTS
from cafe_norte.domain.contracts import Sentiment
from cafe_norte.errors import Language
from evals.contracts import (
    LanguageKind,
    LanguageScores,
    Ratio,
    SentimentScores,
    SignalCase,
    SignalPrediction,
    SignalsReport,
    SignalSystem,
    SystemSummary,
    ThresholdRow,
)

SENTIMENTS: tuple[Sentiment, ...] = get_args(Sentiment)
KINDS: tuple[LanguageKind, ...] = get_args(LanguageKind)
SHOULD_STAY: frozenset[LanguageKind] = frozenset({"stay", "mention", "borrowed"})
REQUESTED: frozenset[LanguageKind] = frozenset({"explicit", "indirect"})
THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95)
ANSWERS_SENTIMENT: frozenset[SignalSystem] = frozenset({"production", "llm", "jev"})
ANSWERS_LANGUAGE: frozenset[SignalSystem] = frozenset({"regex", "llm", "jev"})


def summarize(
    system: SignalSystem,
    model: str,
    cases: Sequence[SignalCase],
    predictions: Sequence[SignalPrediction],
) -> SystemSummary:
    by_id = {c.id: c for c in cases}
    pairs = [(by_id[p.case_id], p) for p in predictions]
    answered = sorted(p.milliseconds for p in predictions if p.error is None)
    costs = [p.cost_eur for p in predictions if p.cost_eur is not None]
    return SystemSummary(
        system=system,
        model=model,
        calls=len(predictions),
        errors=Ratio(k=sum(p.error is not None for p in predictions), n=len(predictions)),
        sentiment=sentiment_scores(pairs) if system in ANSWERS_SENTIMENT else None,
        language=language_scores(pairs) if system in ANSWERS_LANGUAGE else None,
        stable=stability(predictions),
        p50_ms=_percentile(answered, 0.5),
        p95_ms=_percentile(answered, 0.95),
        eur_per_1000_turns=1000 * sum(costs) / len(costs) if costs else None,
    )


def sentiment_of(prediction: SignalPrediction) -> Sentiment:
    return prediction.sentiment or "neutral"


def language_of(case: SignalCase, prediction: SignalPrediction) -> Language:
    return prediction.reply_language or case.session_language


def sentiment_scores(pairs: Sequence[tuple[SignalCase, SignalPrediction]]) -> SentimentScores:
    confusion = {e: dict.fromkeys(SENTIMENTS, 0) for e in SENTIMENTS}
    for case, prediction in pairs:
        confusion[case.sentiment][sentiment_of(prediction)] += 1
    recall = {s: Ratio(k=confusion[s][s], n=sum(confusion[s].values())) for s in SENTIMENTS}
    precision = {
        s: Ratio(k=confusion[s][s], n=sum(confusion[e][s] for e in SENTIMENTS)) for s in SENTIMENTS
    }
    f1 = [_f1(precision[s].rate, recall[s].rate) for s in SENTIMENTS if recall[s].n]
    soft = [(c.sentiment in SOFT_SENTIMENTS, sentiment_of(p) in SOFT_SENTIMENTS) for c, p in pairs]
    with_probabilities = [(c, p) for c, p in pairs if p.sentiment_probabilities]
    return SentimentScores(
        accuracy=Ratio(k=sum(confusion[s][s] for s in SENTIMENTS), n=len(pairs)),
        macro_f1=sum(f1) / len(f1) if f1 else 0.0,
        recall=recall,
        precision=precision,
        actionable_precision=Ratio(k=sum(e and g for e, g in soft), n=sum(g for _, g in soft)),
        actionable_recall=Ratio(k=sum(e and g for e, g in soft), n=sum(e for e, _ in soft)),
        confusion=confusion,
        brier=_brier([(p.sentiment_probabilities, c.sentiment) for c, p in with_probabilities]),
        sweep=tuple(
            _row(
                t,
                [
                    (
                        c.sentiment in SOFT_SENTIMENTS,
                        max(p.sentiment_probabilities.get(s, 0.0) for s in SOFT_SENTIMENTS) >= t,
                    )
                    for c, p in with_probabilities
                ],
            )
            for t in THRESHOLDS
        )
        if with_probabilities
        else (),
    )


def language_scores(pairs: Sequence[tuple[SignalCase, SignalPrediction]]) -> LanguageScores:
    right = [(c, language_of(c, p) == c.reply_language) for c, p in pairs]
    with_probabilities = [(c, p) for c, p in pairs if p.language_probabilities]
    return LanguageScores(
        accuracy=Ratio(k=sum(ok for _, ok in right), n=len(right)),
        false_switches=Ratio(
            k=sum(not ok for c, ok in right if c.kind in SHOULD_STAY),
            n=sum(c.kind in SHOULD_STAY for c, _ in right),
        ),
        missed_requests=Ratio(
            k=sum(not ok for c, ok in right if c.kind in REQUESTED),
            n=sum(c.kind in REQUESTED for c, _ in right),
        ),
        by_kind={
            kind: Ratio(k=sum(ok for c, ok in right if c.kind == kind), n=n)
            for kind in KINDS
            if (n := sum(c.kind == kind for c, _ in right))
        },
        brier=_brier([(p.language_probabilities, c.reply_language) for c, p in with_probabilities]),
        sweep=tuple(
            _row(
                t,
                [
                    (c.kind in REQUESTED, _other(c, p) >= t)
                    for c, p in with_probabilities
                    if c.kind in REQUESTED | SHOULD_STAY
                ],
            )
            for t in THRESHOLDS
        )
        if with_probabilities
        else (),
    )


def stability(predictions: Sequence[SignalPrediction]) -> Ratio | None:
    """Cases whose answers (both questions) are the same on every repetition."""
    answers: dict[str, set[tuple[str | None, str | None]]] = {}
    for p in predictions:
        answers.setdefault(p.case_id, set()).add((p.sentiment, p.reply_language))
    repeated = {p.case_id for p in predictions if p.repetition > 1}
    if not repeated:
        return None
    return Ratio(k=sum(len(answers[c]) == 1 for c in repeated), n=len(repeated))


def _other(case: SignalCase, prediction: SignalPrediction) -> float:
    """Return the highest probability of a language other than the session language."""
    probabilities = prediction.language_probabilities
    others = (
        p for code, p in probabilities.items() if code not in (case.session_language, "other")
    )
    return max(others, default=0.0)


def _row(threshold: float, outcomes: Sequence[tuple[bool, bool]]) -> ThresholdRow:
    """``outcomes``: (should trigger, triggered) per case."""
    return ThresholdRow(
        threshold=threshold,
        caught=Ratio(k=sum(s and t for s, t in outcomes), n=sum(s for s, _ in outcomes)),
        false_alarms=Ratio(
            k=sum(t and not s for s, t in outcomes), n=sum(not s for s, _ in outcomes)
        ),
    )


def _brier(rows: Sequence[tuple[dict[str, float], str]]) -> float | None:
    if not rows:
        return None
    total = 0.0
    for probabilities, truth in rows:
        labels = set(probabilities) | {truth}
        total += sum((probabilities.get(k, 0.0) - (k == truth)) ** 2 for k in labels)
    return total / len(rows)


def _f1(precision: float | None, recall: float | None) -> float:
    if not precision or not recall:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _percentile(sorted_values: Sequence[int], q: float) -> int | None:
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, math.ceil(q * len(sorted_values)) - 1)]


# ---- rendering -----------------------------------------------------------------------------------


def render_markdown(report: SignalsReport, cases: Sequence[SignalCase]) -> str:
    lines = [
        f"# Signals: {report.generated_at}",
        "",
        f"{report.cases} synthetic cases × {report.repeat} repetitions; production classifier "
        f"prompt {report.prompt_version}. A failed call counts as neutral and the session "
        "language, as the runtime would. Latency is the call alone, off the turn's critical "
        "path in every design here.",
        "",
        "| System | Model | Sentiment acc. | Macro-F1 | Frustrated/uncertain P | R "
        "| Language acc. | False switches | Missed requests | Stable | p50 | p95 "
        "| € / 1000 turns | Errors |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in report.systems:
        sentiment, language = s.sentiment, s.language
        lines.append(
            "| "
            + " | ".join(
                [
                    s.system,
                    s.model,
                    str(sentiment.accuracy) if sentiment else "–",
                    f"{sentiment.macro_f1:.2f}" if sentiment else "–",
                    str(sentiment.actionable_precision) if sentiment else "–",
                    str(sentiment.actionable_recall) if sentiment else "–",
                    str(language.accuracy) if language else "–",
                    str(language.false_switches) if language else "–",
                    str(language.missed_requests) if language else "–",
                    str(s.stable) if s.stable else "–",
                    f"{s.p50_ms} ms" if s.p50_ms is not None else "–",
                    f"{s.p95_ms} ms" if s.p95_ms is not None else "–",
                    f"{s.eur_per_1000_turns:.4f}" if s.eur_per_1000_turns is not None else "0",
                    str(s.errors),
                ]
            )
            + " |"
        )
    for s in report.systems:
        lines += ["", f"## {s.system}", ""]
        if s.sentiment:
            lines += _sentiment_section(s.sentiment)
        if s.language:
            lines += _language_section(s.language)
    lines += ["", "## Misses (first repetition)", ""]
    lines += _misses(report, cases)
    return "\n".join(lines) + "\n"


def render_json(report: SignalsReport) -> str:
    return json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"


def _sentiment_section(scores: SentimentScores) -> list[str]:
    lines = [
        "Sentiment, expected (rows) × predicted (columns):",
        "",
        "| | " + " | ".join(SENTIMENTS) + " | recall | precision |",
        "| --- |" + " --- |" * (len(SENTIMENTS) + 2),
    ]
    for e in SENTIMENTS:
        counts = " | ".join(str(scores.confusion[e][g]) for g in SENTIMENTS)
        lines.append(f"| {e} | {counts} | {scores.recall[e]} | {scores.precision[e]} |")
    if scores.brier is not None:
        lines += ["", f"Brier score: {scores.brier:.3f} (0 is perfect, 2 the worst)."]
    if scores.sweep:
        lines += ["", "Frustrated or uncertain acted on when its probability ≥ t:", ""]
        lines += _sweep(scores.sweep)
    return lines + [""]


def _language_section(scores: LanguageScores) -> list[str]:
    lines = [
        "Reply language by kind (right / cases): "
        + ", ".join(f"{k} {r}" for k, r in scores.by_kind.items())
        + ".",
    ]
    if scores.brier is not None:
        lines += ["", f"Brier score: {scores.brier:.3f}."]
    if scores.sweep:
        lines += [
            "",
            "Switch when p(other language) ≥ t; requests caught (explicit and indirect) and "
            "false alarms (stay, mention, borrowed):",
            "",
        ]
        lines += _sweep(scores.sweep)
    return lines


def _sweep(rows: Sequence[ThresholdRow]) -> list[str]:
    return ["| t | caught | false alarms |", "| --- | --- | --- |"] + [
        f"| {r.threshold:.2f} | {r.caught} | {r.false_alarms} |" for r in rows
    ]


def _misses(report: SignalsReport, cases: Sequence[SignalCase]) -> list[str]:
    by_id = {c.id: c for c in cases}
    lines = ["| Case | Text | Expected | " + " | ".join(s.system for s in report.systems) + " |"]
    lines.append("| --- | --- | --- |" + " --- |" * len(report.systems))
    first = {(p.system, p.case_id): p for p in report.predictions if p.repetition == 1}
    for case in cases:
        cells, wrong = [], False
        for s in report.systems:
            p = first.get((s.system, case.id))
            if p is None:
                cells.append("")
                continue
            got: list[str] = []
            if s.system in ANSWERS_SENTIMENT:
                got.append(sentiment_of(p))
                wrong = wrong or sentiment_of(p) != case.sentiment
            if s.system in ANSWERS_LANGUAGE:
                got.append(language_of(case, p))
                wrong = wrong or language_of(case, p) != case.reply_language
            cells.append(" · ".join(got) + (" (error)" if p.error else ""))
        if wrong:
            text = by_id[case.id].text.replace("|", "/")
            expected = f"{case.sentiment} · {case.reply_language} ({case.kind})"
            lines.append(f"| {case.id} | {text} | {expected} | " + " | ".join(cells) + " |")
    return lines
