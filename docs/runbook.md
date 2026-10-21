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
  instance (the startup script reads `latest` on every boot). The database password is
  Terraform's: bump `db_password_version` in `infra/app` and deploy; the user and the secret
  version change together.
- **Database** (Cloud SQL `cafe-norte-db`, D33): the app reaches it through the Auth Proxy on
  the VM (`docker logs cloud-sql-proxy`). To look inside by hand:
  `gcloud sql connect cafe-norte-db --user=cafe_norte --database=cafe_norte --project cafe-norte-orbio`
  with the password from `gcloud secrets versions access latest --secret CAFE_NORTE_DB_PASSWORD`.
  Migrations run at every app start (`schema_migrations` says what is applied). Backups: daily,
  three kept, restore with `gcloud sql backups restore`.
- **Retention and deletion**: sessions older than seven days are deleted at startup and every
  hour (`retention: deleted N expired sessions` in the logs); a candidate deletes their own
  session from the page. Both remove the turns, events, export, resume link and the simulated
  reservation; the rows stay in Cloud SQL backups for up to three days.
- **Read logs**: `gcloud logging read 'resource.type="gce_instance" AND
  jsonPayload.container.name="/app"' --project cafe-norte-orbio --freshness=1h`, or on the
  box `gcloud compute ssh cafe-norte --zone europe-west1-b -- docker logs app`. The startup
  script's own lines are in the serial console (`get-serial-port-output`).
  The app logs JSON lines keyed by `session_id` and `turn_id` (`event` is `turn_failed`,
  `model_round`, `model_round_silent` or `answer_cut`); `model_round` carries `first_output_ms`
  and `total_ms`. Filter with `jsonPayload.session_id="<id>"`.
- **A call that went wrong**: the session's journal is the trace (Langfuse is not wired yet).
  Read it in order from the app container:
  `docker exec app uv run --no-sync python -c "import os,psycopg; c=psycopg.connect(os.environ['CAFE_NORTE_DATABASE_URL']); [print(r) for r in c.execute('select seq, kind, at, payload from events where session_id=%s order by seq', ('<id>',))]"`,
  next to `docker logs --since 1h app` for the voice pipeline (VAD, TTS, idle prompts). D35 is a
  worked example.
- **Restart or new image**: sessions, bookings and the event sequence are in Cloud SQL, so
  they survive; an open page reconnects and a candidate reopens the conversation with the
  private link shown when it started (valid 7 days). A turn in flight during the reset is lost
  and the page says so.
- **Overload**: at most two voice sessions per instance (`CAFE_NORTE_MAX_VOICE_SESSIONS`);
  a third gets `busy`. Lower it to one in `infra/app/main.tf` (`plain_env`) and redeploy.
- **Costs**: one `e2-small` plus a static address (≈ 15 EUR/month) and Cloud SQL `db-f1-micro` with a 10 GB HDD (≈ 8 EUR/month) are the standing cost; budget alerts at 15/24/30 EUR;
  providers are pay-per-use behind the access code and the voice cap.
- **Teardown**: `PROJECT_ID=cafe-norte-orbio BUCKET=cafe-norte-orbio-tfstate
  scripts/teardown.sh` before `demo_end_date`; the bootstrap stack stays unless the project is
  retired. `terraform destroy` removes the Cloud SQL instance too (no deletion protection); its
  backups go with it.

Later stages add: failed-call triage with Langfuse traces, the retention job and manual delete,
backup retention.
