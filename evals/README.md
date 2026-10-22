# Evaluations

Four suites, one typed runner, two execution modes. Deterministic runs use the fake model and
are part of CI; live runs call paid providers and are manual.

| Suite | Cases | Scorers | Mode |
| --- | --- | --- | --- |
| `scenarios` | S01–S22 (`cases/scenarios/*.yaml`): scripted turns for CI, persona for the simulator | deterministic checks on the final `ExportDocument` (fields, confirmations, booking, flags, no fabricated confirmed value) + optional rubric judge | CI (fake) and live |
| `retrieval` | 24 questions (`cases/retrieval/questions.yaml`): 16 answerable, 4 unsupported, 4 leakage | recall@3 of expected sections, zero cross-store sources; unsupported questions reported with what came back after the floor (D27); ragas ID-based context precision and recall with `--ragas` | `make evals-retrieval` (`--retriever hybrid` needs the extra; `lexical` runs in CI) |
| `comparison` | 6 multi-turn cases × 2 models × 2 repetitions (`cases/comparison/cases.yaml`), 24 runs on one loopback server per model, same prompt, tools, KB and configuration | each case's scenario `live_checks`, extraction accuracy, tool calls ok, grounding checks, runs passed, latency, cost; summary and runs (no exports) committed under `results/comparison/` | live, bounded, `--yes` |
| `signals` | 122 synthetic candidate turns (`cases/signals/turns.yaml`), es and en sessions, labelled by construction | sentiment accuracy, macro-F1, frustrated/uncertain precision and recall; reply-language accuracy, false switches, missed requests, accuracy per kind; stability across repetitions, p50/p95 latency, € per 1000 turns; Brier score and threshold sweeps for a system with probabilities | offline experiment, `make evals-signals` (regex free; the rest with `--yes`) |

```bash
make evals ARGS="--suite scenarios --mode fake"          # what CI runs
make evals ARGS="--suite scenarios --mode live --only S01 S02"          # prints the estimate only
make evals ARGS="--suite scenarios --mode live --only S01 S02 --yes"    # spends
make evals ARGS="--suite scenarios --mode live --only S01 --model fake --simulator fake --yes"  # free dry run
make evals-retrieval ARGS="--retriever hybrid"   # lexical: BM25 only, no extra
make evals-retrieval ARGS="--retriever lexical --ragas"   # adds ragas' ID-based metrics, offline
make compare                                   # 6 cases x 2 models x 2 runs: prints the estimate only
make compare ARGS="--yes"                      # spends; default models openai/gpt-4.1 openai/gpt-4o-mini
make compare ARGS="--models fake --repeat 1 --simulator fake --max-turns 2 --yes"  # free dry run
make evals-signals                             # regex only, free; prints the estimate for the rest
make evals-signals ARGS="--yes"                # regex, production, llm and jev, 2 repetitions
make evals-signals ARGS="--cases heldout --yes" # the same on the held-out set
make evals-signals ARGS="--systems regex jev --only es-49 en-35 --repeat 1 --yes"
uv run python -m evals.run --list
```

## What runs today

Scenarios in fake mode. `S01`–`S11`, `S16`–`S19` replay against the real runtime, handlers,
domain, memory store and the real `HybridRetriever` over `kb/` with `FakeEmbedder`, driven by
the scripted `FakeModel`; `tests/test_scenarios.py` parametrizes over the
files, so `make check` and CI fail on a broken scenario with the check named. `make evals
ARGS="--suite scenarios --mode fake"` is the same replay printed as a table. Every fake run
carries its `ExportDocument` in `RunRecord.export`; `make export-example` writes S01's to
`examples/`.

Live mode (D43) runs the scenarios that carry `live_checks` against a real model with the
simulated candidate: by default on a loopback server the runner starts with `--model`
(memory store, text only, traces tagged `evaluation`), or against `--base-url` (hosted or
`make run`; the access code comes from `EVAL_ACCESS_CODE`, never the command line). Every
live command prints its estimated spend and calls nothing without `--yes`. Results go to
`evals/results/live/<UTC time>-<suite>/`: `report.md`, `report.json` (no conversations) and `exports/`
(full exports); the directory is ignored by git. A run that breaks is a recorded miss with
its reason.

### Adding a scenario

One file `evals/cases/scenarios/Snn.yaml`:

- `scripted_turns`: the candidate's lines, in order.
- `fake_script`: one list per line with what a well-behaved model does: `{tool: name, args:
  {...}}` rounds, then `{say: "…"}` to end the turn (`say: ""` when the system speaks, as after
  a read-back or the brief). One model round per step.
- `fake_signals` (optional): one `{sentiment, evidence_text}` per line, the classifier's
  verdict. When present the real `ModelSignalAnalyzer` runs over a fake model and the runner
  waits for it after each turn (`Runtime.settle`), so the asynchronous path is deterministic.
- `checks`: names from `evals/scorers.py` (`field_equals`, `field_status`, `brief_confirmed`,
  `lifecycle_is`, `outcome_is`, `booking_present`, `booking_absent`,
  `no_fabricated_confirmed_values`, `max_repeated_questions`, `review_flag_present`,
  `sources_shown_for_policy_answer`, `no_cross_store_sources`,
  `language_of_last_assistant_turn`, `brief_language`, `signal_recorded`,
  `said_control_reply`, `tool_ok`, `turn_failed`, `brief_unconfirmed`,
  `sources_shown_on_any_turn`, `readback_assurance`
  (how the pending read-back was confirmed: heard, reviewed or waived, D39) and
  `readback_said_whole` (how many turns said its whole text); an unknown name raises).
  The review's `¿Está bien?` after each part is a system question, never a repeated one.
- `live_checks` (optional): the checks a live run is held to. A simulated candidate adapts to
  Ana and runs on a real clock, so these name no turn (`sources_shown_on_any_turn` instead of
  `sources_shown_for_policy_answer`) and dates are relative (`value: next monday`, resolved
  against the session's day). A scenario without them is not run live. Extraction accuracy is
  computed apart from the checks: the persona's exact-match facts (name, phone, permit, days,
  shifts, hours, start date; corrections applied, declined fields left out) against the final
  record; free text such as `experience` is the judge's to read.
- `persona`: what the simulated candidate knows (`facts`, the first value of a field it later
  `corrects`), `asks`, `declines`, `mood`, `switch_language_after_turn`, `withdraws_after_turn`,
  `wants_interview`.
- `today`: the fake clock's date, so relative dates in the script stay fixed.
- `seconds_per_turn` (optional): how long each turn lasts on the runtime's clock; the active-time
  cap needs it (`S18`).
- `faults` (optional): `{turn, kind}` with `kind` one of `interrupt` (the candidate speaks over
  Ana after `after_sentences`; the turn is closed and the heard text acknowledged), `model` (the
  provider is down for that turn) or `storage` (the store refuses the next save). A turn cut
  short or failed never reaches its closing `say`, so its script stops where the turn does
  (`S08`, `S16`). A turn a `turn_failed` check names is not counted as a provider failure.

Checks run over `SessionResult` (final state, transcript, what Ana said per turn); the export
is built as well, and the checks move to it when the remaining checks land (D21).

## How it fits together

- `contracts.py`: `Scenario`, `RetrievalCase`, `RetrievalRun`/`RetrievalReport`, `ComparisonCase`, `Check`, `RunRecord`, `Report`, and the `Scorer` and `CandidateSimulator` ports.
- `observation.py`: folds one turn's runtime events into a `TurnObservation` (said, shown, called, failed, usage, timings); the fake replay and the live SSE stream feed the same reducer, and `session_result` assembles what the checks read.
- `live.py`: `HttpConversation` drives one session through the public API (access, create, one POST per line, the turn's events from SSE resumed by `Last-Event-ID` until it ends, then end, snapshot and export); a turn with no end after 90 s is reported as `no_turn_end`. `drive` runs Ana's opening and then asks a `Candidate` (scripted lines or the simulator) for each next line until it has none, the session leaves `active`, or 24 lines were said. `serve` runs an app on `127.0.0.1` with a free port, so a comparison builds one app per model; `tests/test_eval_loopback.py` replays S03 that way and gets the fake mode's verdicts.
- `spend.py`: what a paid command will cost before it spends: synthetic usage from the per-turn assumptions in `docs/architecture.md`, priced by `observability.cost.estimate` with the export's own table; a model with no price is named, never counted as free.
- `retrieval.py`: the retrieval suite: fixture questions through a retriever, recall@3, leakage, timings; one committed JSON per embedding model and KB version.
- `runner.py`: loads cases, drives a session through the HTTP API (live) or the runtime with fakes (CI), collects the export and timings, applies scorers, writes a report with a `VersionStamp`.
- `scorers.py`: pure functions over `ExportDocument` and retrieval results.
- `simulator.py`: the simulated candidate. `cue(persona, language, transcript)` decides deterministically what the next line does (raise `asks[k]` on line k+2, correct on the first brief read-back only, switch language after line N, withdraw after line N, the persona's mood); an LLM through the `Model` port only words it, so every behaviour happens and on a line the report can name. Its prompt carries today's date and each relative date fact with the day it means (`next monday (Monday 26 October 2026)`): the model miscounts weekdays on its own.
- `judge.py`: rubric judge through the same `Model` port (`--judge provider/model`, prompt `prompts/judge.md`): one JSON boolean per scenario `rubric` bullet over the exported transcript, or `unparsable` with the reason (a string "true" is not a boolean). Secondary signal, never pass/fail: the report shows it in its own section and flags a judge that is also the answering model.
- `ragas_bridge.py`: answerable retrieval runs as ragas samples (chunk ids retrieved and expected) scored by ragas' ID-based context precision and recall: offline, no model, next to recall@3 (`make evals-retrieval ARGS="--ragas"`). A question that retrieved nothing has no precision and is counted apart. Faithfulness needs answers and a paid judge and is not computed.
- `langfuse_sync.py`: cases as a Langfuse dataset (`cafe-norte-<suite>`, one item per case, stable ids) and runs as experiment runs (one per model and repetition, `<prompt> · <model> · r<n>`), through the `ExperimentSink` port (`FakeSink` in tests). `SdkSink` replays recorded runs through the SDK's experiment runner, the supported write path since the dataset-run-items endpoint was deprecated: checks, `passed`, extraction, cost and judge answers become scores, and a span carries the run's `session_id`, so the experiment item sits next to the server's turn traces. `--langfuse` on a live or comparison run, or `python -m evals.langfuse_sync <report.json>` afterwards; nothing is sent without `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`.
- `report.py`: `summarize` (pure) gives one row per answering model: runs passed, extraction (exact facts), no fabricated field, tool calls ok, grounding checks, median first sentence and turn time, cost of the priced runs; then by configuration and language, by case, and every miss with its reason. Every rate is k/n and every median says its n ("2.0 s (n=96 turns)"). `render_markdown` states the spec's targets next to the numbers; `render_json` is the same without exports.

Raw live reports contain conversations and stay out of git (`results/` is ignored); the
comparison's aggregated structured results and the retrieval scores are committed under
`results/` by name exception in `.gitignore` once they exist.

## Signals: sentiment and reply language (Jev experiment)

An offline experiment, not a gate: does a decision model with calibrated probabilities beat
what runs today, so that one call beside the turn could carry both the sentiment and the
language switch? Four systems answer the same synthetic turns (`evals/signals.py`):

| System | What it is | Answers |
| --- | --- | --- |
| `regex` | `explicit_controls` + `requested_language`, the runtime's switch today (D28) | language |
| `production` | `ModelSignalAnalyzer` with the shipped `classifier.md`, evidence rule included (D30) | sentiment |
| `llm` | the same two questions Jev gets, as JSON, from the chat model (`--signal-model`, default `openai/gpt-4o-mini`) | both |
| `jev` | TypeSafe's `typesafe/jev-1.14` through OpenRouter's Decisions API (`evals/jev.py`), two `choice` questions in one call | both, with probabilities |

The questions live once in `QUESTIONS`; the `llm` prompt is written from them. Language is asked
as `keep` or `switch` relative to the session, not as `es`/`en`: on the dev set that took Jev
from 8/38 missed requests to 0/38, and the held-out set confirmed it (0/36, no false switch). Each system reads
`session_language`, what Ana said last and what the candidate said. A failed call scores as the
runtime's fallback (neutral, session language) and is counted under errors. `written_other` (a
whole message in the other language, no request) is labelled a switch but kept out of the false
switch and missed request rates, because D28 deliberately keeps the session language there.
Two case sets (`--cases`): `dev`, the hand-written `turns.yaml` the questions may be tuned on,
and `heldout`, 83 turns written by gpt-4.1 from a fixed grid (`evals/signals_generate.py`: one call
writes each cell's lines, a second checks each line against the cell and drops what does not
fit; labels come from the cell, nothing is relabelled). The held-out set is only scored.
Committed results go to `results/signals/<UTC time>-<set>-<systems>.{md,json}`: synthetic text
only.

Keys: `OPENAI_API_KEY` for `production` and `llm`; `OPENROUTER_API_KEY` for `jev` (openrouter.ai →
Settings → Credits, a few dollars; Settings → API Keys → Create Key with a credit limit; add the
line to `.env`, never to a command line). `JEV_MODEL` overrides the model id
(`~typesafe/jev-latest`).

## Release gate

Scenarios in fake mode must pass; S01 and S02 live must complete. Extraction accuracy across the
fixed set targets ≥95% exact on supplied facts and zero fabricated confirmed fields. Misses are
reported as misses.
