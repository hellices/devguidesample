#!/usr/bin/env bash
# Runs on the gateway VM through Azure VM Run Command.
# BUNDLE_B64 arrives as a named Run Command parameter (environment variable) holding a base64 tar.gz.
set -euo pipefail
trap 'echo "GATEWAY_STEP_FAILED line $LINENO" >&2' ERR
BUNDLE_B64="${BUNDLE_B64:?BUNDLE_B64 parameter is required}"
APP_DIR="${APP_DIR:-/opt/eventhubs-observability}"

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

# Grafana listens on the public IP for the operator /32 only. Serve it over TLS with a
# self-signed certificate for that IP; the operator pins this certificate (printed below).
install -d -m 0755 tls
# Regenerate when the certificate or key is missing, the key does not match, the certificate was
# issued for another IP, or it expires within a day (30-day validity).
cert_key_match() {
  [ "$(openssl x509 -in tls/grafana.crt -noout -pubkey 2>/dev/null)" = "$(openssl pkey -in tls/grafana.key -pubout 2>/dev/null)" ] \
    && [ -n "$(openssl pkey -in tls/grafana.key -pubout 2>/dev/null)" ]
}
CERT_RENEWED=false
if [ ! -s tls/grafana.crt ] || [ ! -s tls/grafana.key ] || ! cert_key_match \
  || ! openssl x509 -in tls/grafana.crt -noout -checkend 86400 >/dev/null 2>&1 \
  || ! openssl x509 -in tls/grafana.crt -noout -ext subjectAltName 2>/dev/null \
    | tr ',' '\n' | sed 's/^ *//' | grep -qxF "IP Address:${GATEWAY_PUBLIC_IP}"; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=eventhubs-lab-grafana" \
    -addext "subjectAltName=IP:${GATEWAY_PUBLIC_IP}" -keyout tls/grafana.key -out tls/grafana.crt 2>/dev/null
  CERT_RENEWED=true
fi
chown 472:0 tls/grafana.key tls/grafana.crt
chmod 0400 tls/grafana.key
chmod 0444 tls/grafana.crt

az acr login --name "$ACR_NAME" --output none
docker compose --profile fallback pull --quiet
docker compose up -d --remove-orphans
if [ "${COMPOSE_PROFILE:-}" = "fallback" ]; then
  docker compose --profile fallback up -d azure-metrics-exporter
else
  docker compose --profile fallback rm -sf azure-metrics-exporter >/dev/null 2>&1 || true
fi
docker compose restart otel-collector >/dev/null
# Grafana loads its certificate at startup and `up -d` keeps an unchanged running container.
if [ "$CERT_RENEWED" = true ]; then
  docker compose restart grafana >/dev/null
fi

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:13133/ >/dev/null \
    && curl -fsS --cacert tls/grafana.crt --resolve "${GATEWAY_PUBLIC_IP}:3000:127.0.0.1" \
      "https://${GATEWAY_PUBLIC_IP}:3000/api/health" >/dev/null; then
    echo "GATEWAY_READY"
    docker compose ps --format '{{.Service}} {{.State}}'
    # Public certificate only; the private key never leaves the VM.
    echo "GRAFANA_CERT_BEGIN"
    cat tls/grafana.crt
    echo "GRAFANA_CERT_END"
    exit 0
  fi
  sleep 5
done
docker compose ps
docker compose logs --tail 40 otel-collector >&2
echo "GATEWAY_STEP_FAILED health" >&2
exit 1
