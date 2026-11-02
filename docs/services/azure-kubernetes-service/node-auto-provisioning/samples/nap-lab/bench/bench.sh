#!/usr/bin/env bash
# 사용법: bench.sh <kube-context> <scenario> <replicas> <runs> [nodeSelector key=value]
#   CPU=1            Pod당 CPU 요청(Kubernetes CPU 수량, 예: 1, 0.5, 500m)
#   TIMEOUT=1800     시작 조건·Pod Ready·축소를 각각 기다릴 최대 시간(초)
#   WAVES="5 5 5 5"  지정하면 replica를 여러 번에 나눠 늘림(WAVE_INTERVAL초 간격, 기본 30). 합계는 replicas와 같아야 함
#   OUT=<dir>        실행별 원본 스냅샷 저장 위치(기본 ./out). 같은 실행 디렉터리의 이전 산출물은 시작할 때 지웁니다.
#   SCALE_IN_COUNT="<cmd>"  남은 VM 수를 출력하는 명령. 0이 되는 시각을 축소 완료로 기록
#                    bench.sh와 같은 클러스터를 조회해야 합니다. 명령에서 "$CTX"(첫 인수)를 쓸 수 있습니다.
#                    bash -o pipefail로 실행하고 300초 안에 끝나지 않거나 정수가 아닌 값을 출력하면 미완료로 봅니다.
#                    timeout이면 다음 실행과 겹치지 않도록 실패로 종료하고, 각 실행 시작 전에도 0을 확인합니다.
#                    예) CAS: az vmss list-instances -g <MC_rg> -n <vmss> --query "length(@)" -o tsv
#                        NAP: kubectl --context "$CTX" --request-timeout=60s get nodeclaims -l karpenter.sh/nodepool=bench-fixed -o name | wc -l
# 실행마다 시작 시각과 Pod·노드·NodeClaim·NodePool·이벤트 스냅샷을 남기고 analyze.py로 단계별 시간을 계산합니다.
set -euo pipefail
USAGE="사용법: bench.sh <kube-context> <scenario> <replicas> <runs> [nodeSelector key=value]"
CTX=${1:?$USAGE} SCENARIO=${2:?$USAGE} REPLICAS=${3:?$USAGE} RUNS=${4:?$USAGE} SELECTOR=${5:-}
export CTX   # SCALE_IN_COUNT 명령이 같은 context를 "$CTX"로 쓸 수 있게 합니다.
CPU=${CPU:-1} TIMEOUT=${TIMEOUT:-1800} WAVE_INTERVAL=${WAVE_INTERVAL:-30}
OUT=${OUT:-./out} HERE=$(cd "$(dirname "$0")" && pwd)
source "$HERE/lib.sh"
# 잘못된 입력으로 patch만 적용되고 측정이 없거나 엉뚱한 노드를 세지 않도록 리소스를 바꾸기 전에 모두 확인합니다.
usage_exit() { echo "$USAGE" >&2; exit 2; }
REPLICAS=$(int_arg replicas "$REPLICAS" 1) || usage_exit
RUNS=$(int_arg runs "$RUNS" 1) || usage_exit
TIMEOUT=$(int_arg TIMEOUT "$TIMEOUT" 1) || usage_exit
WAVE_INTERVAL=$(int_arg WAVE_INTERVAL "$WAVE_INTERVAL" 0) || usage_exit
check_scenario "$SCENARIO" || usage_exit
# CPU는 patch JSON에 그대로 들어가므로 0보다 큰 CPU 수량 형식만 받습니다.
[[ $CPU =~ ^([0-9]+m|[0-9]+(\.[0-9]+)?)$ && $CPU =~ [1-9] ]] || { echo "CPU는 0보다 큰 CPU 수량(예: 1, 0.5, 500m)이어야 합니다: ${CPU}" >&2; usage_exit; }
if [[ -n $SELECTOR ]]; then split_selector "$SELECTOR" || usage_exit; fi
# WAVES 합계가 replicas와 다르면 측정 부하와 완료 조건이 어긋나므로 리소스를 바꾸기 전에 실패합니다.
wave_list=()
if [[ -n ${WAVES:-} ]]; then
  sum=0
  for w in $WAVES; do
    w=$(int_arg "WAVES 항목" "$w" 1) || usage_exit
    wave_list+=("$w"); sum=$((sum + w))
  done
  (( sum == REPLICAS )) || { echo "WAVES 합계(${sum})가 replicas(${REPLICAS})와 다릅니다: ${WAVES}" >&2; usage_exit; }
fi
k() { kubectl --context "$CTX" --request-timeout="$KUBE_RT" "$@"; }
log() { echo "[$(date -u +%T)] $SCENARIO $*" >&2; }
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

NODE_SEL=kubernetes.azure.com/mode=user
[[ -z $SELECTOR ]] || NODE_SEL="${SEL_KEY}=${SEL_VAL}"
ready_nodes() { # 조회 실패는 0개가 아니라 nonzero로 반환합니다.
  local out
  out=$(k get nodes -l "$NODE_SEL" \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}') || return 1
  count_matching '^True$' <<<"$out"
}
ready_pods() { # 삭제 중(deletionTimestamp)인 이전 실행 Pod는 세지 않습니다. 조회 실패는 nonzero
  local out
  out=$(k -n bench get pods -l app=inflate -o go-template='{{range .items}}{{if not .metadata.deletionTimestamp}}{{range .status.conditions}}{{if eq .type "Ready"}}{{.status}}{{"\n"}}{{end}}{{end}}{{end}}{{end}}') || return 1
  count_matching '^True$' <<<"$out"
}
snap_crd() { # snap_crd <resource> <file>: CRD가 없는 클러스터(CAS)만 빈 목록으로 저장. 다른 조회 실패는 nonzero
  local err
  err=$(k get "$1" -o json 2>&1 >"$2") && return 0
  grep -q "the server doesn't have a resource type" <<<"$err" || { echo "$err" >&2; return 1; }
  echo '{"items":[]}' > "$2"
}
wait_for() { # wait_for <desc> <predicate...>: TIMEOUT초 안에 성립하지 않으면 로그를 남기고 1
  local desc=$1; shift
  wait_until "$TIMEOUT" 2 "$@" && return 0
  log "timeout: $desc"; return 1
}
no_ready_nodes() { local n; n=$(ready_nodes) || return 1; [[ $n -eq 0 ]]; }
pods_ready() { local n; n=$(ready_pods) || return 1; [[ $n -ge $REPLICAS ]]; }
# SCALE_IN_COUNT를 pipefail로 실행해 명령 안의 조회 실패(예: kubectl | wc -l)도 실패로 보고, 성공한 정수 출력만 0과 비교합니다.
vms_gone() {
  local out
  out=$(bounded 300 bash -o pipefail -c "$SCALE_IN_COUNT") || return 1
  # 앞뒤 공백만 허용합니다. "0 0"이나 두 줄의 0처럼 정수 하나가 아닌 출력은 실패로 봅니다.
  [[ $out =~ ^[[:space:]]*([0-9]+)[[:space:]]*$ ]] || { log "SCALE_IN_COUNT 출력이 정수 하나가 아닙니다: ${out}"; return 1; }
  out=${BASH_REMATCH[1]}
  (( 10#$out == 0 ))
}
# 삭제·할당 해제된 VM의 node 객체는 NotReady로 남을 수 있으므로 Ready 워크로드 노드 0개를 시작 조건으로 씁니다.
# SCALE_IN_COUNT가 있으면 이전 실행의 VM이 모두 제거됐는지도 함께 확인합니다.
baseline() { no_ready_nodes || return 1; [[ -z ${SCALE_IN_COUNT:-} ]] || vms_gone; }

# 적용 도중이나 스냅샷 조회 실패·중단으로 끝나도 inflate를 0으로 되돌려 Pod와 노드가 남지 않게 합니다.
# 첫 변경 명령보다 먼저 등록하며, 정리 실패가 원래 종료 상태를 덮지 않습니다.
trap 'k -n bench scale deployment inflate --replicas 0 >/dev/null || log "cleanup failed"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
k apply -f "$HERE/../manifests/inflate.yaml" >/dev/null
k -n bench patch deployment inflate --type strategic -p \
  "{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"pause\",\"resources\":{\"requests\":{\"cpu\":\"$CPU\",\"memory\":\"1Gi\"}}}]}}}}" >/dev/null
# nodeSelector 전체를 교체합니다(strategic merge는 이전 키를 남김).
# 생략하면 이전 실행에서 남은 nodeSelector를 지웁니다(apply는 매니페스트에 없는 필드를 지우지 않음).
if [[ -n $SELECTOR ]]; then
  k -n bench patch deployment inflate --type json -p \
    "[{\"op\":\"add\",\"path\":\"/spec/template/spec/nodeSelector\",\"value\":{\"${SEL_KEY}\":\"${SEL_VAL}\"}}]" >/dev/null
else
  k -n bench patch deployment inflate --type merge -p '{"spec":{"template":{"spec":{"nodeSelector":null}}}}' >/dev/null
fi

for (( run = 1; run <= RUNS; run++ )); do
  dir="$OUT/$SCENARIO/run$run"; mkdir -p "$dir"
  # 같은 OUT으로 다시 실행할 때 이전 실행의 스냅샷이 이번 t0와 섞이지 않도록 먼저 지웁니다.
  rm -f "$dir"/{t0,replicas,waves,pods.json,nodes.json,nodeclaims.json,nodepools.json,events.json,scale_in_start,scale_in_end}
  log "run $run: waiting for baseline"
  wait_for baseline baseline || exit 1
  # 분석은 t0 이후 이벤트만 쓰므로 삭제에 실패해도 계속하되 경고를 남깁니다.
  k -n bench delete events --all --wait=false >/dev/null || log "WARNING: bench 이벤트 삭제 실패(이전 이벤트는 t0 기준으로 제외)"

  t0=$(now); echo "$t0" > "$dir/t0"
  echo "$REPLICAS" > "$dir/replicas"   # analyze.py·fallback.py가 Ready Pod 수를 요청 replica 수와 비교합니다.
  if (( ${#wave_list[@]} )); then
    total=0; : > "$dir/waves"
    for w in "${wave_list[@]}"; do
      total=$((total + w)); echo "$(now) $total" >> "$dir/waves"
      k -n bench scale deployment inflate --replicas "$total" >/dev/null
      if (( total < REPLICAS )); then sleep "$WAVE_INTERVAL"; fi
    done
  else
    k -n bench scale deployment inflate --replicas "$REPLICAS" >/dev/null
  fi
  # timeout이어도 그 시점 스냅샷을 남기며, analyze.py가 Ready Pod가 요청 수보다 적으면 all_pods_ready_s를 빈 값으로 둡니다.
  if wait_for "pods ready" pods_ready; then log "run $run: pods ready"; fi

  k -n bench get pods -o json > "$dir/pods.json"
  k get nodes -o json > "$dir/nodes.json"
  snap_crd nodeclaims "$dir/nodeclaims.json"
  snap_crd nodepools.karpenter.sh "$dir/nodepools.json"
  k get events -A -o json > "$dir/events.json"

  now > "$dir/scale_in_start"
  k -n bench scale deployment inflate --replicas 0 >/dev/null
  # CAS는 VM 삭제 뒤에도 node 객체가 NotReady로 몇 분 남으므로 node 수가 아니라 VM 수로 완료를 판단합니다.
  # timeout이면 scale_in_end를 남기지 않아 analyze.py가 축소 시간을 빈 값으로 둡니다.
  vms_left=0
  if [[ -n ${SCALE_IN_COUNT:-} ]]; then
    if wait_for "scale-in" vms_gone; then now > "$dir/scale_in_end"; else vms_left=1; fi
    wait_for "no ready nodes" no_ready_nodes || true
  elif wait_for "no ready nodes" no_ready_nodes; then
    now > "$dir/scale_in_end"
  fi
  log "run $run: scale-in done"
  python3 "$HERE/analyze.py" "$dir" "$SCENARIO" "$run" "$NODE_SEL"
  # VM이 남은 채 다음 실행을 시작하면 결과가 섞이므로 이번 행만 남기고 실패로 종료합니다.
  if (( vms_left )); then log "run $run: VMs remain after ${TIMEOUT}s scale-in timeout; stopping"; exit 1; fi
done
