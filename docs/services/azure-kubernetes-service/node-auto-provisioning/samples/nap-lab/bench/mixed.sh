#!/usr/bin/env bash
# 사용법: mixed.sh <kube-context> <scenario> <nodeSelector key=value> [runs]
#   BIG=4 MEM=6 SMALL=10  워크로드별 replica 수
#   TIMEOUT=900           모든 Pod Ready를 기다릴 최대 시간(초). 넘으면 그 시점 상태를 기록
#   PRICES=prices.json    prices.py 출력. 노드 시간당 비용 계산에 사용
#                         (생략하면 results/prices-$AZURE_LOCATION.json)
set -euo pipefail
USAGE="사용법: mixed.sh <kube-context> <scenario> <nodeSelector key=value> [runs]"
CTX=${1:?$USAGE} SCENARIO=${2:?$USAGE} SELECTOR=${3:?$USAGE} RUNS=${4:-1}
BIG=${BIG:-4} MEM=${MEM:-6} SMALL=${SMALL:-10} TIMEOUT=${TIMEOUT:-900} OUT=${OUT:-./out}
HERE=$(cd "$(dirname "$0")" && pwd)
PRICES=${PRICES:-$HERE/../results/prices-${AZURE_LOCATION:?PRICES 또는 AZURE_LOCATION이 필요합니다}.json}
[[ -f $PRICES ]] || { echo "가격 파일이 없습니다: $PRICES (bench/prices.py로 생성)" >&2; exit 1; }
k() { kubectl --context "$CTX" "$@"; }
log() { echo "[$(date -u +%T)] $SCENARIO $*" >&2; }
total=$((BIG + MEM + SMALL))
ready_pods() {
  k -n mixed get pods -l app=mix \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' | grep -c True || true
}
ready_nodes() { # 조회 실패는 0개가 아니라 nonzero로 반환합니다.
  local out
  out=$(k get nodes -l "$SELECTOR" \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}') || return 1
  grep -c True <<<"$out" || true
}
scale_zero() { for d in big mem small; do k -n mixed scale deployment $d --replicas 0 >/dev/null; done; }

k apply -f "$HERE/../manifests/mixed.yaml" >/dev/null
# nodeSelector 전체를 교체합니다(strategic merge는 이전 키를 남김).
sel="[{\"op\":\"add\",\"path\":\"/spec/template/spec/nodeSelector\",\"value\":{\"${SELECTOR%%=*}\":\"${SELECTOR#*=}\"}}]"
for d in big mem small; do k -n mixed patch deployment $d --type json -p "$sel" >/dev/null; done
# 중간 실패·중단에도 세 Deployment를 0으로 되돌립니다(best-effort).
trap 'scale_zero 2>/dev/null || log "cleanup failed"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for run in $(seq 1 "$RUNS"); do
  dir="$OUT/$SCENARIO/run$run"; mkdir -p "$dir"
  log "run $run: waiting for zero ready workload nodes"
  until n=$(ready_nodes) && [[ $n -eq 0 ]]; do sleep 5; done
  date -u +%Y-%m-%dT%H:%M:%SZ > "$dir/t0"
  k -n mixed scale deployment big --replicas "$BIG" >/dev/null
  k -n mixed scale deployment mem --replicas "$MEM" >/dev/null
  k -n mixed scale deployment small --replicas "$SMALL" >/dev/null
  start=$(date +%s)
  timed_out=0
  until [[ $(ready_pods) -ge $total ]]; do
    if (( $(date +%s) - start > TIMEOUT )); then timed_out=1; break; fi
    sleep 3
  done
  # timeout이면 지연 없이 그 시점 상태를 기록합니다.
  (( timed_out )) || sleep 5
  k -n mixed get pods -o json > "$dir/pods.json"
  log "run $run: $(ready_pods)/$total pods ready"
  k get nodes -o json > "$dir/nodes.json"
  k get events -n mixed -o json > "$dir/events.json"
  python3 "$HERE/analyze_mixed.py" "$dir" "$SCENARIO" "$run" "$SELECTOR" "$PRICES"
  scale_zero
done
