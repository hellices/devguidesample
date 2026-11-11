#!/usr/bin/env bash
# Usage: vm-query.sh start|stop|port. Opens (or repairs) this environment's local port-forward
# to the private VMSingle service, or prints the local port it uses.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"
STATE="$(state_dir)"
PORT="$(vm_local_port)"

# The recorded PID must still be the same process (start time) and our kubectl port-forward
# with exactly "<port>:8428" as an argument, not a reused PID.
is_our_forward() {
  local pid="$1" port="$2"
  [[ -f "$STATE/port-forward.started" ]] \
    && [[ "$(ps -p "$pid" -o lstart= 2>/dev/null)" == "$(<"$STATE/port-forward.started")" ]] \
    && ps -ww -p "$pid" -o command= 2>/dev/null | grep -qE "(^|/)kubectl .*port-forward .*(^| )$port:8428( |$)"
}

# Stops the recorded forward on the port it was started with, even if VM_LOCAL_PORT changed since.
stop_forward() {
  local pid port
  [[ -f "$STATE/port-forward.pid" ]] || return 0
  pid="$(<"$STATE/port-forward.pid")"
  port="$(cat "$STATE/port-forward.port" 2>/dev/null || printf '%s' "$PORT")"
  if is_our_forward "$pid" "$port"; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$STATE/port-forward.pid" "$STATE/port-forward.port" "$STATE/port-forward.started"
}

owned_forward() {
  [[ -f "$STATE/port-forward.pid" && -f "$STATE/port-forward.port" ]] \
    && [[ "$(<"$STATE/port-forward.port")" == "$PORT" ]] \
    && is_our_forward "$(<"$STATE/port-forward.pid")" "$PORT"
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
    # Unhealthy, or recorded on a previous port: never leave it running behind a new record.
    stop_forward
    if healthy; then
      die "port $PORT already serves another VictoriaMetrics; set VM_LOCAL_PORT for this environment"
    fi
    # Start kubectl itself in the background (not the kube function, which would fork a subshell)
    # so the recorded PID is the forward process that stop must terminate.
    kubectl --kubeconfig "$STATE/kubeconfig" port-forward -n eventhubs-observability svc/vmsingle-lab \
      "$PORT:8428" >"$STATE/port-forward.log" 2>&1 &
    pid=$!
    # Until readiness is confirmed, an interrupt must not leave an untracked forward behind.
    trap 'kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; rm -f "$STATE"/port-forward.{pid,port,started}' EXIT
    echo "$pid" >"$STATE/port-forward.pid"
    printf '%s\n' "$PORT" >"$STATE/port-forward.port"
    ps -p "$pid" -o lstart= >"$STATE/port-forward.started"
    for attempt in $(seq 1 20); do
      # A forward that exited (for example, it could not bind) is a failure even if another
      # listener answers on the port.
      if ! kill -0 "$pid" 2>/dev/null; then
        stop_forward
        die "VMSingle port-forward exited before becoming ready on port $PORT; see $STATE/port-forward.log"
      fi
      # Right after the fork the child may not have exec'd kubectl yet, so ownership is retried
      # together with health instead of failing on the first look.
      if owned_forward && healthy; then
        trap - EXIT
        exit 0
      fi
      if [[ "$attempt" -lt 20 ]]; then sleep 1; fi
    done
    stop_forward
    die "VMSingle port-forward did not become ready on port $PORT"
    ;;
  stop)
    stop_forward
    ;;
  *)
    die "usage: vm-query.sh start|stop|port"
    ;;
esac
