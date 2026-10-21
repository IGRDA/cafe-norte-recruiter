# app stack

Everything the running demo needs. The Cloud Run image is an input (`image_digest`), so a
deployment is a Terraform change and cannot drift from infrastructure state. Secrets exist by
name; their versions come from `scripts/set_secrets.py`. Runtime configuration that is not a
secret is plain env on the service: model, voice mode, voice id, voice session cap.

Variables: `project_id`, `region`, `service_name`, `image_digest`, `min_instances`,
`max_instances`, `cpu`, `memory`, `model`, `elevenlabs_voice_id`, `demo_end_date`,
`enable_database` (false until the Postgres stage), `db_tier` (unused until then).
Outputs: `service_url`, `artifact_repository`, `runtime_service_account`.
