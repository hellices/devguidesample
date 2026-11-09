#!/usr/bin/env bash
# Runs on the gateway VM through Azure VM Run Command.
# BUNDLE_B64 arrives as a named Run Command parameter (environment variable) holding a base64 tar.gz.
set -euo pipefail
trap 'echo "GATEWAY_STEP_FAILED line $LINENO" >&2' ERR
BUNDLE_B64="${BUNDLE_B64:?BUNDLE_B64 parameter is required}"
APP_DIR=/opt/eventhubs-observability

cloud-init status --wait >/dev/null || true
command -v docker >/dev/null
command -v az >/dev/null

install -d -m 0755 "$APP_DIR"
echo "$BUNDLE_B64" | base64 -d | tar -xz -C "$APP_DIR"
cd "$APP_DIR"
set -a; . ./.env; set +a

az login --identity --client-id "$GATEWAY_CLIENT_ID" --allow-no-subscriptions --output none
install -d -m 0700 secrets
az keyvault secret show --vault-name "$KEY_VAULT_NAME" --name grafana-admin-password --query value -o tsv > secrets/grafana_admin_password
# Grafana runs as uid 472 and reads the file-based Compose secret.
chown 472:0 secrets/grafana_admin_password
chmod 0400 secrets/grafana_admin_password
chmod 0755 secrets

az acr login --name "$ACR_NAME" --output none
docker compose --profile fallback pull --quiet
docker compose up -d --remove-orphans
if [ "${COMPOSE_PROFILE:-}" = "fallback" ]; then
  docker compose --profile fallback up -d azure-metrics-exporter
else
  docker compose --profile fallback rm -sf azure-metrics-exporter >/dev/null 2>&1 || true
fi
docker compose restart otel-collector >/dev/null

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:13133/ >/dev/null && curl -fsS http://127.0.0.1:3000/api/health >/dev/null; then
    echo "GATEWAY_READY"
    docker compose ps --format '{{.Service}} {{.State}}'
    exit 0
  fi
  sleep 5
done
docker compose ps
docker compose logs --tail 40 otel-collector >&2
echo "GATEWAY_STEP_FAILED health" >&2
exit 1
