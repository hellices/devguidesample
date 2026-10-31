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
wait_web_ready() { # 원하는 replica가 모두 Ready·Available이 될 때까지(15분 제한). 일부 Pod 누락 상태로 진행하지 않습니다.
  local deadline=$(( $(date +%s) + 900 )) s gen obs want ready avail
  while :; do
    s=$(k -n migrate get deploy web -o jsonpath='{.metadata.generation},{.status.observedGeneration},{.spec.replicas},{.status.readyReplicas},{.status.availableReplicas}') || s=""
    IFS=, read -r gen obs want ready avail <<<"$s"
    if [[ -n $want && $obs == "$gen" && ${ready:-0} == "$want" && ${avail:-0} == "$want" ]]; then return 0; fi
    (( $(date +%s) < deadline )) || { log "timeout: web not ready (generation,observed,replicas,ready,available=$s)"; return 1; }
    sleep 2
  done
}

log "deploy probe"; k apply -f "$(dirname "$0")/probe.yaml" >/dev/null; wait_web_ready
k -n migrate get pods -l app=web -o wide --no-headers | awk '{print $7}' | sort | uniq -c

# AllowClusterAutoscalerAndNAP 없이 NAP를 켜려면 CAS가 켜진 풀이 하나도 없어야 합니다.
for p in $(az aks nodepool list -g "$RG" --cluster-name "$CLUSTER" --query "[?enableAutoScaling].name" -o tsv); do
  log "disable cluster autoscaler on $p (count stays $(az aks nodepool show -g "$RG" --cluster-name "$CLUSTER" -n "$p" --query count -o tsv))"
  az aks nodepool update -g "$RG" --cluster-name "$CLUSTER" -n "$p" --disable-cluster-autoscaler -o none
done

log "enable NAP"
az aks update -g "$RG" -n "$CLUSTER" --node-provisioning-mode Auto -o none
log "NAP enabled"; k get nodepools.karpenter.sh

while (( $(pool_count) > 0 )); do
  next=$(( $(pool_count) - 1 ))
  log "scale $POOL to $next"
  az aks nodepool scale -g "$RG" --cluster-name "$CLUSTER" -n "$POOL" --node-count "$next" -o none
  wait_web_ready
  log "wave done: $(k get nodes -l karpenter.sh/nodepool --no-headers | wc -l | tr -d ' ') NAP nodes"
done

log "delete empty pool $POOL"
az aks nodepool delete -g "$RG" --cluster-name "$CLUSTER" -n "$POOL" -o none
k -n migrate get pods -l app=web -o wide --no-headers | awk '{print $7}' | sort | uniq -c
log "done"
