#!/bin/bash
# Container-Optimized OS startup: secrets from Secret Manager, the app image by digest, and
# Caddy for automatic HTTPS. Re-run on every boot; a deploy changes the image metadata and
# resets the instance.
set -euo pipefail
META="http://metadata.google.internal/computeMetadata/v1"
H="Metadata-Flavor: Google"
PROJECT="$(curl -sf -H "$H" "$META/project/project-id")"
IMAGE="$(curl -sf -H "$H" "$META/instance/attributes/image")"
PUBLIC_HOST="$(curl -sf -H "$H" "$META/instance/attributes/public_host")"
DB_CONNECTION="$(curl -sf -H "$H" "$META/instance/attributes/db_connection_name" || true)"
TOKEN="$(curl -sf -H "$H" "$META/instance/service-accounts/default/token" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)"

ENV_DIR=/var/lib/cafe-norte
mkdir -p "$ENV_DIR" && chmod 700 "$ENV_DIR"
ENV_FILE="$ENV_DIR/env"
: > "$ENV_FILE" && chmod 600 "$ENV_FILE"
# Plain settings from metadata; secret values from Secret Manager (latest version).
curl -sf -H "$H" "$META/instance/attributes/env" >> "$ENV_FILE"
echo >> "$ENV_FILE"
secret() {
  curl -sf -H "Authorization: Bearer $TOKEN" \
    "https://secretmanager.googleapis.com/v1/projects/$PROJECT/secrets/$1/versions/latest:access" \
    | grep -o '"data": *"[^"]*"' | cut -d'"' -f4 | base64 -d
}
for NAME in $(curl -sf -H "$H" "$META/instance/attributes/secret_names"); do
  printf '%s=%s\n' "$NAME" "$(secret "$NAME")" >> "$ENV_FILE"
done
# Cloud SQL (D33): the Auth Proxy listens on localhost with this VM's service account identity;
# the app sees an ordinary Postgres URL. The password is the Terraform-generated secret.
if [ -n "$DB_CONNECTION" ]; then
  DB_USER="$(curl -sf -H "$H" "$META/instance/attributes/db_user")"
  DB_NAME="$(curl -sf -H "$H" "$META/instance/attributes/db_name")"
  printf 'CAFE_NORTE_DATABASE_URL=postgresql://%s:%s@127.0.0.1:5432/%s\n' \
    "$DB_USER" "$(secret CAFE_NORTE_DB_PASSWORD)" "$DB_NAME" >> "$ENV_FILE"
fi

# /root is read-only on COS; docker keeps its credential store under HOME.
export HOME="$ENV_DIR"
printf '%s' "$TOKEN" | docker login -u oauth2accesstoken --password-stdin https://europe-west1-docker.pkg.dev
# COS drops inbound traffic except ssh; host networking does not add port rules. Opened
# before the pull: if it fails, the previous release, restarted by docker, stays reachable.
for PORT in 80 443; do
  iptables -w -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null \
    || iptables -w -A INPUT -p tcp --dport "$PORT" -j ACCEPT
done
# Every deploy pulls a 1.7 GB image onto a 16 GB docker partition; nine filled it on 22 October
# 2026 and the deploy stopped. The image the existing containers run is kept, so a failed pull
# still leaves the previous release running.
docker image prune -af >/dev/null || true
docker pull "$IMAGE"
docker rm -f app caddy cloud-sql-proxy >/dev/null 2>&1 || true
if [ -n "$DB_CONNECTION" ]; then
  docker run -d --name cloud-sql-proxy --restart=always --network host \
    gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.18.2 \
    --address 127.0.0.1 --port 5432 "$DB_CONNECTION"
  for _ in $(seq 1 30); do
    (exec 3<>/dev/tcp/127.0.0.1/5432) 2>/dev/null && break
    sleep 1
  done
fi
# Host networking: the app binds 8080 on the VM's routable interface, which is what WebRTC
# needs for ICE candidates (the reason this is a VM and not Cloud Run, D24).
docker run -d --name app --restart=always --network host --env-file "$ENV_FILE" \
  -e PORT=8080 "$IMAGE"
mkdir -p /var/lib/caddy
docker run -d --name caddy --restart=always --network host -v /var/lib/caddy:/data \
  caddy:2.9 caddy reverse-proxy --from "https://$PUBLIC_HOST" --to localhost:8080
