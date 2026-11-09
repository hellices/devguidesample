#!/usr/bin/env bash
# Drives a measured consumer-lag rise and recovery and records UTC boundaries in evidence/scenario.json.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands kubectl curl python3
load_env AZURE_ENV_NAME
NS=eventhubs-observability
EVIDENCE="$(evidence_dir)"
PORT="${VM_LOCAL_PORT:-18428}"
BASELINE_MINUTES="${BASELINE_MINUTES:-5}"
LOAD_MINUTES="${LOAD_MINUTES:-10}"
RECOVERY_TIMEOUT_MINUTES="${RECOVERY_TIMEOUT_MINUTES:-20}"
EVENTS_PER_SECOND="${EVENTS_PER_SECOND:-200}"
PROCESSING_DELAY_SECONDS="${PROCESSING_DELAY_SECONDS:-0.03}"

"$LAB_ROOT/scripts/vm-query.sh" start
trap '"$LAB_ROOT/scripts/vm-query.sh" stop' EXIT

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
max_lag() {
  "$LAB_ROOT/scripts/vm-query.sh" start
  curl -fsS "http://127.0.0.1:$PORT/api/v1/query" \
    --data-urlencode 'query=max(eventhubs_consumer_lag_messages{source_path="lag_exporter",delivery_path="remote_write"})' \
    | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(int(float(r[0]["value"][1])) if r else -1)'
}
last_log_value() {
  kube logs -n "$NS" "deploy/$1" --tail 200 2>/dev/null | grep -o "$2=[0-9]*" | tail -1 | cut -d= -f2
}

kube set env -n "$NS" deploy/eventhubs-slow-consumer PROCESSING_DELAY_SECONDS="$PROCESSING_DELAY_SECONDS" >/dev/null
kube set env -n "$NS" deploy/eventhubs-producer EVENTS_PER_SECOND="$EVENTS_PER_SECOND" >/dev/null
kube scale -n "$NS" deploy/eventhubs-slow-consumer --replicas 1 >/dev/null
kube rollout status -n "$NS" deploy/eventhubs-slow-consumer --timeout 300s >/dev/null

BASELINE_START="$(now)"
log "baseline ${BASELINE_MINUTES}m (producer stopped)"
sleep $((BASELINE_MINUTES * 60))

LOAD_START="$(now)"
log "load ${LOAD_MINUTES}m at target ${EVENTS_PER_SECOND} events/s, consumer delay ${PROCESSING_DELAY_SECONDS}s/event/partition"
kube scale -n "$NS" deploy/eventhubs-producer --replicas 1 >/dev/null
kube rollout status -n "$NS" deploy/eventhubs-producer --timeout 300s >/dev/null
LAG_AT_LOAD_START="$(max_lag)"
sleep $((LOAD_MINUTES * 60))
PRODUCER_SENT="$(last_log_value eventhubs-producer sent_total)"
PEAK_LAG="$(max_lag)"
CONSUMER_PROCESSED_AT_PEAK="$(last_log_value eventhubs-slow-consumer processed_total)"

PRODUCER_STOP="$(now)"
log "producer stopped; peak max lag=$PEAK_LAG"
kube scale -n "$NS" deploy/eventhubs-producer --replicas 0 >/dev/null
[[ "$PEAK_LAG" -gt "$LAG_AT_LOAD_START" ]] || die "lag did not increase (start=$LAG_AT_LOAD_START peak=$PEAK_LAG)"

TARGET=$((PEAK_LAG / 5))
RECOVERED_AT=""
deadline=$(( $(date +%s) + RECOVERY_TIMEOUT_MINUTES * 60 ))
while [[ $(date +%s) -lt $deadline ]]; do
  current="$(max_lag)"
  if [[ "$current" -ge 0 && "$current" -le "$TARGET" ]]; then
    RECOVERED_AT="$(now)"
    break
  fi
  sleep 30
done
FINAL_LAG="$(max_lag)"
# Keep observing for two Azure Monitor minutes so the recovery tail is visible.
sleep 120
SCENARIO_END="$(now)"
CONSUMER_PROCESSED="$(last_log_value eventhubs-slow-consumer processed_total)"

cat >"$EVIDENCE/scenario.json" <<JSON
{
  "baseline_start": "$BASELINE_START",
  "load_start": "$LOAD_START",
  "producer_stop": "$PRODUCER_STOP",
  "recovered_at": "${RECOVERED_AT:-null}",
  "scenario_end": "$SCENARIO_END",
  "target_events_per_second": $EVENTS_PER_SECOND,
  "processing_delay_seconds": $PROCESSING_DELAY_SECONDS,
  "producer_sent_total": ${PRODUCER_SENT:-null},
  "consumer_processed_total_at_peak": ${CONSUMER_PROCESSED_AT_PEAK:-null},
  "consumer_processed_total": ${CONSUMER_PROCESSED:-null},
  "max_lag_at_load_start": $LAG_AT_LOAD_START,
  "peak_max_lag": $PEAK_LAG,
  "final_max_lag": $FINAL_LAG
}
JSON
cat "$EVIDENCE/scenario.json"
[[ -n "$RECOVERED_AT" ]] || die "max lag did not recover by 80% within ${RECOVERY_TIMEOUT_MINUTES}m"
log "scenario completed"
