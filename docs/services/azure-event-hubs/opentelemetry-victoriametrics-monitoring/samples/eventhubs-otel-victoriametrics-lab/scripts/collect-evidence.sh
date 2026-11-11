#!/usr/bin/env bash
# Agent dashboard workflow over the recorded scenario window:
# probe -> build -> publish -> verify every panel -> capture, plus a direct Azure Monitor cross-check.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands az azd node python3 curl
load_env AZURE_SUBSCRIPTION_ID AZURE_ENV_NAME AZURE_RESOURCE_GROUP PREMIUM_NAMESPACE_NAME GATEWAY_PUBLIC_IP
assert_active_subscription
EVIDENCE="$(evidence_dir)"
STATE="$(state_dir)"
PY="$STATE/venv/bin/python"
[[ -f "$EVIDENCE/scenario.json" ]] || die "run ./scripts/run-scenario.sh first"

read -r FROM TO FROM_MS TO_MS < <(python3 - "$EVIDENCE/scenario.json" <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone
s = json.load(open(sys.argv[1]))
parse = lambda v: datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
# Align to whole minutes so Azure Monitor PT1M bins and VictoriaMetrics windows cover the same samples.
start = parse(s["baseline_start"]).replace(second=0)
end = (parse(s["scenario_end"]) + timedelta(minutes=3)).replace(second=0)
fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
print(fmt(start), fmt(end), int(start.timestamp() * 1000), int(end.timestamp() * 1000))
PY
)
export GRAFANA_URL="https://$GATEWAY_PUBLIC_IP:3000"
export GRAFANA_CA_FILE="$STATE/grafana.crt"
[[ -s "$GRAFANA_CA_FILE" ]] || die "missing pinned Grafana certificate; rerun azd hooks run postprovision"
export GRAFANA_USER=admin
GRAFANA_PASSWORD="$(env_value GRAFANA_ADMIN_PASSWORD)"
export GRAFANA_PASSWORD

PORT="$(vm_local_port)"
# Azure Monitor API samples arrive about 3 minutes after their bin and Diagnostic Settings
# about 7–9 minutes; do not verify or capture a window whose last bins are still in flight.
SETTLE_SECONDS="${EVIDENCE_SETTLE_SECONDS:-540}"
remaining=$(( TO_MS / 1000 + SETTLE_SECONDS - $(date +%s) ))
if (( remaining > 0 )); then
  log "waiting ${remaining}s for the window's last minute bins to arrive"
  sleep "$remaining"
fi

"$LAB_ROOT/scripts/vm-query.sh" start
trap '"$LAB_ROOT/scripts/vm-query.sh" stop' EXIT

log "probe"
"$PY" "$LAB_ROOT/agent/probe.py" --vm-url "http://127.0.0.1:$PORT" --output "$EVIDENCE/probe.json"
log "build and publish"
TIER="$(env_value EVENTHUBS_SKU | tr '[:upper:]' '[:lower:]')"
PLATFORM_METRICS="$(env_value PLATFORM_METRICS)"
if [[ "${PLATFORM_METRICS:-Collector}" == "AzureMonitor" ]]; then
  # Platform metrics come from the Azure Monitor data source; only lag (and logs) from VictoriaMetrics.
  DASHBOARD_UID=eventhubs-azure-monitor-direct
  CLUSTER_ID="$(env_value DEDICATED_CLUSTER_RESOURCE_ID)"
  "$PY" "$LAB_ROOT/agent/build_direct_dashboard.py" --tier "${TIER:-premium}" \
    --subscription "$AZURE_SUBSCRIPTION_ID" --resource-group "$AZURE_RESOURCE_GROUP" \
    --namespace "$PREMIUM_NAMESPACE_NAME" --cluster "${CLUSTER_ID##*/}" --output "$EVIDENCE/dashboard.json"
else
  DASHBOARD_UID=eventhubs-otel-victoriametrics
  "$PY" "$LAB_ROOT/agent/build_dashboard.py" --probe "$EVIDENCE/probe.json" --tier "${TIER:-premium}" \
    --output "$EVIDENCE/dashboard.json"
fi
"$PY" "$LAB_ROOT/agent/publish_dashboard.py" "$EVIDENCE/dashboard.json"
log "verify panels over $FROM .. $TO"
"$PY" "$LAB_ROOT/agent/verify_panels.py" --uid "$DASHBOARD_UID" --from "$FROM_MS" --to "$TO_MS" \
  --output "$EVIDENCE/panel-verification.json"
log "capture"
# npm ci recreates node_modules; the stamp marks a completed install of this lockfile.
(cd "$LAB_ROOT/agent" \
  && { cmp -s package-lock.json node_modules/.lab-package-lock.json \
       || { npm ci --silent && cp package-lock.json node_modules/.lab-package-lock.json; }; } \
  && npx playwright install chromium >/dev/null) || die "could not install the capture dependencies"
node "$LAB_ROOT/agent/capture.mjs" "/d/$DASHBOARD_UID" "$EVIDENCE/grafana-dashboard.png" "$FROM_MS" "$TO_MS"

MANAGED_ENDPOINT="$(env_value MANAGED_GRAFANA_ENDPOINT)"
if [[ -n "$MANAGED_ENDPOINT" ]]; then
  log "Managed Grafana: publish, verify and capture the same dashboard"
  # Managed Grafana takes a Microsoft Entra token for its own audience; the deployer has Grafana Admin.
  MANAGED_TOKEN="$(az account get-access-token --resource https://dashboard.azure.com --query accessToken -o tsv)" \
    || die "could not get a Microsoft Entra token for Managed Grafana"
  (
    export GRAFANA_URL="$MANAGED_ENDPOINT" GRAFANA_TOKEN="$MANAGED_TOKEN"
    unset GRAFANA_CA_FILE GRAFANA_PASSWORD
    "$PY" "$LAB_ROOT/agent/publish_dashboard.py" "$EVIDENCE/dashboard.json"
    "$PY" "$LAB_ROOT/agent/verify_panels.py" --uid "$DASHBOARD_UID" --from "$FROM_MS" --to "$TO_MS" \
      --output "$EVIDENCE/panel-verification-managed.json"
    node "$LAB_ROOT/agent/capture.mjs" "/d/$DASHBOARD_UID" "$EVIDENCE/grafana-dashboard-managed.png" \
      "$FROM_MS" "$TO_MS"
  ) || die "Managed Grafana could not show the dashboard"
fi

log "Azure Monitor direct query for the same window"
NAMESPACE_ID="$(az eventhubs namespace show --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" \
  -n "$PREMIUM_NAMESPACE_NAME" --query id -o tsv)"
az monitor metrics list --subscription "$AZURE_SUBSCRIPTION_ID" --resource "$NAMESPACE_ID" \
  --metrics IncomingMessages OutgoingMessages IncomingRequests ThrottledRequests \
  --aggregation Total --interval PT1M --start-time "$FROM" --end-time "$TO" -o json >"$EVIDENCE/azure-monitor-raw.json"
if [[ "$DASHBOARD_UID" == "eventhubs-azure-monitor-direct" ]]; then
  # Grafana queried the same Azure Monitor bins; its panel sums must equal the CLI totals.
  for report in panel-verification panel-verification-managed; do
    [[ -f "$EVIDENCE/$report.json" ]] || continue
    "$PY" "$LAB_ROOT/agent/compare_grafana_azure_monitor.py" --panel-verification "$EVIDENCE/$report.json" \
      --azure-monitor "$EVIDENCE/azure-monitor-raw.json" --output "$EVIDENCE/$report-azure-monitor.json" \
      || die "Grafana $report totals differ from the direct Azure Monitor query"
  done
  exit 0
fi
"$PY" "$LAB_ROOT/agent/compare_azure_monitor.py" --azure-monitor "$EVIDENCE/azure-monitor-raw.json" \
  --from-ms "$FROM_MS" --to-ms "$TO_MS" --vm-url "http://127.0.0.1:$PORT" \
  --output "$EVIDENCE/azure-monitor-comparison.json" >/dev/null \
  || die "remote write does not yet match Azure Monitor for every requested metric and minute; evidence is incomplete"
cat "$EVIDENCE/azure-monitor-comparison.json"
GAPS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["remote_write_gaps"])' "$EVIDENCE/azure-monitor-comparison.json")"
if (( GAPS > 0 )); then
  log "WARNING: $GAPS minute bin(s) were skipped by azuremonitorreceiver and will not arrive; see remote_write_gaps"
fi
