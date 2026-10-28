#!/usr/bin/env bash
# Imports the SQL Server dashboard into Azure Managed Grafana and points it at
# the Prometheus data source that the Azure Monitor workspace integration created.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

DASHBOARD="$SAMPLE_DIR/monitoring/grafana/sql-server-vm.dashboard.json"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> Finding the managed Prometheus data source in ${GRAFANA_NAME}"
DATASOURCE_UID=""
for _ in $(seq 1 20); do
  # The Grafana Admin role assignment can take a few minutes to propagate.
  DATASOURCE_UID="$(az grafana data-source list -g "$RG" -n "$GRAFANA_NAME" \
    --query "[?type=='prometheus'] | [0].uid" -o tsv 2>/dev/null || true)"
  [[ -n "$DATASOURCE_UID" ]] && break
  sleep 30
done
[[ -n "$DATASOURCE_UID" ]] || { echo "no Prometheus data source found in ${GRAFANA_NAME}" >&2; exit 1; }
echo "    uid=${DATASOURCE_UID}"

python3 "$SAMPLE_DIR/scripts/render_dashboard.py" "$DASHBOARD" "$DATASOURCE_UID" > "$TMP/dashboard.json"

echo "==> Importing dashboard"
az grafana dashboard create -g "$RG" -n "$GRAFANA_NAME" --definition "$TMP/dashboard.json" --overwrite true \
  --query "{uid:uid, url:url}" -o json
