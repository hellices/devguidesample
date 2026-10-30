#!/usr/bin/env bash
# 사용법: bench.sh <kube-context> <scenario> <replicas> <runs> [nodeSelector key=value] >> results.csv
# 워크로드 노드(kubernetes.azure.com/mode=user)가 0개인 상태에서 시작해 scale-out/in 시간을 초 단위로 기록합니다.
set -euo pipefail
CTX=$1 SCENARIO=$2 REPLICAS=$3 RUNS=$4 SELECTOR=${5:-}
TIMEOUT=${TIMEOUT:-1800}
k() { kubectl --context "$CTX" "$@"; }
log() { echo "[$(date -u +%T)] $*" >&2; }

workload_nodes() { k get nodes -l kubernetes.azure.com/mode=user --no-headers 2>/dev/null | wc -l | tr -d ' '; }
ready_workload_nodes() {
  k get nodes -l kubernetes.azure.com/mode=user \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' | grep -c True || true
}
ready_pods() {
  k -n bench get pods -l app=inflate \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' | grep -c True || true
}
wait_until() { # wait_until <description> <command...>; 경과 초를 출력
  local desc=$1; shift; local start; start=$(date +%s)
  until "$@"; do
    (( $(date +%s) - start > TIMEOUT )) && { log "timeout: $desc"; echo -1; return; }
    sleep 2
  done
  echo $(( $(date +%s) - start ))
}

k apply -f "$(dirname "$0")/../manifests/inflate.yaml" >/dev/null
if [[ -n $SELECTOR ]]; then
  k -n bench patch deployment inflate --type merge \
    -p "{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"${SELECTOR%%=*}\":\"${SELECTOR#*=}\"}}}}}" >/dev/null
fi

[[ -n ${HEADER:-} ]] && echo "scenario,run,replicas,first_node_ready_s,all_pods_ready_s,new_nodes,skus,scale_in_s"
for run in $(seq 1 "$RUNS"); do
  log "$SCENARIO run $run: waiting for zero workload nodes"
  wait_until "baseline" bash -c "[[ \$(kubectl --context $CTX get nodes -l kubernetes.azure.com/mode=user --no-headers 2>/dev/null | wc -l) -eq 0 ]]" >/dev/null

  t0=$(date +%s)
  k -n bench scale deployment inflate --replicas "$REPLICAS" >/dev/null
  first_node="" all_ready=""
  while [[ -z $all_ready ]]; do
    now=$(( $(date +%s) - t0 ))
    (( now > TIMEOUT )) && { all_ready=-1; break; }
    [[ -z $first_node && $(ready_workload_nodes) -gt 0 ]] && first_node=$now && log "first node ready ${now}s"
    [[ $(ready_pods) -ge $REPLICAS ]] && all_ready=$now
    sleep 2
  done
  log "all pods ready ${all_ready}s"
  nodes=$(workload_nodes)
  skus=$(k get nodes -l kubernetes.azure.com/mode=user \
    -o jsonpath='{range .items[*]}{.metadata.labels.node\.kubernetes\.io/instance-type}{"\n"}{end}' | sort | uniq -c | awk '{printf "%s%sx%s", sep, $2, $1; sep=" "}')

  k -n bench scale deployment inflate --replicas 0 >/dev/null
  scale_in=$(wait_until "scale-in" bash -c "[[ \$(kubectl --context $CTX get nodes -l kubernetes.azure.com/mode=user --no-headers 2>/dev/null | wc -l) -eq 0 ]]")
  log "scale-in ${scale_in}s"
  echo "$SCENARIO,$run,$REPLICAS,$first_node,$all_ready,$nodes,$skus,$scale_in"
done
