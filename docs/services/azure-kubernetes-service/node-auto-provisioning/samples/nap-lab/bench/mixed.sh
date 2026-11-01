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
# 리소스를 바꾸기 전에 확인합니다. 0이나 정수가 아닌 값이면 측정 없이 성공으로 끝나지 않게 합니다.
[[ $RUNS =~ ^[1-9][0-9]*$ ]] || { echo "runs는 1 이상의 정수여야 합니다: ${RUNS}" >&2; echo "$USAGE" >&2; exit 2; }
# scenario는 CSV 첫 열에 그대로 들어가므로 열·행을 깨는 문자를 막습니다.
if [[ $SCENARIO == *[$',\r\n"']* ]]; then
  echo "scenario에 쉼표, CR, LF, 큰따옴표를 쓸 수 없습니다: ${SCENARIO}" >&2; echo "$USAGE" >&2; exit 2
fi
PRICES=${PRICES:-$HERE/../results/prices-${AZURE_LOCATION:?PRICES 또는 AZURE_LOCATION이 필요합니다}.json}
[[ -f $PRICES ]] || { echo "가격 파일이 없습니다: $PRICES (bench/prices.py로 생성)" >&2; exit 1; }
k() { kubectl --context "$CTX" "$@"; }
log() { echo "[$(date -u +%T)] $SCENARIO $*" >&2; }
total=$((BIG + MEM + SMALL))
ready_pods() {
  k -n mixed get pods -l app=mix \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' | grep -c True || true
}
node_objects() { # Ready 여부와 관계없는 node 객체 수. 조회 실패는 0개가 아니라 nonzero로 반환합니다.
  local out
  out=$(k get nodes -l "$SELECTOR" -o name) || return 1
  grep -c . <<<"$out" || true
}
scale_zero() { # 모든 Deployment를 시도하고 하나라도 실패하면 nonzero
  local d rc=0
  for d in big mem small; do k -n mixed scale deployment $d --replicas 0 >/dev/null || rc=1; done
  return "$rc"
}
# 첫 리소스 변경 전에 등록해 중간 실패·중단에도 세 Deployment를 0으로 되돌립니다(best-effort).
trap 'scale_zero 2>/dev/null || log "cleanup failed"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

k apply -f "$HERE/../manifests/mixed.yaml" >/dev/null
# nodeSelector 전체를 교체합니다(strategic merge는 이전 키를 남김).
sel="[{\"op\":\"add\",\"path\":\"/spec/template/spec/nodeSelector\",\"value\":{\"${SELECTOR%%=*}\":\"${SELECTOR#*=}\"}}]"
for d in big mem small; do k -n mixed patch deployment $d --type json -p "$sel" >/dev/null; done

for run in $(seq 1 "$RUNS"); do
  dir="$OUT/$SCENARIO/run$run"; mkdir -p "$dir"
  # 이전 실행의 VM이 지워진 뒤 NotReady로 남은 node 객체까지 사라져야 다음 실행의 구성에 섞이지 않습니다.
  log "run $run: waiting for zero workload node objects"
  wait_start=$(date +%s)
  until n=$(node_objects) && [[ $n -eq 0 ]]; do
    (( $(date +%s) - wait_start <= 1800 )) || { log "run $run: timeout waiting for zero workload node objects"; exit 1; }
    sleep 5
  done
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
  # 생성되지 않은 Pod도 미완료로 보도록 기대 replica 수를 넘깁니다.
  python3 "$HERE/analyze_mixed.py" "$dir" "$SCENARIO" "$run" "$SELECTOR" "$PRICES" "$BIG" "$MEM" "$SMALL"
  scale_zero
done
