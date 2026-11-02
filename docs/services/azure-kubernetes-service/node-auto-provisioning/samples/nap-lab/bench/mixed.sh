#!/usr/bin/env bash
# 사용법: mixed.sh <kube-context> <scenario> <nodeSelector key=value> [runs]
#   BIG=4 MEM=6 SMALL=10  워크로드별 replica 수(0 이상, 합계 1 이상)
#   TIMEOUT=900           모든 Pod Ready를 기다릴 최대 시간(초). 넘으면 그 시점 상태를 기록
#   PRICES=prices.json    prices.py 출력. 노드 시간당 비용 계산에 사용
#                         (생략하면 results/prices-$AZURE_LOCATION.json)
#   OUT=<dir>             실행별 원본 스냅샷 저장 위치(기본 ./out). 같은 실행 디렉터리의 이전 산출물은 시작할 때 지웁니다.
# 각 실행은 selector에 맞는 node 객체가 0개가 될 때까지(최대 1800초) 기다린 뒤 시작합니다.
set -euo pipefail
USAGE="사용법: mixed.sh <kube-context> <scenario> <nodeSelector key=value> [runs]"
CTX=${1:?$USAGE} SCENARIO=${2:?$USAGE} SELECTOR=${3:?$USAGE} RUNS=${4:-1}
BIG=${BIG:-4} MEM=${MEM:-6} SMALL=${SMALL:-10} TIMEOUT=${TIMEOUT:-900} OUT=${OUT:-./out}
HERE=$(cd "$(dirname "$0")" && pwd)
source "$HERE/lib.sh"
# 리소스를 바꾸기 전에 확인합니다. 0이나 정수가 아닌 값이면 측정 없이 성공으로 끝나지 않게 합니다.
usage_exit() { echo "$USAGE" >&2; exit 2; }
RUNS=$(int_arg runs "$RUNS" 1) || usage_exit
BIG=$(int_arg BIG "$BIG" 0) || usage_exit
MEM=$(int_arg MEM "$MEM" 0) || usage_exit
SMALL=$(int_arg SMALL "$SMALL" 0) || usage_exit
TIMEOUT=$(int_arg TIMEOUT "$TIMEOUT" 1) || usage_exit
total=$((BIG + MEM + SMALL))
(( total > 0 )) || { echo "BIG·MEM·SMALL 합계는 1 이상이어야 합니다" >&2; usage_exit; }
check_scenario "$SCENARIO" || usage_exit
split_selector "$SELECTOR" || usage_exit
PRICES=${PRICES:-$HERE/../results/prices-${AZURE_LOCATION:?PRICES 또는 AZURE_LOCATION이 필요합니다}.json}
[[ -f $PRICES ]] || { echo "가격 파일이 없습니다: $PRICES (bench/prices.py로 생성)" >&2; exit 1; }
k() { kubectl --context "$CTX" --request-timeout="$KUBE_RT" "$@"; }
log() { echo "[$(date -u +%T)] $SCENARIO $*" >&2; }
ready_pods() { # 조회 실패는 0개가 아니라 nonzero로 반환합니다.
  local statuses
  statuses=$(k -n mixed get pods -l app=mix \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}') || return 1
  count_matching '^True$' <<<"$statuses"
}
all_ready() { local n; n=$(ready_pods) || return 1; [[ $n -ge $total ]]; }
no_node_objects() { # Ready 여부와 관계없이 selector node 객체가 0개면 성공. 조회 실패는 nonzero
  local out
  out=$(k get nodes -l "${SEL_KEY}=${SEL_VAL}" -o name) || return 1
  [[ -z ${out//[[:space:]]/} ]]
}
scale_zero() { # 모든 Deployment를 시도하고 하나라도 실패하면 nonzero
  local d rc=0
  for d in big mem small; do k -n mixed scale deployment "$d" --replicas 0 >/dev/null || rc=1; done
  return "$rc"
}
# 첫 리소스 변경 전에 등록해 중간 실패·중단에도 세 Deployment를 0으로 되돌립니다. 정리 실패가 원래 종료 상태를 덮지 않습니다.
trap 'scale_zero || log "cleanup failed"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

k apply -f "$HERE/../manifests/mixed.yaml" >/dev/null
# nodeSelector 전체를 교체합니다(strategic merge는 이전 키를 남김).
sel="[{\"op\":\"add\",\"path\":\"/spec/template/spec/nodeSelector\",\"value\":{\"${SEL_KEY}\":\"${SEL_VAL}\"}}]"
for d in big mem small; do k -n mixed patch deployment "$d" --type json -p "$sel" >/dev/null; done

for (( run = 1; run <= RUNS; run++ )); do
  dir="$OUT/$SCENARIO/run$run"; mkdir -p "$dir"
  rm -f "$dir"/{t0,pods.json,nodes.json,events.json}   # 이전 실행 스냅샷이 이번 t0와 섞이지 않게 합니다.
  # 이전 실행의 VM이 지워진 뒤 NotReady로 남은 node 객체까지 사라져야 다음 실행의 구성에 섞이지 않습니다.
  log "run $run: waiting for zero workload node objects"
  wait_until 1800 5 no_node_objects || { log "run $run: timeout waiting for zero workload node objects"; exit 1; }
  date -u +%Y-%m-%dT%H:%M:%SZ > "$dir/t0"
  k -n mixed scale deployment big --replicas "$BIG" >/dev/null
  k -n mixed scale deployment mem --replicas "$MEM" >/dev/null
  k -n mixed scale deployment small --replicas "$SMALL" >/dev/null
  # timeout이면 지연 없이 그 시점 상태를 기록합니다. 완료 여부는 analyze_mixed.py가 스냅샷으로 판단합니다.
  if wait_until "$TIMEOUT" 3 all_ready; then sleep 5; else log "run $run: timeout after ${TIMEOUT}s"; fi
  k -n mixed get pods -o json > "$dir/pods.json"
  n=$(ready_pods)
  log "run $run: ${n}/${total} pods ready"
  k get nodes -o json > "$dir/nodes.json"
  k get events -n mixed -o json > "$dir/events.json"
  # 생성되지 않은 Pod도 미완료로 보도록 기대 replica 수를 넘깁니다.
  python3 "$HERE/analyze_mixed.py" "$dir" "$SCENARIO" "$run" "${SEL_KEY}=${SEL_VAL}" "$PRICES" "$BIG" "$MEM" "$SMALL"
  scale_zero
done
