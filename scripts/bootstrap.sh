#!/usr/bin/env bash
# One-time bootstrap: state bucket + CI identity with local state, then migrate it to GCS.
# Usage: PROJECT_ID=... REGION=europe-west1 scripts/bootstrap.sh
set -euo pipefail
echo "TODO: terraform -chdir=infra/bootstrap init && apply; then init -migrate-state to the bucket" >&2
exit 1
