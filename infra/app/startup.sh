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
TOKEN="$(curl -sf -H "$H" "$META/instance/service-accounts/default/token" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)"

ENV_DIR=/var/lib/cafe-norte
mkdir -p "$ENV_DIR" && chmod 700 "$ENV_DIR"
ENV_FILE="$ENV_DIR/env"
: > "$ENV_FILE" && chmod 600 "$ENV_FILE"
# Plain settings from metadata; secret values from Secret Manager (latest version).
curl -sf -H "$H" "$META/instance/attributes/env" >> "$ENV_FILE"
echo >> "$ENV_FILE"
for NAME in $(curl -sf -H "$H" "$META/instance/attributes/secret_names"); do
  VALUE="$(curl -sf -H "Authorization: Bearer $TOKEN" \
    "https://secretmanager.googleapis.com/v1/projects/$PROJECT/secrets/$NAME/versions/latest:access" \
    | grep -o '"data": *"[^"]*"' | cut -d'"' -f4 | base64 -d)"
  printf '%s=%s\n' "$NAME" "$VALUE" >> "$ENV_FILE"
done

# /root is read-only on COS; docker keeps its credential store under HOME.
export HOME="$ENV_DIR"
printf '%s' "$TOKEN" | docker login -u oauth2accesstoken --password-stdin https://europe-west1-docker.pkg.dev
docker pull "$IMAGE"
docker rm -f app caddy >/dev/null 2>&1 || true
# Host networking: the app binds 8080 on the VM's routable interface, which is what WebRTC
# needs for ICE candidates (the reason this is a VM and not Cloud Run, D24).
docker run -d --name app --restart=always --network host --env-file "$ENV_FILE" \
  -e PORT=8080 "$IMAGE"
# COS drops inbound traffic except ssh; host networking does not add port rules.
for PORT in 80 443; do
  iptables -w -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null \
    || iptables -w -A INPUT -p tcp --dport "$PORT" -j ACCEPT
done
mkdir -p /var/lib/caddy
docker run -d --name caddy --restart=always --network host -v /var/lib/caddy:/data \
  caddy:2.9 caddy reverse-proxy --from "https://$PUBLIC_HOST" --to localhost:8080
