# Scripts

Operational entry points. None is imported by `src/`.

| Script | Purpose | Needs |
| --- | --- | --- |
| `export_schema.py` | Regenerate `examples/session_export.schema.json` from `ExportDocument` | nothing |
| `build_index.py` | Chunk and embed `kb/` into `kb/index/<kb_version>/` | `--extra knowledge` |
| `voice_listen.py` | The spec's listening check: two scripts × a few ElevenLabs voices to `/tmp/voices` (paid, manual) |
| `smoke.py <url>` | After deploy: page loads, access gate on, health ready; with `SMOKE_ACCESS_CODE`, one text turn against the fake-free runtime | network |
| `bootstrap.sh` | One-time: state bucket, Workload Identity Federation, migrate bootstrap state to GCS | gcloud ADC, terraform |
| `set_secrets.py` | Upload provider keys to Secret Manager versions outside Terraform state | gcloud ADC |
| `teardown.sh` | Drain sessions, then destroy the app stack; keeps state and backups until selected | gcloud ADC, terraform |
| `init_test_db.sql` | Compose init: creates the test database | compose |
