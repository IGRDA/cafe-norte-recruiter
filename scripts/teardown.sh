#!/usr/bin/env bash
# Drain active sessions, then destroy infra/app. State bucket and Cloud SQL backups are kept.
set -euo pipefail
echo "TODO: stop admission, wait for sessions, terraform -chdir=infra/app destroy" >&2
exit 1
