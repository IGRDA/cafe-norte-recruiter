# Runbook

## Hosted demo (Cloud Run, project `cafe-norte-orbio`)

- **URL**: the `service_url` output of `infra/app` (`https://cafe-norte-<hash>-ew.a.run.app`).
- **Deploy**: push to `main`; `deploy.yml` builds, pushes, applies with the digest and runs
  `scripts/smoke.py`. By hand: `make infra-init`, `make infra-plan`, `make infra-apply` with
  `-var image_digest=…`.
- **Rotate a secret** (keys, access code, cookie secret): export the new value, run
  `uv run python scripts/set_secrets.py --project cafe-norte-orbio`, then redeploy (an
  instance reads `latest` when it starts; a new revision picks it up).
- **Read logs**: `gcloud logging read 'resource.type="cloud_run_revision" AND
  resource.labels.service_name="cafe-norte"' --project cafe-norte-orbio --freshness=1h`.
  Failed turns log `turn failed … code=… detail=…`.
- **Restart or new revision**: sessions live in memory until the Postgres stage; an active
  conversation is lost and the page says so on its next request. Resume links arrive with
  Postgres.
- **Overload**: at most two voice sessions per instance (`CAFE_NORTE_MAX_VOICE_SESSIONS`);
  a third gets `busy`. Lower it to one by changing the service env and redeploying.
- **Costs**: one always-on instance is the standing cost; budget alerts at 15/24/30 EUR;
  providers are pay-per-use behind the access code and the voice cap.
- **Teardown**: `PROJECT_ID=cafe-norte-orbio BUCKET=cafe-norte-orbio-tfstate
  scripts/teardown.sh` before `demo_end_date`; the bootstrap stack stays unless the project is
  retired.

Later stages add: failed-call triage with Langfuse traces, the retention job and manual delete,
backup retention.
