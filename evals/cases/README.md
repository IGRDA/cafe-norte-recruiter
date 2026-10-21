# Cases

| Directory | File per | Loaded by |
| --- | --- | --- |
| `scenarios/` | one YAML per scenario `S01`–`S18`, matching `evals.contracts.Scenario` | scenarios suite and `tests/` (fake mode) |
| `retrieval/` | `questions.yaml`: 24 `RetrievalCase` entries | retrieval suite |
| `comparison/` | `cases.yaml`: 6 `ComparisonCase` entries referencing scenarios | comparison suite |

`S01.yaml` is the template (`fake_script` format in `evals/README.md`). Ids follow the spec's table: `S02` (English happy path, Arganzuela), `S03` (not interested), `S04` (correction after the brief), `S05` (policy question mid-collection), `S06` (other-store and unknown questions) and `S07` (Spanish to English switch) exist; the rest follow with their stages.
