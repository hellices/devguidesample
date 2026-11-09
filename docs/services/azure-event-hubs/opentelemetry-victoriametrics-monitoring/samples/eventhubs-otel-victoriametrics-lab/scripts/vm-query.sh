#!/usr/bin/env bash
# Usage: vm-query.sh start|stop|port. Opens (or repairs) this environment's local port-forward
# to the private VMSingle service, or prints the local port it uses.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"
STATE="$(state_dir)"
PORT="$(vm_local_port)"

# The recorded PID must still be our kubectl port-forward for this port, not a reused PID.
is_our_forward() {
  local pid="$1"
  ps -p "$pid" -o command= 2>/dev/null | grep -q "kubectl.*port-forward.*$PORT:8428"
}

stop_forward() {
  local pid
  [[ -f "$STATE/port-forward.pid" ]] || return 0
  pid="$(<"$STATE/port-forward.pid")"
  if is_our_forward "$pid"; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$STATE/port-forward.pid" "$STATE/port-forward.port"
}

owned_forward() {
  [[ -f "$STATE/port-forward.pid" && -f "$STATE/port-forward.port" ]] \
    && [[ "$(<"$STATE/port-forward.port")" == "$PORT" ]] \
    && is_our_forward "$(<"$STATE/port-forward.pid")"
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
      stop_forward
    elif healthy; then
      die "port $PORT already serves another VictoriaMetrics; set VM_LOCAL_PORT for this environment"
    fi
    # Start kubectl itself in the background (not the kube function, which would fork a subshell)
    # so the recorded PID is the forward process that stop must terminate.
    kubectl --kubeconfig "$STATE/kubeconfig" port-forward -n eventhubs-observability svc/vmsingle-lab \
      "$PORT:8428" >"$STATE/port-forward.log" 2>&1 &
    echo $! >"$STATE/port-forward.pid"
    printf '%s\n' "$PORT" >"$STATE/port-forward.port"
    for _ in $(seq 1 20); do
      healthy && exit 0
      sleep 1
    done
    die "VMSingle port-forward did not become ready on port $PORT"
    ;;
  stop)
    stop_forward
    ;;
  *)
    die "usage: vm-query.sh start|stop|port"
    ;;
esac
