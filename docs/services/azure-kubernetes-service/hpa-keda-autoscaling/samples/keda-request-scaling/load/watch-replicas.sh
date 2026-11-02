#!/usr/bin/env bash
# 5초 간격으로 Unix 시각, 원하는 replica, Ready replica, KEDA가 만든 HPA의 현재 지표, 워크로드 노드 수를 CSV로 기록합니다.
# 대상은 demo namespace의 Deployment podinfo와 KEDA가 ScaledObject 이름으로 만드는 HPA keda-hpa-podinfo입니다.
# DURATION(기본 1200초) 동안 기록합니다. Pod 축소(약 11~12분)와 노드 정리(약 16~17분)까지 보려면 줄이지 않습니다.
# postdeploy hook이 load/watcher.yaml Job으로 클러스터 안에서 실행하고(in-cluster 인증),
# epoch를 k6 시작 시각 기준 경과 초(elapsed_s)로 바꿔 저장합니다.
# 조회에 실패한 값은 빈 칸으로 남기고 kubectl 오류는 stderr(Job 로그)에 남깁니다. hook은 숫자로 시작하는 줄만 CSV로 씁니다.
set -uo pipefail
DURATION=${DURATION:-1200} INTERVAL=5
[[ $DURATION =~ ^[0-9]+$ ]] && (( 10#$DURATION > 0 )) || { echo "DURATION은 양의 정수여야 합니다: '${DURATION}'" >&2; exit 2; }
# 앞자리 0(예: 08)이 있어도 8진수로 해석하지 않도록 검증 뒤 10진수로 바꿉니다.
DURATION=$((10#$DURATION))
# 조회 하나가 멈춰도 다음 기록을 이어 가도록 요청마다 제한을 둡니다.
k() { kubectl --request-timeout=10s "$@"; }
echo "epoch,desired,ready,hpa_metric,user_nodes"
start=$(date +%s) next=$(( start + INTERVAL ))
while now=$(date +%s); (( now - start < DURATION )); do
  dep=$(k -n demo get deploy podinfo -o jsonpath='{.spec.replicas},{.status.readyReplicas}') || dep=","
  desired=${dep%%,*} ready=${dep#*,}
  [[ -n $desired && -z $ready ]] && ready=0
  # 지표가 아직 없으면 [0] 대신 [*]로 읽어 오류 없이 빈 칸을 남깁니다(ScaledObject당 trigger는 하나).
  metric=$(k -n demo get hpa keda-hpa-podinfo -o jsonpath='{.status.currentMetrics[*].external.current.averageValue}') || metric=""
  if nl=$(k get nodes -l kubernetes.azure.com/mode=user -o name); then
    # 조회가 성공하고 노드가 없으면 빈 칸이 아니라 0을 기록합니다.
    nodes=$(awk 'NF { n++ } END { print n + 0 }' <<<"$nl")
  else
    nodes=""
  fi
  echo "$now,$desired,$ready,$metric,$nodes"
  # 조회 시간과 관계없이 start + i×INTERVAL 시각(next)에 다음 기록을 시작합니다.
  # 한 번의 기록이 INTERVAL보다 오래 걸리면 이미 지난 시각만 건너뛰고, 지금 시각과 같으면 바로 기록합니다.
  t=$(date +%s)
  while (( next < t )); do next=$(( next + INTERVAL )); done
  sleep "$(( next - t ))"
  next=$(( next + INTERVAL ))
done
