#!/usr/bin/env bash
# Runs on the gateway VM through Azure VM Run Command.
# BUNDLE_B64 arrives as a named Run Command parameter (environment variable) holding a base64 tar.gz.
set -euo pipefail
trap 'echo "GATEWAY_STEP_FAILED line $LINENO" >&2' ERR
# Run Command reports only the output, not the script's exit status; the last line carries it.
BUNDLE_DIR=""
trap 'rc=$?; [ -n "$BUNDLE_DIR" ] && rm -rf "$BUNDLE_DIR"; echo "GATEWAY_EXIT_CODE=$rc"' EXIT
BUNDLE_B64="${BUNDLE_B64:?BUNDLE_B64 parameter is required}"
# Run Command starts without HOME; Azure CLI would then write its cache under ./None in APP_DIR.
export HOME="${HOME:-/root}"
APP_DIR="${APP_DIR:-/opt/eventhubs-observability}"
# Every top-level entry of APP_DIR is replaced below, so it must be a dedicated directory: a
# canonical path at least two levels deep (never / or /opt), and if it already holds files they
# must carry this bundle's marker. Common names such as tls/ or secrets/ alone prove nothing.
BUNDLE_MARKER=.eventhubs-observability-bundle
while [ "${APP_DIR%/}" != "$APP_DIR" ]; do APP_DIR="${APP_DIR%/}"; done
case "$APP_DIR/" in
  */./* | */../* | *//*) echo "GATEWAY_STEP_FAILED unsafe APP_DIR $APP_DIR" >&2; exit 1 ;;
esac
case "$APP_DIR" in
  /*/?*) ;;
  *) echo "GATEWAY_STEP_FAILED unsafe APP_DIR ${APP_DIR:-/}" >&2; exit 1 ;;
esac
if [ -d "$APP_DIR" ] && [ -n "$(ls -A "$APP_DIR")" ] && [ ! -e "$APP_DIR/$BUNDLE_MARKER" ]; then
  echo "GATEWAY_STEP_FAILED APP_DIR $APP_DIR is not a gateway bundle directory" >&2
  exit 1
fi

cloud-init status --wait >/dev/null || true
command -v docker >/dev/null
command -v az >/dev/null

install -d -m 0755 "$APP_DIR"
# Unpack into a fresh directory first, then replace every bundle-managed file so files removed
# from a newer bundle do not linger. Only runtime state (secrets/, tls/) survives a rerun.
BUNDLE_DIR="$(mktemp -d)"
echo "$BUNDLE_B64" | base64 -d | tar -xz -C "$BUNDLE_DIR"
[ -s "$BUNDLE_DIR/.env" ] && [ -s "$BUNDLE_DIR/compose.yaml" ] || { echo "GATEWAY_STEP_FAILED bundle" >&2; exit 1; }
# Move the previous bundle aside on the same filesystem and put it back if the copy fails, so a
# failed update never leaves a half-installed directory.
PREVIOUS_DIR="$(mktemp -d "${APP_DIR}.previous.XXXXXX")"
# Puts the moved-aside entries back. After a failed copy, the partial new bundle is removed first;
# after a failed move, APP_DIR still holds the entries that were not moved and they are kept.
restore_previous() {
  if [[ "${1:-}" == "--discard-new" ]]; then
    find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name secrets ! -name tls -exec rm -rf {} +
  fi
  find "$PREVIOUS_DIR" -mindepth 1 -maxdepth 1 -exec mv {} "$APP_DIR/" \;
  rmdir "$PREVIOUS_DIR"
}
# One mv per entry with its status checked: `find -exec mv` would hide a failed move, leaving a
# stale file from an older bundle in place.
while IFS= read -r -d '' entry; do
  if ! mv "$entry" "$PREVIOUS_DIR/"; then
    restore_previous
    echo "GATEWAY_STEP_FAILED could not move $entry aside; previous bundle restored" >&2
    exit 1
  fi
done < <(find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name secrets ! -name tls -print0)
if ! cp -a "$BUNDLE_DIR/." "$APP_DIR/"; then
  restore_previous --discard-new
  echo "GATEWAY_STEP_FAILED bundle copy; previous bundle restored" >&2
  exit 1
fi
rm -rf "$PREVIOUS_DIR"
touch "$APP_DIR/$BUNDLE_MARKER"
cd "$APP_DIR"
set -a; . ./.env; set +a

az login --identity --client-id "$GATEWAY_CLIENT_ID" --allow-no-subscriptions --output none
install -d -m 0700 secrets
# Write to a temporary file and replace the secret only after a successful read, so a transient
# Key Vault failure never truncates the password Grafana already uses.
SECRET_TMP="$(mktemp secrets/.grafana_admin_password.XXXXXX)"
az keyvault secret show --vault-name "$KEY_VAULT_NAME" --name grafana-admin-password --query value -o tsv >"$SECRET_TMP" \
  || { rm -f "$SECRET_TMP"; echo "GATEWAY_STEP_FAILED key vault secret" >&2; exit 1; }
[ -s "$SECRET_TMP" ] || { rm -f "$SECRET_TMP"; echo "GATEWAY_STEP_FAILED empty key vault secret" >&2; exit 1; }
# Grafana runs as uid 472 and reads the file-based Compose secret.
chown 472:0 "$SECRET_TMP"
chmod 0400 "$SECRET_TMP"
mv -f "$SECRET_TMP" secrets/grafana_admin_password
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
# Pull the fallback exporter image only when it will run; the default deployment must not depend on it.
if [ "${COMPOSE_PROFILE:-}" = "fallback" ]; then
  docker compose --profile fallback pull --quiet
else
  docker compose pull --quiet
fi
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

# The fallback exporter has no HTTP check here, so require its container to be running.
fallback_ready() {
  [ "${COMPOSE_PROFILE:-}" != "fallback" ] \
    || docker compose --profile fallback ps --status running --services 2>/dev/null | grep -qx azure-metrics-exporter
}

for _ in $(seq 1 30); do
  # Bounded requests keep the loop (30 tries) finite even if a service accepts but never answers.
  if curl -fsS --connect-timeout 3 --max-time 5 http://127.0.0.1:13133/ >/dev/null \
    && curl -fsS --connect-timeout 3 --max-time 5 --cacert tls/grafana.crt --resolve "${GATEWAY_PUBLIC_IP}:3000:127.0.0.1" \
      "https://${GATEWAY_PUBLIC_IP}:3000/api/health" >/dev/null \
    && fallback_ready; then
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
