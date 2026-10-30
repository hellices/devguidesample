#!/usr/bin/env bash
# 사용법: overprovision.sh <kube-context> <scenario> <nodeSelector key=value> [runs]
# placeholder Pod(PriorityClass -10) 3개로 노드 1대분 여유를 잡아 둔 상태에서
# 실제 Pod 3개를 추가해 Ready까지 걸린 시간을 기록합니다.
set -euo pipefail
CTX=$1 SCENARIO=$2 SELECTOR=$3 RUNS=${4:-2}
HERE=$(cd "$(dirname "$0")" && pwd)
k() { kubectl --context "$CTX" "$@"; }
log() { echo "[$(date -u +%T)] $SCENARIO $*" >&2; }
sel="[{\"op\":\"add\",\"path\":\"/spec/template/spec/nodeSelector\",\"value\":{\"${SELECTOR%%=*}\":\"${SELECTOR#*=}\"}}]"

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
  k -n bench rollout status deployment/overprovisioning --timeout=15m >/dev/null
  # 빈 여유 노드가 남아 있으면 선점 없이 바로 배치되므로, placeholder가 있는 노드 1대만 남을 때까지 기다립니다.
  stable=0
  until (( stable >= 3 )); do
    n=$(k get nodes -l "$SELECTOR" -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' | grep -c True || true)
    if [[ $n == 1 ]]; then stable=$((stable + 1)); else stable=0; fi
    sleep 10
  done
  t0=$(date +%s)
  k -n bench scale deployment inflate --replicas 3 >/dev/null
  until [[ $(k -n bench get deploy inflate -o jsonpath='{.status.readyReplicas}') == 3 ]]; do sleep 1; done
  t1=$(date +%s)
  # 선점된 placeholder가 새 노드에서 다시 Running이 될 때까지(다음 burst를 받을 여유가 복구되는 시간)
  until [[ $(k -n bench get deploy overprovisioning -o jsonpath='{.status.readyReplicas}') == 3 ]]; do sleep 2; done
  t2=$(date +%s)
  echo "$SCENARIO,$run,$((t1 - t0)),$((t2 - t0))"
done
k -n bench scale deployment inflate --replicas 0 >/dev/null
k -n bench delete deployment overprovisioning >/dev/null
