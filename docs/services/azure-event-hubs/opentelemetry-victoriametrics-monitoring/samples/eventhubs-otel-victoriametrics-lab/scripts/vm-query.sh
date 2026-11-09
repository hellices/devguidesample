#!/usr/bin/env bash
# Usage: vm-query.sh start|stop|port. Opens (or repairs) this environment's local port-forward
# to the private VMSingle service, or prints the local port it uses.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"
STATE="$(state_dir)"
PORT="$(vm_local_port)"

owned_forward() {
  [[ -f "$STATE/port-forward.pid" && -f "$STATE/port-forward.port" ]] \
    && [[ "$(<"$STATE/port-forward.port")" == "$PORT" ]] \
    && kill -0 "$(<"$STATE/port-forward.pid")" 2>/dev/null
}

healthy() {
  curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1
}

case "${1:-start}" in
  port)
    printf '%s\n' "$PORT"
    ;;
  start)
    # Long-lived port-forwards drop with "lost connection to pod"; trust only our own live forward.
    if owned_forward && healthy; then
      exit 0
    fi
    if owned_forward; then
      kill "$(<"$STATE/port-forward.pid")" 2>/dev/null || true
      sleep 1
    elif healthy; then
      die "port $PORT already serves another VictoriaMetrics; set VM_LOCAL_PORT for this environment"
    fi
    kube port-forward -n eventhubs-observability svc/vmsingle-lab "$PORT:8428" >"$STATE/port-forward.log" 2>&1 &
    echo $! >"$STATE/port-forward.pid"
    printf '%s\n' "$PORT" >"$STATE/port-forward.port"
    for _ in $(seq 1 20); do
      healthy && exit 0
      sleep 1
    done
    die "VMSingle port-forward did not become ready on port $PORT"
    ;;
  stop)
    [[ -f "$STATE/port-forward.pid" ]] && kill "$(<"$STATE/port-forward.pid")" 2>/dev/null || true
    rm -f "$STATE/port-forward.pid" "$STATE/port-forward.port"
    ;;
esac
