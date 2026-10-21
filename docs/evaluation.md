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
| Scenario integrity (S01–S18) against fakes | own runner, deterministic scorers | CI |
| Scenario behaviour live, candidate simulated | own runner over the HTTP API + `ModelCandidateSimulator` worded from deterministic cues (D43) | local, paid, `--yes` |
| Retrieval quality (24 questions) | own scorers (recall@3, abstention, leakage) + ragas ID-based context precision/recall (`--ragas`, offline) | local, free |
| Rubric judge | `evals/judge.py` through the `Model` port (`--judge provider/model`) | local, optional |
| Model comparison (gpt-4o-mini vs gpt-4o by default, 24 runs) | own runner on one loopback server per model, same prompt/tools/KB | local, once, `--yes`; summary committed |
| Voice latency | browser monotonic timings + server stage timings | hosted, by hand, ≥6 sessions |
| Production traces | OpenTelemetry → Langfuse EU | always |

## What a scenario checks

Scorers over `ExportDocument`: brief confirmed at the final revision; booking present or absent;
field values and statuses; no `confirmed` field without evidence from a user turn; review
flags; outcome; language of the last assistant turn; sources shown for policy answers; no
cross-store source; no question repeated for an already captured field.

## What retrieval checks

Recall@3 of expected sections ≥ 90 % on answerable questions; abstention on all four unsupported
questions; zero sources from the other store on the four leakage questions. ragas metrics are
reported next to these, not instead of them.

## Judge

Default off. `--judge provider/model` enables rubric bullets. Output must be one JSON boolean per
bullet; anything else is recorded as unparsable, never coerced.
Using the answering model as judge is a known bias and is labelled in the report.

## Cost

`observability/cost.py` prices usage from a versioned table. Reports separate measured usage,
estimated usage (cancelled generations) and unpriced kinds. The €100 ceiling is tracked by
admission reservation in Postgres plus the Google Cloud budget alerts; neither is a hard cap.

## Live runs (D43)

The same scorers as fake mode, over the public API: `HttpConversation` reads each turn from the
SSE stream into the `TurnObservation` the fake replay builds. Live runs are held to a scenario's
`live_checks` (no turn numbers, relative dates) plus extraction accuracy from the persona.
Every paid command prints its estimated spend first and calls nothing without `--yes`. Langfuse
gets cases as a dataset and runs as experiments with `--langfuse`.
