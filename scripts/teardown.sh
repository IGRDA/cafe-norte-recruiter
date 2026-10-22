#!/usr/bin/env bash
# Destroy the app and images, retaining bootstrap/state. Active calls are interrupted.
# Usage: PROJECT_ID=cafe-norte-orbio BUCKET=cafe-norte-orbio-tfstate scripts/teardown.sh
set -euo pipefail
: "${PROJECT_ID:?set PROJECT_ID}"
: "${BUCKET:?set BUCKET}"
REGION="${REGION:-europe-west1}"

terraform -chdir=infra/app init -input=false -backend-config="bucket=$BUCKET" -backend-config="prefix=app" >/dev/null
terraform -chdir=infra/app destroy -input=false -var-file=../environments/demo.tfvars
gcloud artifacts repositories delete app --location="$REGION" --project="$PROJECT_ID" --quiet || true
echo "App stack destroyed. The bootstrap stack (state bucket, WIF, deployer) is kept; destroy it by hand if the project is being retired."
