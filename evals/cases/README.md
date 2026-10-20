# Cases

| Directory | File per | Loaded by |
| --- | --- | --- |
| `scenarios/` | one YAML per scenario `S01`–`S18`, matching `evals.contracts.Scenario` | scenarios suite and `tests/` (fake mode) |
| `retrieval/` | `questions.yaml`: 24 `RetrievalCase` entries | retrieval suite |
| `comparison/` | `cases.yaml`: 6 `ComparisonCase` entries referencing scenarios | comparison suite |

`S01.yaml` is the template; the other seventeen follow when the runtime lands.
