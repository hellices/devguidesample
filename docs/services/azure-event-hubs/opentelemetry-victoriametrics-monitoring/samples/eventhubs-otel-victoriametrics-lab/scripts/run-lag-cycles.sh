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
# Returns only once no producer Pod is left, so producer_stop marks the real end of sending.
stop_producer() {
  kube scale -n "$NS" deploy/eventhubs-producer --replicas 0 >/dev/null || return 1
  # wait exits non-zero when no Pod matches (already gone), so verify the result instead.
  kube wait -n "$NS" --for=delete pod -l app=eventhubs-producer --timeout 120s >/dev/null 2>&1 || true
  local remaining
  # An API or auth failure also prints nothing; only a successful empty listing proves termination.
  remaining="$(kube get pod -n "$NS" -l app=eventhubs-producer -o name)" || return 1
  [[ -z "$remaining" ]]
}
# Whatever ends the loop (completion, an error, Ctrl-C), the producer must not keep sending.
trap 'stop_producer || log "WARNING: could not stop the producer; scale deploy/eventhubs-producer to 0"; record "stopped (producer 0)"' EXIT

kube set env -n "$NS" deploy/eventhubs-slow-consumer PROCESSING_DELAY_SECONDS="$PROCESSING_DELAY_SECONDS" >/dev/null
kube set env -n "$NS" deploy/eventhubs-producer EVENTS_PER_SECOND="$EVENTS_PER_SECOND" >/dev/null
kube scale -n "$NS" deploy/eventhubs-slow-consumer --replicas 1 >/dev/null
# The first cycle must already run against the consumer configured above.
kube rollout status -n "$NS" deploy/eventhubs-slow-consumer --timeout 180s >/dev/null \
  || die "slow consumer did not become ready"
stop_producer || die "producer is still running before the first cycle"
END=$(( $(date +%s) + DURATION_SECONDS ))
record "start: ${DURATION_SECONDS}s total, load ${LOAD_SECONDS}s at ${EVENTS_PER_SECOND} events/s, drain ${DRAIN_SECONDS}s"

cycle=0
# A cycle starts only if its whole load phase fits; the last drain may be cut short by the deadline.
while (( $(date +%s) + LOAD_SECONDS <= END )); do
  kube scale -n "$NS" deploy/eventhubs-producer --replicas 1 >/dev/null
  # Scheduling or an image pull must not shorten the load, and a producer that never starts must not
  # count as a cycle: load_start is recorded only after the rollout, if the whole load still fits.
  kube rollout status -n "$NS" deploy/eventhubs-producer --timeout 180s >/dev/null \
    || die "producer did not become ready"
  if (( $(date +%s) + LOAD_SECONDS > END )); then
    stop_producer || die "could not stop the producer"
    break
  fi
  cycle=$((cycle + 1))
  record "cycle $cycle load_start"
  sleep "$LOAD_SECONDS"
  stop_producer || die "producer is still running after the load phase"
  record "cycle $cycle producer_stop"
  left=$(( END - $(date +%s) ))
  (( left > 0 )) || break
  sleep $(( DRAIN_SECONDS < left ? DRAIN_SECONDS : left ))
  record "cycle $cycle drain_end"
done
record "done after $cycle cycles"
