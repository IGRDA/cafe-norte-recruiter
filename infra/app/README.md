# app stack

Everything the running demo needs. The image is an input (`image_digest`), so a deployment is a
Terraform change plus an instance reset, and cannot drift from infrastructure state. Secrets
exist by name; their versions come from `scripts/set_secrets.py`. Runtime configuration that is
not a secret is plain env in instance metadata: model, voice mode, voice id, voice session cap.

The app runs on one Compute Engine VM because Cloud Run containers have no routable address
for WebRTC (D24). `startup.sh` is the deploy: metadata → env file (secrets from Secret
Manager) → open 80/443 in the COS host firewall (inbound is dropped by default) → `docker run`
of the app and of Caddy, both with host networking, on every boot.
A change to `startup.sh` replaces the instance (the address survives); a change to the image
only updates metadata, and the reset in `deploy.yml` applies it.

Variables: `project_id`, `region`, `service_name`, `image_digest`, `machine_type`, `model`,
`elevenlabs_voice_id`, `demo_end_date`, `enable_database` (false until the Postgres stage),
`db_tier` (unused until then).
Outputs: `service_url`, `instance`, `artifact_repository`, `runtime_service_account`.
