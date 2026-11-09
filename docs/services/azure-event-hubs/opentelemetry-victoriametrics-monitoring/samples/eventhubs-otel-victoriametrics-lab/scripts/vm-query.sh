#!/usr/bin/env bash
# Usage: vm-query.sh start|stop. Opens a local port-forward to the private VMSingle service.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"
STATE="$(state_dir)"
PORT="${VM_LOCAL_PORT:-18428}"
case "${1:-start}" in
  start)
    if [[ -f "$STATE/port-forward.pid" ]] && kill -0 "$(<"$STATE/port-forward.pid")" 2>/dev/null; then
      exit 0
    fi
    kube port-forward -n eventhubs-observability svc/vmsingle-lab "$PORT:8428" >"$STATE/port-forward.log" 2>&1 &
    echo $! >"$STATE/port-forward.pid"
    for _ in $(seq 1 20); do
      curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && exit 0
      sleep 1
    done
    die "VMSingle port-forward did not become ready"
    ;;
  stop)
    [[ -f "$STATE/port-forward.pid" ]] && kill "$(<"$STATE/port-forward.pid")" 2>/dev/null || true
    rm -f "$STATE/port-forward.pid"
    ;;
esac
