#!/usr/bin/env bash
# 사용법: mixed.sh <kube-context> <scenario> <nodeSelector key=value> [runs]
#   BIG=4 MEM=6 SMALL=10  워크로드별 replica 수
#   TIMEOUT=900           모든 Pod Ready를 기다릴 최대 시간(초). 넘으면 그 시점 상태를 기록
#   PRICES=prices.json    prices.py 출력. 노드 시간당 비용 계산에 사용
set -euo pipefail
CTX=$1 SCENARIO=$2 SELECTOR=$3 RUNS=${4:-1}
BIG=${BIG:-4} MEM=${MEM:-6} SMALL=${SMALL:-10} TIMEOUT=${TIMEOUT:-900} OUT=${OUT:-./out}
HERE=$(cd "$(dirname "$0")" && pwd)
k() { kubectl --context "$CTX" "$@"; }
log() { echo "[$(date -u +%T)] $SCENARIO $*" >&2; }
total=$((BIG + MEM + SMALL))
ready_pods() {
  k -n mixed get pods -l app=mix \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' | grep -c True || true
}
ready_nodes() {
  k get nodes -l "$SELECTOR" \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' | grep -c True || true
}

k apply -f "$HERE/../manifests/mixed.yaml" >/dev/null
# nodeSelector 전체를 교체합니다(strategic merge는 이전 키를 남김).
sel="[{\"op\":\"add\",\"path\":\"/spec/template/spec/nodeSelector\",\"value\":{\"${SELECTOR%%=*}\":\"${SELECTOR#*=}\"}}]"
for d in big mem small; do k -n mixed patch deployment $d --type json -p "$sel" >/dev/null; done

for run in $(seq 1 "$RUNS"); do
  dir="$OUT/$SCENARIO/run$run"; mkdir -p "$dir"
  log "run $run: waiting for zero ready workload nodes"
  until [[ $(ready_nodes) -eq 0 ]]; do sleep 5; done
  date -u +%Y-%m-%dT%H:%M:%SZ > "$dir/t0"
  k -n mixed scale deployment big --replicas "$BIG" >/dev/null
  k -n mixed scale deployment mem --replicas "$MEM" >/dev/null
  k -n mixed scale deployment small --replicas "$SMALL" >/dev/null
  start=$(date +%s)
  until [[ $(ready_pods) -ge $total ]] || (( $(date +%s) - start > TIMEOUT )); do sleep 3; done
  sleep 5
  log "run $run: $(ready_pods)/$total pods ready"
  k -n mixed get pods -o json > "$dir/pods.json"
  k get nodes -o json > "$dir/nodes.json"
  k get events -n mixed -o json > "$dir/events.json"
  python3 "$HERE/analyze_mixed.py" "$dir" "$SCENARIO" "$run" "$SELECTOR" "${PRICES:-$HERE/../results/prices-eastus2.json}"
  for d in big mem small; do k -n mixed scale deployment $d --replicas 0 >/dev/null; done
done
