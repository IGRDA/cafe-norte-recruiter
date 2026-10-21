# Runbook

## Hosted demo (one Compute Engine VM, project `cafe-norte-orbio`, D24)

- **URL**: the `service_url` output of `infra/app` (`https://<ip-with-dashes>.sslip.io`).
- **Deploy**: push to `main`; `deploy.yml` builds, pushes, applies with the digest, resets the
  instance, waits for `/health/ready` and runs `scripts/smoke.py`. By hand: `make infra-init`,
  `make infra-plan`, `make infra-apply` with `-var image_digest=…`, then
  `gcloud compute instances reset cafe-norte --zone europe-west1-b`. About a minute of
  downtime per deploy.
- **Rotate a secret** (keys, access code, cookie secret): export the new value, run
  `uv run python scripts/set_secrets.py --project cafe-norte-orbio`, then reset the
  instance (the startup script reads `latest` on every boot).
- **Read logs**: `gcloud logging read 'resource.type="gce_instance" AND
  jsonPayload.container.name="/app"' --project cafe-norte-orbio --freshness=1h`, or on the
  box `gcloud compute ssh cafe-norte --zone europe-west1-b -- docker logs app`. The startup
  script's own lines are in the serial console (`get-serial-port-output`).
  Failed turns log `turn failed … code=… detail=…`.
- **Restart or new image**: on Postgres (`CAFE_NORTE_DATABASE_URL` set) sessions, bookings and
  the event sequence survive; an open page reconnects and a candidate reopens the conversation
  with the private link shown when it started (valid 7 days). The hosted VM still runs the
  memory store until Cloud SQL lands (D24): there an active conversation is lost and the page
  says so on its next request.
- **Overload**: at most two voice sessions per instance (`CAFE_NORTE_MAX_VOICE_SESSIONS`);
  a third gets `busy`. Lower it to one in `infra/app/main.tf` (`plain_env`) and redeploy.
- **Costs**: one `e2-small` plus a static address is the standing cost (≈ 15 EUR/month); budget alerts at 15/24/30 EUR;
  providers are pay-per-use behind the access code and the voice cap.
- **Teardown**: `PROJECT_ID=cafe-norte-orbio BUCKET=cafe-norte-orbio-tfstate
  scripts/teardown.sh` before `demo_end_date`; the bootstrap stack stays unless the project is
  retired.

Later stages add: failed-call triage with Langfuse traces, the retention job and manual delete,
backup retention.
