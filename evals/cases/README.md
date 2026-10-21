# Cases

| Directory | File per | Loaded by |
| --- | --- | --- |
| `scenarios/` | one YAML per scenario `S01`–`S18`, matching `evals.contracts.Scenario` | scenarios suite and `tests/` (fake mode) |
| `retrieval/` | `questions.yaml`: 24 `RetrievalCase` entries | retrieval suite |
| `comparison/` | `cases.yaml`: 6 `ComparisonCase` entries referencing scenarios | comparison suite |

`S01.yaml` is the template (`fake_script` format in `evals/README.md`). Ids follow the spec's table: `S02` (English happy path, Arganzuela), `S03` (not interested), `S04` (correction after the brief), `S05` (policy question mid-collection), `S06` (other-store and unknown questions), `S07` (Spanish to English switch) and `S09` (frustration and an explicit human request) exist; the rest follow with their stages. `S12` (restart, overlapping worker, private resume) and `S13` (wrong or expired token, guessed session id) are not scripted conversations: they live in `tests/test_api_postgres.py` and `tests/test_api_resume.py`.
