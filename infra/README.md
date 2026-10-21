# Infrastructure

Google Cloud, declared with Terraform in two stacks so the first run never depends on an image
or secret version that does not exist yet (D23).

| Stack | Creates | Applied by | State |
| --- | --- | --- | --- |
| `bootstrap/` | Versioned state bucket (public access prevention), Workload Identity Federation pool and provider for GitHub Actions restricted to this repository's `main`, deployer service account with deploy roles, the billing budget (50/80/100 %) | a person, once, with ADC: `scripts/bootstrap.sh` | local on first run, then migrated to `gs://<bucket>/bootstrap` |
| `app/` | Artifact Registry repository, runtime service account (secret accessor, image reader, log writer), Secret Manager secrets (names only), a static address, an ingress rule for 80/443, and one `e2-small` Container-Optimized OS instance whose startup script runs the app image by digest and Caddy (automatic HTTPS on `<ip-with-dashes>.sslip.io`) with host networking (D24). The page is public; the app enforces the access code | CI on every push to `main` (`deploy.yml`) with the image digest it built, then an instance reset; the first time by a person | `gs://<bucket>/app` |
| `environments/` | `demo.tfvars.example` (project, region, sizing, image digest, end date) and `demo.backend.hcl.example` | copied to ignored files | |

Cloud SQL is provisioned in `app/` (D33). Not provisioned yet: the uptime check and 5xx alert.

Sequence, first time: `scripts/bootstrap.sh` → `make infra-init` → targeted apply of the
repository → build and push the image by digest → targeted apply of the secret names →
`scripts/set_secrets.py` → `make infra-apply` with the digest → `scripts/smoke.py <url>`.
Thereafter `deploy.yml` does build, apply, reset the instance, wait for `/health/ready`, smoke on every push to `main`. Secrets never pass
through Terraform inputs; only secret names do. Terraform state is private in the bucket and
the plan is never published as a CI artifact.

GitHub Actions needs these repository variables: `GCP_PROJECT_ID`, `GCP_REGION`,
`GCP_ARTIFACT_REPOSITORY` (`app`), `GCP_WORKLOAD_IDENTITY_PROVIDER` and
`GCP_DEPLOYER_SERVICE_ACCOUNT` (bootstrap outputs), `TF_STATE_BUCKET`, `DEMO_END_DATE`; and the
repository secret `SMOKE_ACCESS_CODE`. `demo.tfvars` is local and git-ignored; CI passes the
same non-secret values as `TF_VAR_*`. The `demo` environment exists without required reviewers.

Terraform is 1.11 or later (write-only arguments, D33; CI runs `~> 1.12`) and the Google
provider `~> 6.0`; both lock files are committed. `make infra-check` formats and validates both
stacks without a backend. Both providers set `user_project_override` with the project as quota project so user-credential
calls (the budget API) work.

Set an explicit demo end date before provisioning; `scripts/teardown.sh` destroys the app
stack and the image repository. The bootstrap stack is kept unless the project is retired.
