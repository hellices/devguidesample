#!/usr/bin/env bash
# 5초 간격으로 Unix 시각, 원하는 replica, Ready replica, KEDA가 만든 HPA의 현재 지표, 워크로드 노드 수를 CSV로 기록합니다.
# 기본 1200초 동안 기록합니다. Pod 축소(약 11~12분)와 노드 정리(약 16~17분)까지 보려면 줄이지 않습니다.
# postdeploy hook은 이 스크립트를 load/watcher.yaml Job으로 클러스터 안에서 실행하고(CTX 없음 = in-cluster),
# epoch를 k6 시작 시각 기준 경과 초(elapsed_s)로 바꿔 저장합니다. 조회에 실패한 값은 빈 칸으로 남깁니다.
set -uo pipefail
NS=${NS:-demo} DEPLOY=${DEPLOY:-podinfo} DURATION=${DURATION:-1200} INTERVAL=${INTERVAL:-5}
k() { kubectl ${CTX:+--context "$CTX"} "$@"; }
echo "epoch,desired,ready,hpa_metric,user_nodes"
start=$(date +%s) i=0
while (( $(date +%s) - start < DURATION )); do
  now=$(date +%s)
  dep=$(k -n "$NS" get deploy "$DEPLOY" -o jsonpath='{.spec.replicas},{.status.readyReplicas}' 2>/dev/null) || dep=","
  desired=${dep%%,*} ready=${dep#*,}
  [[ -n $desired && -z $ready ]] && ready=0
  metric=$(k -n "$NS" get hpa -o jsonpath='{.items[0].status.currentMetrics[0].external.current.averageValue}' 2>/dev/null) || metric=""
  if nl=$(k get nodes -l kubernetes.azure.com/mode=user --no-headers 2>/dev/null); then
    nodes=$(grep -c . <<<"$nl")
  else
    nodes=""
  fi
  echo "$now,$desired,$ready,$metric,$nodes"
  # 조회 시간과 관계없이 start + i×INTERVAL 시각에 다음 기록을 시작합니다.
  i=$((i + 1)); wait_s=$(( start + i * INTERVAL - $(date +%s) ))
  (( wait_s > 0 )) && sleep "$wait_s"
done
