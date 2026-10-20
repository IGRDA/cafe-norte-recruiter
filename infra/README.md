# Infrastructure

Google Cloud, declared with Terraform in two stacks so the first run never depends on an image
or secret version that does not exist yet.

| Stack | Creates | State |
| --- | --- | --- |
| `bootstrap/` | Terraform state bucket (versioned, public access prevention), Workload Identity Federation pool and provider for GitHub Actions, deployer service account | local on first run, then migrated to `gs://<bucket>/bootstrap` |
| `app/` | Enabled APIs, runtime and migration service accounts with scoped IAM, Artifact Registry repository, Secret Manager secrets (names only), Cloud SQL PostgreSQL 16 (`db-g1-small`, single zone, three backups), Cloud Run service (gen2, 1 vCPU, 2 GiB, CPU always allocated, min 1 / max 1, concurrency 20, 600 s timeout, startup and liveness probes), uptime check and error alert, billing budget with 50/80/100% alerts | `gs://<bucket>/app` |
| `environments/` | `demo.tfvars.example` (project, region, sizing, budget, image digest) and `demo.backend.hcl.example` | copied to ignored files |

Sequence: `scripts/bootstrap.sh` → `scripts/set_secrets.py` → image build and push (CI) →
`make infra-apply` with the image digest → `make migrate` through the migration identity →
smoke check. Thereafter `deploy.yml` does build, plan, apply, migrate, smoke on every push to
`main`. Secrets never pass through Terraform inputs; only secret names and version references
do. Terraform state can still contain database credentials, so the bucket is private and the
plan is never published as a CI artifact.

Cloud Run reaches Cloud SQL through the built-in Unix socket (`/cloudsql/<connection name>`),
which needs no VPC connector and which psycopg speaks natively. The database has no public
authorized networks.

Terraform is pinned to 1.5.7 (the version Homebrew ships and CI installs) and the Google
provider to `~> 6.0`; both `.terraform.lock.hcl` files are committed. `make infra-check`
formats and validates both stacks without a backend.

Set an explicit demo end date before provisioning; `scripts/teardown.sh` drains and destroys.
