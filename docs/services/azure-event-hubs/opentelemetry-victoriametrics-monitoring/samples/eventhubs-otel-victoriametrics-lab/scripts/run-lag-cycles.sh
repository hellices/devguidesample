#!/usr/bin/env bash
# Repeats consumer-lag build-up and drain for a fixed time: the producer sends for LOAD_SECONDS, then
# stops for DRAIN_SECONDS while the slow consumer catches up. Each boundary is appended to
# evidence/<env>/lag-cycles.log so the cycles can be compared afterwards.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands kubectl
load_env AZURE_ENV_NAME
NS=eventhubs-observability
EVIDENCE="$(evidence_dir)"
LOG_FILE="$EVIDENCE/lag-cycles.log"
DURATION_SECONDS="${DURATION_SECONDS:-14400}"
LOAD_SECONDS="${LOAD_SECONDS:-600}"
DRAIN_SECONDS="${DRAIN_SECONDS:-900}"
EVENTS_PER_SECOND="${EVENTS_PER_SECOND:-200}"
PROCESSING_DELAY_SECONDS="${PROCESSING_DELAY_SECONDS:-0.03}"
for value in "$DURATION_SECONDS" "$LOAD_SECONDS" "$DRAIN_SECONDS"; do
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || die "DURATION_SECONDS, LOAD_SECONDS and DRAIN_SECONDS must be positive integers"
done

record() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG_FILE" >&2; }
stop_producer() { kube scale -n "$NS" deploy/eventhubs-producer --replicas 0 >/dev/null; }
# Whatever ends the loop (completion, an error, Ctrl-C), the producer must not keep sending.
trap 'stop_producer || log "WARNING: could not stop the producer; scale deploy/eventhubs-producer to 0"; record "stopped (producer 0)"' EXIT

kube set env -n "$NS" deploy/eventhubs-slow-consumer PROCESSING_DELAY_SECONDS="$PROCESSING_DELAY_SECONDS" >/dev/null
kube set env -n "$NS" deploy/eventhubs-producer EVENTS_PER_SECOND="$EVENTS_PER_SECOND" >/dev/null
kube scale -n "$NS" deploy/eventhubs-slow-consumer --replicas 1 >/dev/null
stop_producer
END=$(( $(date +%s) + DURATION_SECONDS ))
record "start: ${DURATION_SECONDS}s total, load ${LOAD_SECONDS}s at ${EVENTS_PER_SECOND} events/s, drain ${DRAIN_SECONDS}s"

cycle=0
# A cycle starts only if its whole load phase fits; the last drain may be cut short by the deadline.
while (( $(date +%s) + LOAD_SECONDS <= END )); do
  cycle=$((cycle + 1))
  kube scale -n "$NS" deploy/eventhubs-producer --replicas 1 >/dev/null
  record "cycle $cycle load_start"
  sleep "$LOAD_SECONDS"
  stop_producer
  record "cycle $cycle producer_stop"
  left=$(( END - $(date +%s) ))
  (( left > 0 )) || break
  sleep $(( DRAIN_SECONDS < left ? DRAIN_SECONDS : left ))
  record "cycle $cycle drain_end"
done
record "done after $cycle cycles"
