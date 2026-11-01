#!/usr/bin/env bash
# 사용법: bench.sh <kube-context> <scenario> <replicas> <runs> [nodeSelector key=value]
#   CPU=1            Pod당 CPU 요청
#   WAVES="5 5 5 5"  지정하면 replica를 여러 번에 나눠 늘림(WAVE_INTERVAL초 간격). 합계는 replicas와 같아야 함
#   OUT=<dir>        실행별 원본 스냅샷 저장 위치
#   SCALE_IN_COUNT="<cmd>"  남은 VM 수를 출력하는 명령. 0이 되는 시각을 축소 완료로 기록
#                    예) CAS: az vmss list-instances -g <MC_rg> -n <vmss> --query "length(@)" -o tsv
#                        NAP: kubectl get nodeclaims -l karpenter.sh/nodepool=bench-fixed --no-headers | wc -l
# 실행마다 시작 시각과 Pod·노드·NodeClaim·이벤트 스냅샷을 남기고 analyze.py로 단계별 시간을 계산합니다.
set -euo pipefail
USAGE="사용법: bench.sh <kube-context> <scenario> <replicas> <runs> [nodeSelector key=value]"
CTX=${1:?$USAGE} SCENARIO=${2:?$USAGE} REPLICAS=${3:?$USAGE} RUNS=${4:?$USAGE} SELECTOR=${5:-}
CPU=${CPU:-1} TIMEOUT=${TIMEOUT:-1800} WAVE_INTERVAL=${WAVE_INTERVAL:-30}
OUT=${OUT:-./out} HERE=$(cd "$(dirname "$0")" && pwd)
# WAVES 합계가 replicas와 다르면 측정 부하와 완료 조건이 어긋나므로 리소스를 바꾸기 전에 실패합니다.
if [[ -n ${WAVES:-} ]]; then
  sum=0
  for w in $WAVES; do
    [[ $w =~ ^[0-9]+$ ]] || { echo "WAVES는 정수 목록이어야 합니다: $WAVES" >&2; exit 1; }
    sum=$((sum + w))
  done
  [[ $sum == "$REPLICAS" ]] || { echo "WAVES 합계($sum)가 replicas($REPLICAS)와 다릅니다: $WAVES" >&2; exit 1; }
fi
k() { kubectl --context "$CTX" "$@"; }
log() { echo "[$(date -u +%T)] $SCENARIO $*" >&2; }
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

NODE_SEL=${SELECTOR:-kubernetes.azure.com/mode=user}
ready_nodes() { # 조회 실패는 0개가 아니라 nonzero로 반환합니다.
  local out
  out=$(k get nodes -l "$NODE_SEL" \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}') || return 1
  grep -c True <<<"$out" || true
}
ready_pods() {
  k -n bench get pods -l app=inflate \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' | grep -c True || true
}
wait_for() { # wait_for <desc> <predicate...>
  local desc=$1; shift; local start; start=$(date +%s)
  until "$@"; do
    (( $(date +%s) - start > TIMEOUT )) && { log "timeout: $desc"; return 1; }
    sleep 2
  done
}
no_ready_nodes() { local n; n=$(ready_nodes) || return 1; [[ $n -eq 0 ]]; }
pods_ready() { [[ $(ready_pods) -ge $REPLICAS ]]; }

k apply -f "$HERE/../manifests/inflate.yaml" >/dev/null
# 스냅샷 조회 실패나 중단으로 끝나도 inflate를 0으로 되돌려 Pod와 노드가 남지 않게 합니다.
# 정리 실패가 원래 종료 상태를 덮지 않습니다.
trap 'k -n bench scale deployment inflate --replicas 0 >/dev/null 2>&1 || log "cleanup failed"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
k -n bench patch deployment inflate --type strategic -p \
  "{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"pause\",\"resources\":{\"requests\":{\"cpu\":\"$CPU\",\"memory\":\"1Gi\"}}}]}}}}" >/dev/null
# nodeSelector 전체를 교체합니다(strategic merge는 이전 키를 남김).
if [[ -n $SELECTOR ]]; then
  k -n bench patch deployment inflate --type json -p \
    "[{\"op\":\"add\",\"path\":\"/spec/template/spec/nodeSelector\",\"value\":{\"${SELECTOR%%=*}\":\"${SELECTOR#*=}\"}}]" >/dev/null
fi

# 삭제·할당 해제된 VM의 node 객체는 NotReady로 남을 수 있으므로 Ready 워크로드 노드 0개를 시작 조건으로 씁니다.
baseline=no_ready_nodes

for run in $(seq 1 "$RUNS"); do
  dir="$OUT/$SCENARIO/run$run"; mkdir -p "$dir"
  rm -f "$dir/waves" "$dir/scale_in_start" "$dir/scale_in_end"   # 같은 OUT으로 다시 실행할 때 이전 산출물 제거
  log "run $run: waiting for baseline"
  wait_for baseline "$baseline"
  k -n bench delete events --all >/dev/null 2>&1 || true

  t0=$(now); echo "$t0" > "$dir/t0"
  if [[ -n ${WAVES:-} ]]; then
    total=0; : > "$dir/waves"
    for w in $WAVES; do
      total=$((total + w)); echo "$(now) $total" >> "$dir/waves"
      k -n bench scale deployment inflate --replicas "$total" >/dev/null
      if [[ $total -lt $REPLICAS ]]; then sleep "$WAVE_INTERVAL"; fi
    done
  else
    k -n bench scale deployment inflate --replicas "$REPLICAS" >/dev/null
  fi
  wait_for "pods ready" pods_ready || true
  log "run $run: pods ready"

  k -n bench get pods -o json > "$dir/pods.json"
  k get nodes -o json > "$dir/nodes.json"
  k get nodeclaims -o json > "$dir/nodeclaims.json" 2>/dev/null || echo '{"items":[]}' > "$dir/nodeclaims.json"
  k get events -A -o json > "$dir/events.json"

  now > "$dir/scale_in_start"
  k -n bench scale deployment inflate --replicas 0 >/dev/null
  # CAS는 VM 삭제 뒤에도 node 객체가 NotReady로 몇 분 남으므로 node 수가 아니라 VM 수로 완료를 판단합니다.
  # timeout이면 scale_in_end를 남기지 않아 analyze.py가 축소 시간을 빈 값으로 둡니다.
  if [[ -n ${SCALE_IN_COUNT:-} ]]; then
    # pipefail로 명령 안의 조회 실패(예: kubectl | wc -l)를 실패로 전파하고, 성공한 출력만 0과 비교합니다.
    vms_gone() { local out; out=$(bash -o pipefail -c "$SCALE_IN_COUNT" 2>/dev/null) || return 1; [[ $(tr -d ' \n' <<<"$out") == 0 ]]; }
    if wait_for "scale-in" vms_gone; then now > "$dir/scale_in_end"; fi
    wait_for "no ready nodes" no_ready_nodes || true
  elif wait_for "no ready nodes" no_ready_nodes; then
    now > "$dir/scale_in_end"
  fi
  log "run $run: scale-in done"
  python3 "$HERE/analyze.py" "$dir" "$SCENARIO" "$run" "$NODE_SEL"
done
