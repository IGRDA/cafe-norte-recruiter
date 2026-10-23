#!/usr/bin/env bash
# One-time bootstrap: state bucket + CI identity, applied with local state because the bucket
# does not exist yet, then the state is migrated into that bucket.
# Usage: PROJECT_ID=cafe-norte-orbio BUCKET=cafe-norte-orbio-tfstate REPO=IGRDA/cafe-norte-recruiter scripts/ops/bootstrap.sh
set -euo pipefail
: "${PROJECT_ID:?set PROJECT_ID}"
: "${BUCKET:?set BUCKET (globally unique state bucket name)}"
: "${REPO:?set REPO as owner/name}"
: "${BILLING_ACCOUNT:?set BILLING_ACCOUNT}"
REGION="${REGION:-europe-west1}"
DIR=infra/bootstrap
VARS=(-var "project_id=$PROJECT_ID" -var "region=$REGION" -var "state_bucket_name=$BUCKET" -var "github_repository=$REPO" -var "billing_account=$BILLING_ACCOUNT")

# Phase 1: local state, backend block set aside (Terraform refuses a gcs block without init).
mv "$DIR/backend.tf" "$DIR/backend.tf.off"
trap 'mv -f "$DIR/backend.tf.off" "$DIR/backend.tf" 2>/dev/null || true' EXIT
rm -rf "$DIR/.terraform"
terraform -chdir="$DIR" init -input=false >/dev/null
terraform -chdir="$DIR" apply -input=false -auto-approve "${VARS[@]}"

# Phase 2: move the local state into the bucket it just created.
mv "$DIR/backend.tf.off" "$DIR/backend.tf"
trap - EXIT
terraform -chdir="$DIR" init -input=false -force-copy -migrate-state \
  -backend-config="bucket=$BUCKET" -backend-config="prefix=bootstrap" >/dev/null
rm -f "$DIR/terraform.tfstate" "$DIR/terraform.tfstate.backup"
terraform -chdir="$DIR" output
