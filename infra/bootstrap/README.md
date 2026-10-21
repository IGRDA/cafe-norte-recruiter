# bootstrap stack

Run once with local Application Default Credentials (`scripts/bootstrap.sh`): the first apply
uses local state with the backend block set aside, then the state is migrated into the bucket
it just created. Creates the state bucket, the GitHub Workload Identity Federation pool and
provider restricted to this repository and the `main` branch, the deployer service account CI
impersonates, and the billing budget. No long-lived keys.

Inputs: `PROJECT_ID`, `BUCKET`, `REPO` (owner/name), `BILLING_ACCOUNT`, optional `REGION`.
Outputs: `workload_identity_provider`, `deployer_service_account`, `state_bucket`,
`project_number`.
