#!/usr/bin/env bash
# Path 1 리허설: 모든 풀의 CAS 비활성화 → NAP 활성화 → 고정 user pool을 단계적으로 축소 → 풀 삭제
#   AZURE_RESOURCE_GROUP, CAS_CLUSTER_NAME  필수. kube context 이름은 클러스터 이름과 같습니다(CTX로 변경).
#   POOL=user  축소·삭제할 고정 풀
set -euo pipefail
RG=${AZURE_RESOURCE_GROUP:?AZURE_RESOURCE_GROUP이 필요합니다}
CLUSTER=${CAS_CLUSTER_NAME:?CAS_CLUSTER_NAME이 필요합니다}
POOL=${POOL:-user} CTX=${CTX:-$CLUSTER}
k() { kubectl --context "$CTX" "$@"; }
log() { echo "[$(date -u +%T)] $*"; }
pool_count() { az aks nodepool show -g "$RG" --cluster-name "$CLUSTER" -n "$POOL" --query count -o tsv; }
wait_web_ready() { # 새 revision의 replica가 모두 Ready·Available이고 전체 Pod 수가 spec과 같을 때까지(15분 제한).
  # 일부 Pod 누락이나 이전 revision Pod(status.replicas > spec.replicas)가 남은 상태로 진행하지 않습니다.
  local deadline=$(( $(date +%s) + 900 )) s gen obs want total updated ready avail
  while :; do
    s=$(k -n migrate get deploy web -o jsonpath='{.metadata.generation},{.status.observedGeneration},{.spec.replicas},{.status.replicas},{.status.updatedReplicas},{.status.readyReplicas},{.status.availableReplicas}') || s=""
    IFS=, read -r gen obs want total updated ready avail <<<"$s"
    if [[ -n $want && $obs == "$gen" && ${total:-0} == "$want" && ${updated:-0} == "$want" && ${ready:-0} == "$want" && ${avail:-0} == "$want" ]]; then return 0; fi
    (( $(date +%s) < deadline )) || { log "timeout: web not ready (generation,observed,spec,replicas,updated,ready,available=$s)"; return 1; }
    sleep 2
  done
}

log "deploy probe"; k apply -f "$(dirname "$0")/probe.yaml" >/dev/null; wait_web_ready
k -n migrate get pods -l app=web -o wide --no-headers | awk '{print $7}' | sort | uniq -c
# client가 요청을 보내 200 응답을 기록하기 전에 바꾸면 전환 중 실패를 측정하지 못하므로, 풀·NAP를 바꾸기 전에 확인합니다.
log "wait for client 200 sample"
client_deadline=$(( $(date +%s) + 120 ))
client_ok() { local out; out=$(k -n migrate logs deploy/client --tail=200 2>/dev/null) || return 1; grep -q ' 200$' <<<"$out"; }
until client_ok; do
  (( $(date +%s) < client_deadline )) || { log "client 로그에 120초 안에 200 응답이 없습니다. 변경 전에 중단합니다"; exit 1; }
  sleep 5
done

# AllowClusterAutoscalerAndNAP 없이 NAP를 켜려면 CAS가 켜진 풀이 하나도 없어야 합니다.
# 변경 전 각 풀의 min/max를 저장하고, NAP 활성화 전에 실패·중단하면 CAS를 원래 값으로 되돌립니다.
cas_pools=$(az aks nodepool list -g "$RG" --cluster-name "$CLUSTER" \
  --query "[?enableAutoScaling].[name,minCount,maxCount]" -o tsv)
disabled=""   # "<풀> <min> <max>" 줄 목록. 실패한 변경도 일부 적용됐을 수 있어 호출 전에 기록합니다.
rollback() {
  local rc=$? p min max
  trap '' INT TERM   # 복구 중 들어온 중단 신호로 복구가 끊기지 않게 합니다.
  # NAP 활성화 요청이 실패로 끝나도 실제로는 적용됐을 수 있습니다. NAP가 켜졌거나 확인하지 못하면 CAS를 다시 켜지 않습니다.
  if [[ -n $disabled ]]; then
    local mode
    if ! mode=$(az aks show -g "$RG" -n "$CLUSTER" --query nodeProvisioningProfile.mode -o tsv); then
      log "rollback skipped: node provisioning mode 조회 실패. CAS를 다시 켜지 않습니다. 풀 상태를 직접 확인하세요"; exit "$rc"
    fi
    if [[ $mode == Auto ]]; then
      log "rollback skipped: NAP(mode Auto)가 켜져 있어 CAS를 다시 켜지 않습니다"; exit "$rc"
    fi
  fi
  while read -r -u 3 p min max; do
    [[ -n $p ]] || continue
    log "rollback: enable cluster autoscaler on $p (min $min, max $max)"
    az aks nodepool update -g "$RG" --cluster-name "$CLUSTER" -n "$p" --enable-cluster-autoscaler \
      --min-count "$min" --max-count "$max" -o none || log "rollback failed: $p"
  done 3<<<"$disabled"
  exit "$rc"
}
trap rollback EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
while read -r -u 3 p min max; do
  [[ -n $p ]] || continue
  log "disable cluster autoscaler on $p (count stays $(az aks nodepool show -g "$RG" --cluster-name "$CLUSTER" -n "$p" --query count -o tsv))"
  disabled+="$p $min $max"$'\n'
  az aks nodepool update -g "$RG" --cluster-name "$CLUSTER" -n "$p" --disable-cluster-autoscaler -o none
done 3<<<"$cas_pools"

log "enable NAP"
az aks update -g "$RG" -n "$CLUSTER" --node-provisioning-mode Auto -o none
trap - EXIT INT TERM   # NAP가 켜졌으므로 이후 실패는 CAS로 되돌리지 않습니다.
log "NAP enabled"; k get nodepools.karpenter.sh

while :; do
  # 조건식 안의 $(pool_count)는 조회 실패가 set -e로 전파되지 않으므로 일반 명령으로 읽고 정수인지 확인합니다.
  count=$(pool_count)
  [[ $count =~ ^[0-9]+$ ]] || { log "pool $POOL count is not an integer: ${count}"; exit 1; }
  if (( count == 0 )); then break; fi
  next=$(( count - 1 ))
  log "scale $POOL to $next"
  az aks nodepool scale -g "$RG" --cluster-name "$CLUSTER" -n "$POOL" --node-count "$next" -o none
  wait_web_ready
  log "wave done: $(k get nodes -l karpenter.sh/nodepool --no-headers | wc -l | tr -d ' ') NAP nodes"
done

log "delete empty pool $POOL"
az aks nodepool delete -g "$RG" --cluster-name "$CLUSTER" -n "$POOL" -o none
k -n migrate get pods -l app=web -o wide --no-headers | awk '{print $7}' | sort | uniq -c
log "done"
