#!/usr/bin/env bash
# 사용법: overprovision.sh <kube-context> <scenario> <nodeSelector key=value> [runs]
# placeholder Pod(PriorityClass -10) 3개로 노드 1대분 여유를 잡아 둔 상태에서
# 실제 Pod 3개를 추가해 Ready까지 걸린 시간을 기록합니다.
# nodeSelector는 이 벤치마크 전용 노드 풀의 노드만 가리켜야 합니다(예: CAS agentpool=<bench-pool>,
# NAP karpenter.sh/nodepool=<bench-pool> 또는 그 NodePool template에만 둔 label). "노드 1대" 조건을 이 selector로 세므로
# 시작할 때 selector에 맞는 Ready 노드가 하나라도 있으면(다른 워크로드 노드, 이전 실행의 잔류 노드) 바로 실패합니다.
# TIMEOUT=900  Pod·placeholder Ready 대기 제한(초). 넘으면 실패로 종료합니다.
# placeholder_rescheduled_s: burst 전 placeholder Pod가 모두 선점·교체되고 새 placeholder 3개가 Ready가 된 시각
set -euo pipefail
USAGE="사용법: overprovision.sh <kube-context> <scenario> <nodeSelector key=value> [runs]"
CTX=${1:?$USAGE} SCENARIO=${2:?$USAGE} SELECTOR=${3:?$USAGE} RUNS=${4:-2} TIMEOUT=${TIMEOUT:-900}
HERE=$(cd "$(dirname "$0")" && pwd)
# 리소스를 바꾸기 전에 확인합니다. 0이나 정수가 아닌 값이면 측정 없이 성공으로 끝나지 않게 합니다.
[[ $RUNS =~ ^[1-9][0-9]*$ ]] || { echo "runs는 1 이상의 정수여야 합니다: ${RUNS}" >&2; echo "$USAGE" >&2; exit 2; }
# scenario는 CSV 첫 열에 그대로 들어가므로 다른 bench 스크립트와 같은 규칙으로 안전한 문자만 허용합니다.
if [[ ! $SCENARIO =~ ^[A-Za-z0-9._-]+$ || $SCENARIO == . || $SCENARIO == .. ]]; then
  echo "scenario는 영문자, 숫자, '.', '_', '-'만 쓸 수 있고 '.'이나 '..'일 수 없습니다: ${SCENARIO}" >&2; echo "$USAGE" >&2; exit 2
fi
# nodeSelector는 Kubernetes label 문법의 key=value 하나여야 합니다('=' 1개, key 필수, value는 비어도 됨).
# key: [DNS subdomain 접두사/]이름(63자 이하), value: 빈 값 또는 이름과 같은 규칙. 나눈 key·value를 patch와 노드 조회에 함께 씁니다.
split_selector() { # split_selector <key=value>: 성공하면 SEL_KEY, SEL_VAL을 설정
  local name='[A-Za-z0-9]([-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?' dns='[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?'
  local key=${1%%=*} val=${1#*=}
  [[ $1 == *=* && $val != *=* && $key =~ ^(($dns)(\.$dns)*/)?$name$ && $val =~ ^($name)?$ ]] || return 1
  local prefix=${key%/*}
  [[ $key != */* || ${#prefix} -le 253 ]] || return 1
  SEL_KEY=$key SEL_VAL=$val
}
split_selector "$SELECTOR" || {
  echo "nodeSelector는 Kubernetes label 문법의 key=value여야 합니다: ${SELECTOR}" >&2; echo "$USAGE" >&2; exit 2; }
k() { kubectl --context "$CTX" "$@"; }
log() { echo "[$(date -u +%T)] $SCENARIO $*" >&2; }
cleanup() { # best-effort: 실패해도 원래 종료 상태를 유지합니다.
  k -n bench scale deployment inflate --replicas 0 >/dev/null 2>&1 || log "cleanup: scale inflate failed"
  k -n bench delete deployment overprovisioning --ignore-not-found >/dev/null 2>&1 || log "cleanup: delete overprovisioning failed"
}
wait_ready3() { # wait_ready3 <deployment> <poll초>: readyReplicas가 3이 될 때까지. timeout은 측정 실패
  local deadline=$(( $(date +%s) + TIMEOUT ))
  until [[ $(k -n bench get deploy "$1" -o jsonpath='{.status.readyReplicas}') == 3 ]]; do
    (( $(date +%s) < deadline )) || { log "run $run: timeout waiting for $1 readyReplicas=3"; exit 1; }
    sleep "$2"
  done
}
placeholders_replaced() { # 선점 전 placeholder($old_uids)가 모두 사라지고 삭제 중이 아닌 placeholder 3개가 Ready면 성공
  local out uid
  out=$(k -n bench get pods -l app=overprovisioning -o go-template='{{range .items}}{{.metadata.uid}} {{if .metadata.deletionTimestamp}}deleting{{else}}{{range .status.conditions}}{{if eq .type "Ready"}}{{.status}}{{end}}{{end}}{{end}}{{"\n"}}{{end}}') || return 1
  for uid in $old_uids; do grep -q "^$uid " <<<"$out" && return 1; done
  [[ $(grep -c ' True$' <<<"$out" || true) -ge 3 ]]
}
single_ready_node() { # 삭제 중이 아닌 selector 노드가 Ready 상태와 관계없이 정확히 1대이고 그 노드가 Ready면 0, 아니면 1, 조회 실패는 2
  local out
  out=$(k get nodes -l "${SEL_KEY}=${SEL_VAL}" -o go-template='{{range .items}}{{if not .metadata.deletionTimestamp}}node:{{range .status.conditions}}{{if eq .type "Ready"}}{{.status}}{{end}}{{end}}{{"\n"}}{{end}}{{end}}') || return 2
  [[ $(grep -c '^node:' <<<"$out" || true) == 1 && $(grep -c '^node:True$' <<<"$out" || true) == 1 ]]
}
sel="[{\"op\":\"add\",\"path\":\"/spec/template/spec/nodeSelector\",\"value\":{\"${SEL_KEY}\":\"${SEL_VAL}\"}}]"

# placeholder를 배포하기 전에 selector가 전용 풀만 가리키고 그 풀이 비어 있는지 확인합니다. 조회 실패도 실패로 봅니다.
out=$(k get nodes -l "${SEL_KEY}=${SEL_VAL}" -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}') || {
  log "node 조회에 실패했습니다"; exit 1; }
n=$(grep -c True <<<"$out" || true)
if (( n > 0 )); then
  log "nodeSelector ${SEL_KEY}=${SEL_VAL}에 맞는 Ready 노드가 시작 전에 ${n}대 있습니다. 전용 벤치마크 풀만 가리키는 selector를 쓰고, 이전 실행의 노드가 축소된 뒤 다시 실행하세요."
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
for run in $(seq 1 "$RUNS"); do
  k -n bench scale deployment inflate --replicas 0 >/dev/null
  log "run $run: waiting for placeholders on a single node"
  k -n bench rollout status deployment/overprovisioning --timeout="${TIMEOUT}s" >/dev/null
  # 빈 여유 노드가 남아 있으면 선점 없이 바로 배치되므로, placeholder가 있는 노드 1대만 남을 때까지 기다립니다.
  # placeholder 3개가 노드 1대에 들어가지 않는 VM 크기면 이 조건을 만족할 수 없으므로 TIMEOUT 뒤 실패로 종료합니다.
  # NotReady 노드도 세어 정확히 1대이고 Ready일 때만 안정으로 봅니다. 세 번째 확인 뒤에는 기다리지 않고 burst로 넘어갑니다.
  stable=0 deadline=$(( $(date +%s) + TIMEOUT ))
  while :; do
    (( $(date +%s) < deadline )) || { log "run $run: timeout waiting for placeholders on a single node"; exit 1; }
    single_ready_node && rc=0 || rc=$?
    (( rc != 2 )) || { log "run $run: node 조회에 실패했습니다"; exit 1; }
    if (( rc == 0 )); then stable=$((stable + 1)); else stable=0; fi
    (( stable < 3 )) || break
    sleep 10
  done
  # readyReplicas는 선점 직후에도 이전 값 3으로 남을 수 있으므로 burst 전 placeholder UID를 기록해 교체 여부로 판단합니다.
  old_uids=$(k -n bench get pods -l app=overprovisioning -o jsonpath='{range .items[*]}{.metadata.uid}{"\n"}{end}')
  [[ -n $old_uids ]] || { log "run $run: no placeholder pods before burst"; exit 1; }
  # 안정 확인 뒤 상태가 바뀌지 않았는지 burst 직전에 다시 확인합니다.
  single_ready_node || { log "run $run: burst 직전 selector 노드가 Ready 1대가 아닙니다"; exit 1; }
  t0=$(date +%s)
  k -n bench scale deployment inflate --replicas 3 >/dev/null
  wait_ready3 inflate 1
  t1=$(date +%s)
  # 선점된 placeholder가 새 노드에서 다시 Running이 될 때까지(다음 burst를 받을 여유가 복구되는 시간)
  deadline=$(( $(date +%s) + TIMEOUT ))
  until placeholders_replaced; do
    (( $(date +%s) < deadline )) || { log "run $run: timeout waiting for placeholders to be replaced and Ready"; exit 1; }
    sleep 2
  done
  t2=$(date +%s)
  echo "$SCENARIO,$run,$((t1 - t0)),$((t2 - t0))"
done
