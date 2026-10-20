# Evaluations

Three suites, one typed runner, two execution modes. Deterministic runs use the fake model and
are part of CI; live runs call paid providers and are manual.

| Suite | Cases | Scorers | Mode |
| --- | --- | --- | --- |
| `scenarios` | S01–S18 (`cases/scenarios/*.yaml`): scripted turns for CI, persona for the simulator | deterministic checks on the final `ExportDocument` (fields, confirmations, booking, flags, no fabricated confirmed value) + optional rubric judge | CI (fake) and live |
| `retrieval` | 24 questions (`cases/retrieval/questions.yaml`): 16 answerable, 4 unsupported, 4 leakage | recall@3 of expected sections, abstention, zero cross-store sources; ragas context precision/recall and faithfulness as a second opinion | local, cheap (judge optional) |
| `comparison` | 6 multi-turn cases × 2 models × 2 repetitions (`cases/comparison/cases.yaml`) | extraction accuracy, valid tool use, grounding, completion, latency, cost; results committed under `results/comparison/` | live, bounded |

```bash
make evals ARGS="--suite scenarios --mode fake"          # what CI runs
make evals ARGS="--suite scenarios --mode live --only S01 S02"
make evals-retrieval ARGS="--judge off"
make compare ARGS="--models groq/openai/gpt-oss-120b groq/openai/gpt-oss-20b --repeat 2"
uv run python -m evals.run --list
```

## How it fits together

- `contracts.py`: `Scenario`, `RetrievalCase`, `ComparisonCase`, `Check`, `RunRecord`, `Report`, and the `Scorer` and `CandidateSimulator` ports.
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
