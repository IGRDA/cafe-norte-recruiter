# Evaluations

Three suites, one typed runner, two execution modes. Deterministic runs use the fake model and
are part of CI; live runs call paid providers and are manual.

| Suite | Cases | Scorers | Mode |
| --- | --- | --- | --- |
| `scenarios` | S01–S18 (`cases/scenarios/*.yaml`): scripted turns for CI, persona for the simulator | deterministic checks on the final `ExportDocument` (fields, confirmations, booking, flags, no fabricated confirmed value) + optional rubric judge | CI (fake) and live |
| `retrieval` | 24 questions (`cases/retrieval/questions.yaml`): 16 answerable, 4 unsupported, 4 leakage | recall@3 of expected sections, zero cross-store sources; unsupported questions reported with what came back after the floor (D27); ragas as a second opinion later | `make evals-retrieval` (`--retriever hybrid` needs the extra; `lexical` runs in CI) |
| `comparison` | 6 multi-turn cases × 2 models × 2 repetitions (`cases/comparison/cases.yaml`) | extraction accuracy, valid tool use, grounding, completion, latency, cost; results committed under `results/comparison/` | live, bounded |

```bash
make evals ARGS="--suite scenarios --mode fake"          # what CI runs
make evals ARGS="--suite scenarios --mode live --only S01 S02"
make evals-retrieval ARGS="--retriever hybrid"   # lexical: BM25 only, no extra
make compare ARGS="--models groq/openai/gpt-oss-120b groq/openai/gpt-oss-20b --repeat 2"
uv run python -m evals.run --list
```

## What runs today

Scenarios in fake mode. `S01`–`S03`, `S05`, `S06` and `S09` replay against the real runtime, handlers,
domain, memory store and the real `HybridRetriever` over `kb/` with `FakeEmbedder`, driven by
the scripted `FakeModel`; `tests/test_scenarios.py` parametrizes over the
files, so `make check` and CI fail on a broken scenario with the check named. `make evals
ARGS="--suite scenarios --mode fake"` is the same replay printed as a table. Live mode, the
retrieval and comparison suites, the judge and the simulator arrive with their stages (the
CLI says so and exits 2). Every fake run carries its `ExportDocument` in `RunRecord.export`;
`make export-example` writes S01's to `examples/`.

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
  `lifecycle_is`, `outcome_is`, `no_fabricated_confirmed_values`, `max_repeated_questions`,
  `review_flag_present`, `signal_recorded`, `said_control_reply`; the rest raise until their
  stage).
- `today`: the fake clock's date, so relative dates in the script stay fixed.

Checks run over `SessionResult` (final state, transcript, what Ana said per turn); the export
is built as well, and the checks move to it when the booking and retrieval checks land (D21).

## How it fits together

- `contracts.py`: `Scenario`, `RetrievalCase`, `RetrievalRun`/`RetrievalReport`, `ComparisonCase`, `Check`, `RunRecord`, `Report`, and the `Scorer` and `CandidateSimulator` ports.
- `retrieval.py`: the retrieval suite: fixture questions through a retriever, recall@3, leakage, timings; one committed JSON per embedding model and KB version.
- `runner.py`: loads cases, drives a session through the HTTP API (live) or the runtime with fakes (CI), collects the export and timings, applies scorers, writes a report with a `VersionStamp`.
- `scorers.py`: pure functions over `ExportDocument` and retrieval results.
- `simulator.py`: an LLM playing the candidate from a persona fixture; adapts to Ana's question order, applies the scripted corrections, frustration and language switches.
- `judge.py`: rubric judge through the same `Model` port; secondary signal, never pass/fail.
- `ragas_bridge.py`: converts retrieval runs into ragas samples.
- `langfuse_sync.py`: pushes cases as a Langfuse dataset and runs as experiments, so traces, scores and prompt versions line up in one place.
- `report.py`: Markdown and JSON with denominators; a median from ten turns says "n=10".

Raw live reports contain conversations and stay out of git (`results/` is ignored); the
comparison's aggregated structured results and the retrieval scores are committed under
`results/` by name exception in `.gitignore` once they exist.

## Release gate

Scenarios in fake mode must pass; S01 and S02 live must complete. Extraction accuracy across the
fixed set targets ≥95% exact on supplied facts and zero fabricated confirmed fields. Misses are
reported as misses.
