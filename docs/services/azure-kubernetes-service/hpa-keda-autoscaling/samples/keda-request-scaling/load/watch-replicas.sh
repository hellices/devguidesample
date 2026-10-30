#!/usr/bin/env bash
# 5초마다 시각, 원하는 replica, Ready replica, KEDA가 만든 HPA의 현재 메트릭과 워크로드 노드 수를 CSV로 기록합니다.
set -euo pipefail
CTX=${CTX:-aks-nap} NS=${NS:-demo} DEPLOY=${DEPLOY:-podinfo} DURATION=${DURATION:-600}
k() { kubectl --context "$CTX" "$@"; }
echo "elapsed_s,desired,ready,hpa_metric,user_nodes"
start=$(date +%s)
while (( $(date +%s) - start < DURATION )); do
  read -r desired ready < <(k -n "$NS" get deploy "$DEPLOY" -o jsonpath='{.spec.replicas} {.status.readyReplicas}{"\n"}')
  metric=$(k -n "$NS" get hpa -o jsonpath='{.items[0].status.currentMetrics[0].external.current.averageValue}' 2>/dev/null || true)
  nodes=$(k get nodes -l kubernetes.azure.com/mode=user --no-headers 2>/dev/null | wc -l | tr -d ' ')
  echo "$(( $(date +%s) - start )),${desired:-0},${ready:-0},${metric:-},${nodes}"
  sleep 5
done
