# Cases

| Directory | File per | Loaded by |
| --- | --- | --- |
| `scenarios/` | one YAML per scenario `S01`–`S18`, matching `evals.contracts.Scenario` | scenarios suite and `tests/` (fake mode) |
| `retrieval/` | `questions.yaml`: 24 `RetrievalCase` entries | retrieval suite |
| `comparison/` | `cases.yaml`: 6 `ComparisonCase` entries referencing scenarios | comparison suite |

`S01.yaml` is the template (`fake_script` format in `evals/README.md`); `S02` (correction after the brief) and `S03` (not interested) exist; the rest follow with their stages.
