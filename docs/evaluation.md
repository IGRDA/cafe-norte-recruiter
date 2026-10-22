# Evaluation and observability design

## Principles

1. Deterministic checks decide; judges inform. A scenario passes on checks computed from the
   export document, never on a model's opinion.
2. Fake mode in CI, live mode by hand. CI never spends money.
3. Every number carries its denominator and its `VersionStamp`.
4. Tracing is always on in production (metadata), evaluation is local, and the two meet in
   Langfuse: production traces, evaluation datasets, experiment runs and judge scores on one
   screen, all keyed by prompt, KB and config versions.

## Layers

| Layer | Tooling | Runs |
| --- | --- | --- |
| Unit and property tests of the domain | pytest, hypothesis | CI |
| Scenario integrity (S01–S22) against fakes | own runner, deterministic scorers | CI |
| Scenario behaviour live, candidate simulated | own runner over the HTTP API + `ModelCandidateSimulator` worded from deterministic cues (D43) | local, paid, `--yes` |
| Retrieval quality (41 questions, D48) | own scorers (recall@3, abstention, leakage) + ragas ID-based context precision/recall (`--ragas`, offline) | local, free |
| Judges | ragas through the `AnswerJudge` port (`--judge openai/<model>`, `fake` or `off`; the scorecard defaults to `openai/gpt-4o-mini`) | local, optional, report only |
| Model comparison (gpt-4.1 vs gpt-4o-mini by default, 24 runs) | own runner on one loopback server per model, same prompt/tools/KB | local, once, `--yes`; summary committed |
| Voice latency | browser monotonic timings + server stage timings | hosted, by hand, ≥6 sessions |
| Production traces | OpenTelemetry → Langfuse EU | always |

## The scorecard (D48)

One table of 25 rows says whether a change made Ana better: `make evals ARGS="--suite
scorecard"`. Four tiers, cheapest first, like a test pyramid:

| Tier | Kind | Rows | Decides |
| --- | --- | --- | --- |
| 0 | Deterministic, no reference | valid export, turn length, first-sentence latency, cost, tool calls accepted, language kept, no leak | gate |
| 1 | Deterministic, against a reference | recall@3, ragas ID precision/recall, no cross-store source, abstention, expected facts, ragas `ToolCallF1`, scenario trajectory, extraction, no fabrication, task success, injection held | gate |
| 2 | Judge, against a reference | ragas `Faithfulness`, `FactualCorrectness`; the scenario's goal and rubric bullets as pass/fail ragas `DiscreteMetric` | report |
| 3 | Judge alone | stays on topic, style (pass/fail ragas `DiscreteMetric`) | report |

Answer-level rows come from QA probes: each of the 41 knowledge-base questions as the first
line of its own live session, so an answer is scored apart from the interview around it.
`make evals ARGS="--suite scorecard --mode live"` prints the estimate; `--yes` runs the
scenarios with `live_checks`, the probes and the judges (`openai/gpt-4o-mini` by default).

Each row carries k/n, its target (`docs/architecture.md`) and the delta against the committed
baseline (`evals/results/scorecard/`). A row nothing measured says "not run" and neither passes
nor fails. `make check` holds the gated scenario rows on every fake scenario
(`tests/test_eval_scorecard.py`).

## What a scenario checks

Scorers over `ExportDocument`: brief confirmed at the final revision; booking present or absent;
field values and statuses; no `confirmed` field without evidence from a user turn; review
flags; outcome; language of the last assistant turn; sources shown for policy answers; no
cross-store source; no question repeated for an already captured field.

## What retrieval checks

Recall@3 of expected sections ≥ 90 % on answerable questions; abstention on all five unsupported
questions; zero sources from the other store on the four leakage questions. ragas metrics are
reported next to these, not instead of them.

## Judges

ragas through the `AnswerJudge` port (D48): `Faithfulness` and `FactualCorrectness` on the QA
probes, and a pass/fail `DiscreteMetric` (`evals/prompts/criterion.md`) for staying on topic,
the scenario's goal, style and each rubric bullet. Off for the scenario and comparison suites
unless `--judge openai/<model>`; the live scorecard defaults to `openai/gpt-4o-mini`. A judge
that fails leaves no score and is named, never guessed. Using the answering model as judge is a
known bias and is labelled in the report. Judge rows never pass or fail anything.

## Cost

`observability/cost.py` prices usage from a versioned table. Reports separate measured usage,
estimated usage (generations cut before their usage report, at 4 characters per token) and
unpriced kinds. A voice call's speech usage is measured (D44); `cost_is_partial` means
something is missing, not that something is estimated. The €100 ceiling is tracked by
admission reservation in Postgres plus the Google Cloud budget alerts; neither is a hard cap.

## Live runs (D43)

The same scorers as fake mode, over the public API: `HttpConversation` reads each turn from the
SSE stream into the `TurnObservation` the fake replay builds. Live runs are held to a scenario's
`live_checks` (no turn numbers, relative dates) plus extraction accuracy from the persona.
Every paid command prints its estimated spend first and calls nothing without `--yes`. Langfuse
gets cases as a dataset and runs as experiments with `--langfuse`.
