#!/usr/bin/env bash
# One-time bootstrap: state bucket + CI identity with local state, then migrate it to GCS.
# Usage: PROJECT_ID=cafe-norte-orbio BUCKET=cafe-norte-orbio-tfstate REPO=IGRDA/cafe-norte-recruiter scripts/bootstrap.sh
set -euo pipefail
: "${PROJECT_ID:?set PROJECT_ID}"
: "${BUCKET:?set BUCKET (globally unique state bucket name)}"
: "${REPO:?set REPO as owner/name}"
REGION="${REGION:-europe-west1}"
DIR=infra/bootstrap
VARS=(-var "project_id=$PROJECT_ID" -var "region=$REGION" -var "state_bucket_name=$BUCKET" -var "github_repository=$REPO")

terraform -chdir="$DIR" init -input=false -backend=false >/dev/null
terraform -chdir="$DIR" apply -input=false "${VARS[@]}"
# Move the local state into the bucket it just created.
terraform -chdir="$DIR" init -input=false -force-copy -migrate-state \
  -backend-config="bucket=$BUCKET" -backend-config="prefix=bootstrap" >/dev/null
terraform -chdir="$DIR" output
