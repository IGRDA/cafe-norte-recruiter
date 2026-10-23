# Infrastructure operations

Hosted-operation helpers live in `scripts/ops/`: `bootstrap.sh`, `set_secrets.py`,
`smoke.py` and `teardown.sh`. Run the commands below from the repository root;
`make smoke` also runs the smoke check locally or against `SMOKE_URL`.

Terraform owns two stacks: `bootstrap/` creates the state bucket, GitHub workload identity,
deployer and billing budget; `app/` creates the image registry, runtime identity, secrets,
Compute Engine VM and Cloud SQL. Requires Terraform ≥1.11, gcloud Application Default
Credentials and an explicit `demo_end_date`. Copy the examples in `environments/` to their
ignored `.tfvars` and `.backend.hcl` counterparts. `make infra-check` validates without a backend.

## Bootstrap and deploy

1. Run `scripts/ops/bootstrap.sh` with `PROJECT_ID`, `BUCKET`, `REPO` (`owner/name`),
   `BILLING_ACCOUNT` and optionally `REGION`. It migrates the initial local state into GCS.
2. Run `make infra-init`. On first setup, create `google_artifact_registry_repository.app`
   with a targeted apply, build/push the Docker image, then create
   `google_secret_manager_secret.keys` with a targeted apply. Supply the image digest in
   `demo.tfvars`; upload provider/access/cookie secrets with `scripts/ops/set_secrets.py` before
   the full `make infra-plan` and `make infra-apply`.
3. Configure GitHub variables `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_ARTIFACT_REPOSITORY`,
   `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOYER_SERVICE_ACCOUNT`, `TF_STATE_BUCKET`,
   `DEMO_END_DATE`, `PUBLIC_HOSTNAME`, and the secret `SMOKE_ACCESS_CODE`. Identity values
   come from bootstrap outputs. CI uses workload identity, without a service-account key.
4. Pushes to `main` deploy through [deploy.yml](../.github/workflows/deploy.yml): check, build,
   push by digest, apply, reset the VM, wait for the expected `/api/runtime` commit and
   `/health/ready`, then smoke-check. Markdown-only changes do not deploy.

`startup.sh` reads metadata and secrets on boot. Image changes need a VM reset; startup-script
changes replace the instance. The static address survives. A reset interrupts active calls;
Postgres keeps sessions and bookings, and candidates can reconnect with their private resume
links. The previous image may answer while the new image downloads, hence the commit check.
To roll back, set `image_digest` to the previous digest, apply, then reset the VM; migrations
are forward-only, so deployed schemas must remain compatible with that image.

The `service_url` output uses `public_hostname` when set. Point its DNS A record at the static
address; the `<ip-with-dashes>.sslip.io` hostname remains available. Share the access code in
`/?store=chamberi_barista_v1&lang=es#code=...`; the fragment is exchanged and removed by the page.

## Secrets and data

Use `uv run python scripts/ops/set_secrets.py --project <project> --only <NAME> ...`, then reset
the instance. `--only` avoids overwriting hosted secrets with unrelated values from a local
`.env`. Rotate the database password by increasing Terraform's `db_password_version`; the
password uses ephemeral/write-only values and is absent from state.

Cloud SQL uses an IAM-authenticated Auth Proxy at `127.0.0.1:5432`; the app user also applies
migrations at startup. Sessions are purged after `CAFE_NORTE_RETENTION_DAYS` (default seven)
and on owner deletion. Cloud SQL keeps three daily backups; deleted data can remain there.
The demo disables database deletion protection. Provider and trace retention are separate.

Langfuse is enabled when both keys are set. Hosted `CAFE_NORTE_TRACE_CONTENT=on` sends redacted
words and tool arguments for fictional-data debugging. Set it to `off` in `app/main.tf` before
using real applicant data; metadata, timings and costs remain. Redaction does not remove every
name or address. Prices and conversion rate are versioned in `observability/prices/v1.yaml`;
update the source, verification date and version together when refreshing prices.

## Diagnose and retire

- Check `/api/runtime` for the served commit, `/health/ready` for readiness, and
  `gcloud compute instances get-serial-port-output <instance> --zone <zone>` for startup failures.
- Use `gcloud compute ssh <instance> --zone <zone> -- docker logs app` (or
  `docker logs cloud-sql-proxy`). App logs carry `session_id`, `turn_id` and stable event codes.
  In Langfuse, open that session to inspect model/tool spans, timings and usage; the JSON export
  and ordered `events` journal show what the candidate received.
- Voice capacity is controlled by `CAFE_NORTE_MAX_VOICE_SESSIONS`. Startup releases that
  instance's abandoned admission rows; room expiry and admission TTL recover crashed calls.
- Capacity is set in `app/variables.tf`: one `e2-standard-4` with six calls, 30 session starts
  per IP an hour and ten database connections, sized for about ten testers with five to ten at
  once. This is reasoned, not load-tested. The call cap counts every instance on the database,
  so a second VM adds no calls unless the cap is raised. The ElevenLabs plan must allow as many
  requests at once as there are calls. To scale back, set `e2-small`, 2, 9 and 5.
- When an access code is set, [RequestLimits](../src/cafe_norte/api/limits.py) configures code
  attempts and session starts per IP, plus the daily session ceiling. It documents the
  environment overrides. Restarts clear per-IP counters; deleting sessions reduces the daily
  count, and concurrent starts can exceed that ceiling because checking and creation are separate.
- Before `demo_end_date`, run `PROJECT_ID=... BUCKET=... scripts/ops/teardown.sh`. It prompts through
  Terraform, destroys the app/database and removes images. It does not drain active calls or
  retain database backups. Bootstrap/state are kept unless explicitly retired separately.
