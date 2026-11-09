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
export GRAFANA_URL="http://$GATEWAY_PUBLIC_IP:3000"
export GRAFANA_USER=admin
GRAFANA_PASSWORD="$(env_value GRAFANA_ADMIN_PASSWORD)"
export GRAFANA_PASSWORD

"$LAB_ROOT/scripts/vm-query.sh" start
trap '"$LAB_ROOT/scripts/vm-query.sh" stop' EXIT

log "probe"
"$PY" "$LAB_ROOT/agent/probe.py" --output "$EVIDENCE/probe.json"
log "build and publish"
"$PY" "$LAB_ROOT/agent/build_dashboard.py" --probe "$EVIDENCE/probe.json" --output "$EVIDENCE/dashboard.json"
"$PY" "$LAB_ROOT/agent/publish_dashboard.py" "$EVIDENCE/dashboard.json"
log "verify panels over $FROM .. $TO"
"$PY" "$LAB_ROOT/agent/verify_panels.py" --from "$FROM_MS" --to "$TO_MS" --output "$EVIDENCE/panel-verification.json"
log "capture"
(cd "$LAB_ROOT/agent" && [[ -d node_modules ]] || npm ci --silent && npx playwright install chromium >/dev/null)
node "$LAB_ROOT/agent/capture.mjs" /d/eventhubs-otel-victoriametrics "$EVIDENCE/grafana-dashboard.png" "$FROM_MS" "$TO_MS"

log "Azure Monitor direct query for the same window"
NAMESPACE_ID="$(az eventhubs namespace show --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" \
  -n "$PREMIUM_NAMESPACE_NAME" --query id -o tsv)"
az monitor metrics list --subscription "$AZURE_SUBSCRIPTION_ID" --resource "$NAMESPACE_ID" \
  --metrics IncomingMessages OutgoingMessages IncomingRequests ThrottledRequests \
  --aggregation Total --interval PT1M --start-time "$FROM" --end-time "$TO" -o json >"$EVIDENCE/azure-monitor-raw.json"
# Compare Azure Monitor PT1M bins with the remote write samples (same minute timestamps) and with
# the scrape path, whose samples are re-stamped at scrape time and repeat each minute value.
python3 - "$EVIDENCE/azure-monitor-raw.json" "$FROM_MS" "$TO_MS" >"$EVIDENCE/azure-monitor-comparison.json" <<'PY'
import json, sys, urllib.parse, urllib.request
raw, start_ms, end_ms = json.load(open(sys.argv[1])), int(sys.argv[2]), int(sys.argv[3])
start, end = start_ms // 1000, end_ms // 1000

def vm(path, params):
    body = urllib.parse.urlencode(params).encode()
    return urllib.request.urlopen(f"http://127.0.0.1:18428{path}", body).read().decode()

report = {"window": {"from": start, "to": end}, "metrics": {}}
for metric in raw["value"]:
    name = metric["name"]["value"]
    direct = {}
    for series in metric["timeseries"]:
        for point in series["data"]:
            minute = point["timeStamp"][:16]
            direct[minute] = direct.get(minute, 0) + (point.get("total") or 0)
    selector = f'azure_{name.lower()}_total_Count{{source_path="azure_monitor_api",delivery_path="remote_write"}}'
    remote = {}
    for line in vm("/api/v1/export", {"match[]": selector, "start": start, "end": end - 1}).splitlines():
        series = json.loads(line)
        for value, ts in zip(series["values"], series["timestamps"]):
            minute = __import__("datetime").datetime.fromtimestamp(ts / 1000, __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M")
            remote[minute] = remote.get(minute, 0) + value
    totals = {}
    for delivery in ("remote_write", "scrape"):
        q = (f'sum(sum_over_time(azure_{name.lower()}_total_Count'
             f'{{source_path="azure_monitor_api",delivery_path="{delivery}"}}[{end - start}s]))')
        result = json.loads(vm("/api/v1/query", {"query": q, "time": end - 1}))["data"]["result"]
        totals[delivery] = float(result[0]["value"][1]) if result else None
    diagnostic = {}
    for line in vm("/api/v1/export", {"match[]": f'{name.lower()}_total{{source_path="diagnostic_eventhub",delivery_path="remote_write"}}',
                                      "start": start, "end": end - 1}).splitlines():
        series = json.loads(line)
        for value, ts in zip(series["values"], series["timestamps"]):
            minute = __import__("datetime").datetime.fromtimestamp(ts / 1000, __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M")
            diagnostic[minute] = diagnostic.get(minute, 0) + value
    minutes = sorted(direct)
    report["metrics"][name] = {
        "azure_monitor_total": sum(direct.values()),
        "victoriametrics_total": totals,
        "minutes": len(minutes),
        "minutes_matching_remote_write": sum(1 for m in minutes if remote.get(m) == direct[m]),
        "minutes_missing_in_remote_write": [m for m in minutes if m not in remote and direct[m]],
        "diagnostic_eventhub_total": sum(diagnostic.values()) if diagnostic else None,
        "minutes_matching_diagnostic_eventhub": sum(1 for m in minutes if diagnostic.get(m) == direct[m]),
        "minutes_present_in_diagnostic_eventhub": sum(1 for m in minutes if m in diagnostic),
    }
print(json.dumps(report, indent=2))
PY
cat "$EVIDENCE/azure-monitor-comparison.json"
