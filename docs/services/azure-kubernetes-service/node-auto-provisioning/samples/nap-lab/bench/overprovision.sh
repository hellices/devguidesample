#!/usr/bin/env bash
# 사용법: overprovision.sh <kube-context> <scenario> <nodeSelector key=value> [runs]
# placeholder Pod(PriorityClass -10) 3개로 노드 1대분 여유를 잡아 둔 상태에서
# 실제 Pod 3개를 추가해 Ready까지 걸린 시간을 기록합니다.
# nodeSelector는 이 벤치마크 전용 노드 풀의 노드만 가리켜야 합니다(예: CAS agentpool=<bench-pool>,
# NAP karpenter.sh/nodepool=<bench-pool> 또는 그 NodePool template에만 둔 label). "노드 1대" 조건을 이 selector로 세므로
# 시작할 때 selector에 맞는 노드가 상태와 관계없이 하나라도 있으면(다른 워크로드 노드, 이전 실행의 잔류 노드) 바로 실패합니다.
# TIMEOUT=900  placeholder 배치·노드 1대 안정·Pod Ready를 각각 기다릴 최대 시간(초). placeholder 복구는 burst부터 TIMEOUT×2. 넘으면 실패로 종료합니다.
# pods_ready_s: burst 뒤 inflate Deployment가 이번 scale을 반영하고 readyReplicas 3이 된 시각
# placeholder_rescheduled_s: burst 전 placeholder Pod가 모두 선점·교체되고 새 placeholder 3개가 Ready가 된 시각
set -euo pipefail
USAGE="사용법: overprovision.sh <kube-context> <scenario> <nodeSelector key=value> [runs]"
CTX=${1:?$USAGE} SCENARIO=${2:?$USAGE} SELECTOR=${3:?$USAGE} RUNS=${4:-2} TIMEOUT=${TIMEOUT:-900}
HERE=$(cd "$(dirname "$0")" && pwd)
source "$HERE/lib.sh"
# 리소스를 바꾸기 전에 확인합니다. 0이나 정수가 아닌 값이면 측정 없이 성공으로 끝나지 않게 합니다.
usage_exit() { echo "$USAGE" >&2; exit 2; }
RUNS=$(int_arg runs "$RUNS" 1) || usage_exit
TIMEOUT=$(int_arg TIMEOUT "$TIMEOUT" 1) || usage_exit
check_scenario "$SCENARIO" || usage_exit
split_selector "$SELECTOR" || usage_exit
k() { kubectl --context "$CTX" --request-timeout="$KUBE_RT" "$@"; }
log() { echo "[$(date -u +%T)] $SCENARIO $*" >&2; }
cleanup() { # best-effort: 실패해도 원래 종료 상태를 유지합니다.
  k -n bench scale deployment inflate --replicas 0 >/dev/null || log "cleanup: scale inflate failed"
  k -n bench delete deployment overprovisioning --ignore-not-found --wait=false >/dev/null || log "cleanup: delete overprovisioning failed"
}
inflate_ready() { # controller가 이번 scale(generation)을 반영했고 readyReplicas가 3이면 성공. 조회 실패는 nonzero
  local s gen obs ready
  s=$(k -n bench get deploy inflate -o jsonpath='{.metadata.generation} {.status.observedGeneration} {.status.readyReplicas}') || return 1
  read -r gen obs ready <<<"$s"
  [[ -n $gen && $obs == "$gen" && ${ready:-0} == 3 ]]
}
placeholders_replaced() { # 선점 전 placeholder($old_uids)가 모두 사라지고 삭제 중이 아닌 placeholder 3개가 Ready면 성공
  local out uid n
  out=$(k -n bench get pods -l app=overprovisioning -o go-template='{{range .items}}{{.metadata.uid}} {{if .metadata.deletionTimestamp}}deleting{{else}}{{range .status.conditions}}{{if eq .type "Ready"}}{{.status}}{{end}}{{end}}{{end}}{{"\n"}}{{end}}') || return 1
  for uid in $old_uids; do grep -q "^$uid " <<<"$out" && return 1; done
  n=$(count_matching ' True$' <<<"$out") || return 1
  (( n >= 3 ))
}
single_ready_node() { # 삭제 중이 아닌 selector 노드가 Ready 상태와 관계없이 정확히 1대이고 그 노드가 Ready면 0, 아니면 1, 조회 실패는 2
  local out all ready
  out=$(k get nodes -l "${SEL_KEY}=${SEL_VAL}" -o go-template='{{range .items}}{{if not .metadata.deletionTimestamp}}node:{{range .status.conditions}}{{if eq .type "Ready"}}{{.status}}{{end}}{{end}}{{"\n"}}{{end}}{{end}}') || return 2
  all=$(count_matching '^node:' <<<"$out") || return 2
  ready=$(count_matching '^node:True$' <<<"$out") || return 2
  [[ $all == 1 && $ready == 1 ]]
}
sel="[{\"op\":\"add\",\"path\":\"/spec/template/spec/nodeSelector\",\"value\":{\"${SEL_KEY}\":\"${SEL_VAL}\"}}]"

# placeholder를 배포하기 전에 selector가 전용 풀만 가리키고 그 풀이 비어 있는지 확인합니다. 조회 실패도 실패로 봅니다.
# NotReady 노드도 나중에 Ready로 돌아오면 새 노드 없이 측정이 진행되므로, 삭제 중이 아닌 노드는 상태와 관계없이 셉니다.
out=$(k get nodes -l "${SEL_KEY}=${SEL_VAL}" -o go-template='{{range .items}}{{if not .metadata.deletionTimestamp}}node:{{range .status.conditions}}{{if eq .type "Ready"}}{{.status}}{{end}}{{end}}{{"\n"}}{{end}}{{end}}') || {
  log "node 조회에 실패했습니다"; exit 1; }
n=$(count_matching '^node:' <<<"$out")
if (( n > 0 )); then
  log "nodeSelector ${SEL_KEY}=${SEL_VAL}에 맞는 노드가 시작 전에 ${n}대(Ready $(count_matching '^node:True$' <<<"$out")대) 있습니다. 전용 벤치마크 풀만 가리키는 selector를 쓰고, 이전 실행의 노드와 node 객체가 정리된 뒤 다시 실행하세요."
  exit 1
fi

# 첫 리소스 변경 전에 등록해 apply·patch 부분 실패도 정리합니다.
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
k apply -f "$HERE/../manifests/inflate.yaml" >/dev/null
k apply -f "$HERE/../manifests/overprovisioning.yaml" >/dev/null
k -n bench patch deployment overprovisioning --type json -p "$sel" >/dev/null
k -n bench patch deployment inflate --type json -p "$sel" >/dev/null
k -n bench patch deployment inflate --type strategic \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"pause","resources":{"requests":{"cpu":"1","memory":"1Gi"}}}]}}}}' >/dev/null

echo "scenario,run,pods_ready_s,placeholder_rescheduled_s"
for (( run = 1; run <= RUNS; run++ )); do
  k -n bench scale deployment inflate --replicas 0 >/dev/null
  log "run $run: waiting for placeholders on a single node"
  # rollout status는 자체 --timeout까지 watch하므로 요청 제한을 그보다 길게 둡니다.
  kubectl --context "$CTX" --request-timeout="$((TIMEOUT + 60))s" -n bench rollout status deployment/overprovisioning \
    --timeout="${TIMEOUT}s" >/dev/null
  # 빈 여유 노드가 남아 있으면 선점 없이 바로 배치되므로, placeholder가 있는 노드 1대만 남을 때까지 기다립니다.
  # placeholder 3개가 노드 1대에 들어가지 않는 VM 크기면 이 조건을 만족할 수 없으므로 TIMEOUT 뒤 실패로 종료합니다.
  # NotReady 노드도 세어 정확히 1대이고 Ready일 때만 안정으로 봅니다. 10초 간격으로 세 번 연속 성립하면 burst로 넘어가며,
  # 마감 이후에 끝난 확인은 성립해도 timeout으로 봅니다.
  stable=0 deadline=$(( $(date +%s) + TIMEOUT ))
  while :; do
    single_ready_node && rc=0 || rc=$?
    (( rc != 2 )) || { log "run $run: node 조회에 실패했습니다"; exit 1; }
    if (( rc == 0 )); then stable=$((stable + 1)); else stable=0; fi
    left=$(( deadline - $(date +%s) ))
    (( left > 0 )) || { log "run $run: timeout waiting for placeholders on a single node"; exit 1; }
    (( stable < 3 )) || break
    sleep "$(( left < 10 ? left : 10 ))"
  done
  # readyReplicas는 선점 직후에도 이전 값 3으로 남을 수 있으므로 burst 전 placeholder UID를 기록해 교체 여부로 판단합니다.
  # 삭제 중이 아니고 Ready인 placeholder가 정확히 3개일 때 그 UID만 기록합니다(Pending 교체 Pod는 선점 대상이 아님).
  old_uids=$(k -n bench get pods -l app=overprovisioning -o go-template='{{range .items}}{{if not .metadata.deletionTimestamp}}{{$uid := .metadata.uid}}{{range .status.conditions}}{{if and (eq .type "Ready") (eq .status "True")}}{{$uid}}{{"\n"}}{{end}}{{end}}{{end}}{{end}}')
  n=$(count_matching . <<<"$old_uids")
  (( n == 3 )) || { log "run $run: burst 직전 Ready placeholder가 ${n}개입니다(3개 필요)"; exit 1; }
  # 안정 확인 뒤 상태가 바뀌지 않았는지 burst 직전에 다시 확인합니다.
  single_ready_node || { log "run $run: burst 직전 selector 노드가 Ready 1대가 아닙니다"; exit 1; }
  t0=$(date +%s)
  k -n bench scale deployment inflate --replicas 3 >/dev/null
  # 두 조건을 한 polling loop에서 따로 확인해, 각각 처음 성립한 시각을 t1·t2로 남깁니다.
  # placeholder 복구(선점된 placeholder가 새 노드에서 다시 Ready, 다음 burst를 받을 여유 복구)가 inflate보다 먼저 끝나도
  # 실제 시각을 잃지 않습니다. inflate는 burst부터 TIMEOUT, placeholder는 burst부터 TIMEOUT×2까지 기다립니다.
  t1="" t2=""
  while [[ -z $t1 || -z $t2 ]]; do
    now=$(date +%s)
    if [[ -z $t1 ]]; then
      if inflate_ready; then t1=$(date +%s); elif (( now - t0 >= TIMEOUT )); then
        log "run $run: timeout waiting for inflate readyReplicas=3"; exit 1; fi
    fi
    if [[ -z $t2 ]]; then
      if placeholders_replaced; then t2=$(date +%s); elif (( now - t0 >= 2 * TIMEOUT )); then
        log "run $run: timeout waiting for placeholders to be replaced and Ready"; exit 1; fi
    fi
    [[ -n $t1 && -n $t2 ]] || sleep 1
  done
  echo "$SCENARIO,$run,$((t1 - t0)),$((t2 - t0))"
done
