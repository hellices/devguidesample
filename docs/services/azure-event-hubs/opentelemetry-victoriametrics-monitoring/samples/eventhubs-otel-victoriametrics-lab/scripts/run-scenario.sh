#!/usr/bin/env bash
# Drives a measured consumer-lag rise and recovery and records UTC boundaries in evidence/scenario.json.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands kubectl curl python3
load_env AZURE_ENV_NAME
NS=eventhubs-observability
EVIDENCE="$(evidence_dir)"
PORT="$(vm_local_port)"
BASELINE_MINUTES="${BASELINE_MINUTES:-5}"
LOAD_MINUTES="${LOAD_MINUTES:-10}"
RECOVERY_TIMEOUT_MINUTES="${RECOVERY_TIMEOUT_MINUTES:-20}"
EVENTS_PER_SECOND="${EVENTS_PER_SECOND:-200}"
PROCESSING_DELAY_SECONDS="${PROCESSING_DELAY_SECONDS:-0.03}"

COMPLETED=false
cleanup() {
  # An error or Ctrl-C after the load starts must not leave the producer sending.
  if [[ "$COMPLETED" != "true" ]]; then
    kube scale -n "$NS" deploy/eventhubs-producer --replicas 0 >/dev/null 2>&1 || true
  fi
  "$LAB_ROOT/scripts/vm-query.sh" stop
}
trap cleanup EXIT
"$LAB_ROOT/scripts/vm-query.sh" start

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
# Called through $(...), where errexit is off: return on failure so the caller's assignment fails
# instead of querying a port that may belong to another environment.
# Only series with a sample in the last 120 s count, so a stopped collector can never look like a
# recovery. Every partition reports eventhubs_checkpoint_present, but a non-empty partition without a
# checkpoint has no lag series; the maximum counts only when every partition has a fresh lag value,
# otherwise the function prints -1 instead of the maximum of the remaining partitions.
LAG_SERIES='eventhubs_consumer_lag_messages{source_path="lag_exporter",delivery_path="remote_write"}'
PARTITION_SERIES='eventhubs_checkpoint_present{source_path="lag_exporter",delivery_path="remote_write"}'
FRESH_LAG="($LAG_SERIES and (time() - timestamp($LAG_SERIES)) < 120)"
FRESH_PARTITIONS="($PARTITION_SERIES and (time() - timestamp($PARTITION_SERIES)) < 120)"
vm_scalar() {
  "$LAB_ROOT/scripts/vm-query.sh" start || return 1
  curl -fsS --max-time "$1" "http://127.0.0.1:$PORT/api/v1/query" --data-urlencode "query=$2" \
    | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(int(float(r[0]["value"][1])) if r else -1)'
}
max_lag() {
  vm_scalar "${1:-30}" "max($FRESH_LAG) and on() (count($FRESH_LAG) == count($FRESH_PARTITIONS))"
}
# The largest lag stored since the producer was scaled up (it may send before its rollout is
# reported complete); lag keeps rising until the producer stops.
peak_lag() {
  vm_scalar 30 "max(max_over_time($LAG_SERIES[$(( $(date +%s) - LOAD_REQUESTED_EPOCH ))s]))"
}
# Scaling to 0 only requests termination; the load ends when the producer pod is gone.
stop_producer() {
  kube scale -n "$NS" deploy/eventhubs-producer --replicas 0 >/dev/null
  # wait exits non-zero when no pod matches (already gone), so verify the result instead.
  kube wait -n "$NS" --for=delete pod -l app=eventhubs-producer --timeout 120s >/dev/null 2>&1 || true
  local remaining
  # An API or auth failure also prints nothing; only a successful empty listing proves termination.
  remaining="$(kube get pod -n "$NS" -l app=eventhubs-producer -o name)" || die "could not list producer pods"
  [[ -z "$remaining" ]] || die "producer pod is still running"
}
last_log_value() {
  kube logs -n "$NS" "deploy/$1" --tail 200 2>/dev/null | grep -o "$2=[0-9]*" | tail -1 | cut -d= -f2
}

# A previous interrupted run may have left the producer running; the baseline needs it stopped.
stop_producer
kube set env -n "$NS" deploy/eventhubs-slow-consumer PROCESSING_DELAY_SECONDS="$PROCESSING_DELAY_SECONDS" >/dev/null
kube set env -n "$NS" deploy/eventhubs-producer EVENTS_PER_SECOND="$EVENTS_PER_SECOND" >/dev/null
kube scale -n "$NS" deploy/eventhubs-slow-consumer --replicas 1 >/dev/null
kube rollout status -n "$NS" deploy/eventhubs-slow-consumer --timeout 300s >/dev/null

BASELINE_START="$(now)"
log "baseline ${BASELINE_MINUTES}m (producer stopped)"
sleep $((BASELINE_MINUTES * 60))

log "load ${LOAD_MINUTES}m at target ${EVENTS_PER_SECOND} events/s, consumer delay ${PROCESSING_DELAY_SECONDS}s/event/partition"
# load_requested is the earliest moment the producer can send; load_start is when its rollout is
# complete. The timed load runs from load_start, and the peak covers everything since the request.
LOAD_REQUESTED="$(now)"
LOAD_REQUESTED_EPOCH="$(date +%s)"
kube scale -n "$NS" deploy/eventhubs-producer --replicas 1 >/dev/null
kube rollout status -n "$NS" deploy/eventhubs-producer --timeout 300s >/dev/null
LOAD_START="$(now)"
LOAD_START_EPOCH="$(date +%s)"
LAG_AT_LOAD_START="$(max_lag)"
sleep $((LOAD_MINUTES * 60))
PRODUCER_SENT="$(last_log_value eventhubs-producer sent_total)"
CONSUMER_PROCESSED_AT_LOAD_END="$(last_log_value eventhubs-slow-consumer processed_total)"

stop_producer
PRODUCER_STOP="$(now)"
# Read the peak after the producer is gone and the exporter has stored its last rising sample.
sleep 20
PEAK_LAG="$(peak_lag)"
log "producer stopped; peak max lag=$PEAK_LAG"
# max_lag prints -1 when no series exists; both readings must be real before comparing.
[[ "$LAG_AT_LOAD_START" -ge 0 && "$PEAK_LAG" -gt 0 && "$PEAK_LAG" -gt "$LAG_AT_LOAD_START" ]] \
  || die "lag did not increase (start=$LAG_AT_LOAD_START peak=$PEAK_LAG)"

TARGET=$((PEAK_LAG / 5))
RECOVERED_AT=""
deadline=$(( $(date +%s) + RECOVERY_TIMEOUT_MINUTES * 60 ))
while [[ $(date +%s) -lt $deadline ]]; do
  # Bound each query by the time left, and count a recovery only if it was observed in time.
  remaining=$(( deadline - $(date +%s) ))
  current="$(max_lag "$(( remaining < 30 ? (remaining > 1 ? remaining : 1) : 30 ))")"
  if [[ $(date +%s) -le $deadline && "$current" -ge 0 && "$current" -le "$TARGET" ]]; then
    RECOVERED_AT="$(now)"
    break
  fi
  sleep 30
done
# Keep observing for two Azure Monitor minutes so the recovery tail is visible.
sleep 120
# Take the final readings first, then close the window, so every stored value lies inside it.
FINAL_LAG="$(max_lag)"
CONSUMER_PROCESSED="$(last_log_value eventhubs-slow-consumer processed_total)"
SCENARIO_END="$(now)"
[[ "$FINAL_LAG" -ge 0 ]] || die "no fresh lag sample at the end of the scenario"

# Serialize with Python so absent values become JSON null rather than the string "null".
python3 - "$EVIDENCE/scenario.json" <<PY
import json, sys
def number(value, kind=int):
    return kind(value) if value not in ("", None) else None
json.dump({
    "baseline_start": "$BASELINE_START",
    "load_requested": "$LOAD_REQUESTED",
    "load_start": "$LOAD_START",
    "producer_stop": "$PRODUCER_STOP",
    "recovered_at": "$RECOVERED_AT" or None,
    "scenario_end": "$SCENARIO_END",
    "target_events_per_second": number("$EVENTS_PER_SECOND"),
    "processing_delay_seconds": number("$PROCESSING_DELAY_SECONDS", float),
    "producer_sent_total": number("$PRODUCER_SENT"),
    "consumer_processed_total_at_load_end": number("$CONSUMER_PROCESSED_AT_LOAD_END"),
    "consumer_processed_total": number("$CONSUMER_PROCESSED"),
    "max_lag_at_load_start": number("$LAG_AT_LOAD_START"),
    "peak_max_lag": number("$PEAK_LAG"),
    "final_max_lag": number("$FINAL_LAG"),
}, open(sys.argv[1], "w"), indent=2)
PY
cat "$EVIDENCE/scenario.json"
COMPLETED=true
[[ -n "$RECOVERED_AT" ]] || die "max lag did not recover by 80% within ${RECOVERY_TIMEOUT_MINUTES}m"
log "scenario completed"
