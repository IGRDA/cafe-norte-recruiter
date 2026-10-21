# Evaluations

Three suites, one typed runner, two execution modes. Deterministic runs use the fake model and
are part of CI; live runs call paid providers and are manual.

| Suite | Cases | Scorers | Mode |
| --- | --- | --- | --- |
| `scenarios` | S01–S18 (`cases/scenarios/*.yaml`): scripted turns for CI, persona for the simulator | deterministic checks on the final `ExportDocument` (fields, confirmations, booking, flags, no fabricated confirmed value) + optional rubric judge | CI (fake) and live |
| `retrieval` | 24 questions (`cases/retrieval/questions.yaml`): 16 answerable, 4 unsupported, 4 leakage | recall@3 of expected sections, zero cross-store sources; unsupported questions reported with what came back after the floor (D27); ragas as a second opinion later | `make evals-retrieval` (`--retriever hybrid` needs the extra; `lexical` runs in CI) |
| `comparison` | 6 multi-turn cases × 2 models × 2 repetitions (`cases/comparison/cases.yaml`), 24 runs on one loopback server per model, same prompt, tools, KB and configuration | each case's scenario `live_checks`, extraction accuracy, tool calls ok, grounding checks, runs passed, latency, cost; summary and runs (no exports) committed under `results/comparison/` | live, bounded, `--yes` |

```bash
make evals ARGS="--suite scenarios --mode fake"          # what CI runs
make evals ARGS="--suite scenarios --mode live --only S01 S02"          # prints the estimate only
make evals ARGS="--suite scenarios --mode live --only S01 S02 --yes"    # spends
make evals ARGS="--suite scenarios --mode live --only S01 --model fake --simulator fake --yes"  # free dry run
make evals-retrieval ARGS="--retriever hybrid"   # lexical: BM25 only, no extra
make compare                                   # 6 cases x 2 models x 2 runs: prints the estimate only
make compare ARGS="--yes"                      # spends; default models openai/gpt-4o-mini openai/gpt-4o
make compare ARGS="--models fake --repeat 1 --simulator fake --max-turns 2 --yes"  # free dry run
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
  `sources_shown_on_any_turn`; an unknown name raises).
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
- `simulator.py`: the simulated candidate. `cue(persona, language, transcript)` decides deterministically what the next line does (raise `asks[k]` on line k+2, correct on the first brief read-back only, switch language after line N, withdraw after line N, the persona's mood); an LLM through the `Model` port only words it, so every behaviour happens and on a line the report can name.
- `judge.py`: rubric judge through the same `Model` port (`--judge provider/model`, prompt `prompts/judge.md`): one JSON boolean per scenario `rubric` bullet over the exported transcript, or `unparsable` with the reason (a string "true" is not a boolean). Secondary signal, never pass/fail: the report shows it in its own section and flags a judge that is also the answering model.
- `ragas_bridge.py`: converts retrieval runs into ragas samples.
- `langfuse_sync.py`: pushes cases as a Langfuse dataset and runs as experiments, so traces, scores and prompt versions line up in one place.
- `report.py`: `summarize` (pure) gives one row per answering model: runs passed, extraction (exact facts), no fabricated field, tool calls ok, grounding checks, median first sentence and turn time, cost of the priced runs; then by configuration and language, by case, and every miss with its reason. Every rate is k/n and every median says its n ("2.0 s (n=96 turns)"). `render_markdown` states the spec's targets next to the numbers; `render_json` is the same without exports.

Raw live reports contain conversations and stay out of git (`results/` is ignored); the
comparison's aggregated structured results and the retrieval scores are committed under
`results/` by name exception in `.gitignore` once they exist.

## Release gate

Scenarios in fake mode must pass; S01 and S02 live must complete. Extraction accuracy across the
fixed set targets ≥95% exact on supplied facts and zero fabricated confirmed fields. Misses are
reported as misses.
