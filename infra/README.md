# Infrastructure

Google Cloud, declared with Terraform in two stacks so the first run never depends on an image
or secret version that does not exist yet (D23).

| Stack | Creates | Applied by | State |
| --- | --- | --- | --- |
| `bootstrap/` | Versioned state bucket (public access prevention), Workload Identity Federation pool and provider for GitHub Actions restricted to this repository's `main`, deployer service account with deploy roles, the billing budget (50/80/100 %) | a person, once, with ADC: `scripts/bootstrap.sh` | local on first run, then migrated to `gs://<bucket>/bootstrap` |
| `app/` | Artifact Registry repository, runtime service account (secret accessor, log writer), Secret Manager secrets (names only), Cloud Run v2 service (gen2, 1 vCPU, 2 GiB, CPU always allocated, min 1 / max 1, concurrency 20, 600 s timeout, session affinity, startup and liveness probes, secrets as env from `latest`), public invoker (the app enforces the access code) | CI on every push to `main` (`deploy.yml`) with the image digest it built; the first time by a person | `gs://<bucket>/app` |
| `environments/` | `demo.tfvars.example` (project, region, sizing, image digest, end date) and `demo.backend.hcl.example` | copied to ignored files | |

Not provisioned yet: Cloud SQL (`enable_database = false`, Postgres stage), uptime check and
5xx alert (observability stage).

Sequence, first time: `scripts/bootstrap.sh` → `make infra-init` → targeted apply of the
repository → build and push the image by digest → targeted apply of the secret names →
`scripts/set_secrets.py` → `make infra-apply` with the digest → `scripts/smoke.py <url>`.
Thereafter `deploy.yml` does build, apply, smoke on every push to `main`. Secrets never pass
through Terraform inputs; only secret names do. Terraform state is private in the bucket and
the plan is never published as a CI artifact.

GitHub Actions needs these repository variables: `GCP_PROJECT_ID`, `GCP_REGION`,
`GCP_ARTIFACT_REPOSITORY` (`app`), `GCP_WORKLOAD_IDENTITY_PROVIDER` and
`GCP_DEPLOYER_SERVICE_ACCOUNT` (bootstrap outputs), `TF_STATE_BUCKET`; and the repository
secret `SMOKE_ACCESS_CODE`. The `demo` environment exists without required reviewers.

Terraform is pinned to 1.5.7 and the Google provider to `~> 6.0`; both lock files are
committed. `make infra-check` formats and validates both stacks without a backend. Both
providers set `user_project_override` with the project as quota project so user-credential
calls (the budget API) work.

Set an explicit demo end date before provisioning; `scripts/teardown.sh` destroys the app
stack and the image repository. The bootstrap stack is kept unless the project is retired.
