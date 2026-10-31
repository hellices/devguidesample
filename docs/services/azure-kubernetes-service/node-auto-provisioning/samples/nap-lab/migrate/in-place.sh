#!/usr/bin/env bash
# Path 1 리허설: 모든 풀의 CAS 비활성화 → NAP 활성화 → 고정 user pool을 단계적으로 축소 → 풀 삭제
set -euo pipefail
RG=${RG:-rg-aks-autoscale-lab} CLUSTER=${CLUSTER:-aks-cas} POOL=${POOL:-user} CTX=${CTX:-aks-cas}
k() { kubectl --context "$CTX" "$@"; }
log() { echo "[$(date -u +%T)] $*"; }
pool_count() { az aks nodepool show -g "$RG" --cluster-name "$CLUSTER" -n "$POOL" --query count -o tsv; }
wait_web_ready() { k -n migrate rollout status deploy/web --timeout=15m >/dev/null; k -n migrate wait --for=condition=Ready pod -l app=web --timeout=15m >/dev/null; }

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
