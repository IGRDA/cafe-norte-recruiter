# app stack

Everything the running demo needs. The image is an input (`image_digest`), so a deployment is a
Terraform change plus an instance reset, and cannot drift from infrastructure state. Secrets
exist by name; their versions come from `scripts/set_secrets.py`. Runtime configuration that is
not a secret is plain env in instance metadata (`plain_env` in `main.tf`): model, voice mode,
voice id, voice session cap, Langfuse host and environment, and trace content (`on`, D42; `off`
before any real applicant). Every key there must exist in `.env.example`
(`tests/test_infra_settings.py`), so a misspelling cannot silently drop a setting.

The app runs on one Compute Engine VM because Cloud Run containers have no routable address
for WebRTC (D24). `startup.sh` is the deploy: metadata → env file (secrets from Secret
Manager) → open 80/443 in the COS host firewall (inbound is dropped by default), before the
pull so a failed pull leaves the previous release reachable → prune images no container uses
(the 16 GB docker partition holds about nine 1.7 GB releases; a full one stopped a deploy on
22 October 2026) → pull → `docker run` of the app and of Caddy, both with host networking, on
every boot.
A change to `startup.sh` replaces the instance (the address survives); a change to the image
only updates metadata, and the reset in `deploy.yml` applies it. After the reset docker
restarts the previous release, which answers while the new image is pulled, so the deploy waits
until `GET /api/runtime` names the commit it built before it checks readiness and runs the smoke.

`database.tf` (D33) is Cloud SQL Postgres 16 on the smallest tier, public address with no
authorized networks, daily backups kept three days, no point-in-time recovery, no deletion
protection. The VM runs the Cloud SQL Auth Proxy as a third container with host networking;
it authenticates as the runtime service account (`roles/cloudsql.client`) and the app gets an
ordinary `CAFE_NORTE_DATABASE_URL` on `127.0.0.1:5432`. The one built-in user's password is an
ephemeral `random_password` written only through write-only arguments, to the user and to the
`CAFE_NORTE_DB_PASSWORD` secret version: it is never in the plan or the state. Bump
`db_password_version` to rotate it. Needs Terraform 1.11 or later.

Variables: `project_id`, `region`, `service_name`, `image_digest`, `machine_type`, `model`,
`elevenlabs_voice_id`, `demo_end_date`, `enable_database` (default true), `db_tier`,
`db_name`, `db_user`, `db_password_version`.
Outputs: `service_url`, `instance`, `artifact_repository`, `runtime_service_account`,
`database_connection_name`.
