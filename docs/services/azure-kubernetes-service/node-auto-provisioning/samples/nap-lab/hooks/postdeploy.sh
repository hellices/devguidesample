#!/usr/bin/env bash
# azd postdeploy hook: EXPERIMENT 환경 값에 적은 실험을 차례로 실행하고 결과를 out/<azd 환경>/에 남깁니다.
#   azd env set EXPERIMENT "scale-out waves"   # 공백 또는 쉼표로 여러 개
#   azd env set RUNS 3                         # 반복 횟수(일부 실험은 고정)
#   azd hooks run postdeploy                   # 또는 azd deploy
# 실험: scale-out waves large dealloc azurelinux overprovision quota-fallback mixed rightsize
#       zone1 burst40 quota-staleness migration drift
# migration은 CAS 클러스터에 NAP를 켜므로 CAS 실험을 모두 끝낸 뒤 마지막에 실행합니다.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${AZURE_RESOURCE_GROUP:?}" "${CAS_CLUSTER_NAME:?}" "${NAP_CLUSTER_NAME:?}" "${AZURE_LOCATION:?}" "${AZURE_ENV_NAME:?}"
RG=$AZURE_RESOURCE_GROUP CAS=$CAS_CLUSTER_NAME NAP=$NAP_CLUSTER_NAME LOC=$AZURE_LOCATION
RUNS=${RUNS:-3}
export OUT=out/$AZURE_ENV_NAME PRICES=results/prices-$LOC.json
mkdir -p "$OUT"
log() { echo "[$(date -u +%T)] $*" >&2; }

BENCH_HEADER=scenario,run,replicas,decision_s,vm_launched_s,first_node_ready_s,last_node_ready_s,all_pods_ready_s,new_nodes,skus,scale_in_s,wave_latency_s
# csv <file> <header>: 표준 입력을 결과 CSV에 덧붙입니다(처음이면 header 먼저).
csv() { local f=$OUT/$1; [[ -s $f ]] || echo "$2" > "$f"; tee -a "$f"; }

nrg=$(az aks show -g "$RG" -n "$CAS" --query nodeResourceGroup -o tsv)
vmss_count() { # CAS 풀의 남은 VM 수
  local s; s=$(az vmss list -g "$nrg" --query "[?tags.\"aks-managed-poolName\"=='$1'].name | [0]" -o tsv)
  echo "az vmss list-instances -g $nrg -n $s --query 'length(@)' -o tsv"
}
claim_count() { echo "kubectl --context $NAP get nodeclaims -l karpenter.sh/nodepool=$1 --no-headers | wc -l"; }
add_pool() { # add_pool <name> <az aks nodepool add 추가 인수...>
  local name=$1; shift
  az aks nodepool show -g "$RG" --cluster-name "$CAS" -n "$name" -o none 2>/dev/null && return 0
  log "CAS 풀 $name 추가"
  az aks nodepool add -g "$RG" --cluster-name "$CAS" -n "$name" --mode User --node-count 0 \
    --enable-cluster-autoscaler --min-count 0 "$@" -o none
}
del_pool() { # 노드 풀 10개 제한 정책이 있는 구독을 위해 실험이 끝나면 풀을 지웁니다.
  az aks nodepool show -g "$RG" --cluster-name "$CAS" -n "$1" -o none 2>/dev/null || return 0
  log "CAS 풀 $1 삭제"; az aks nodepool delete -g "$RG" --cluster-name "$CAS" -n "$1" -o none
}
profile() { az aks update -g "$RG" -n "$CAS" --cluster-autoscaler-profile "$@" -o none; }
nap_apply() { kubectl --context "$NAP" apply -f "$@" >/dev/null; }
nap_delete() { kubectl --context "$NAP" delete --ignore-not-found -f "$@" >/dev/null; }

exp_scale_out() {
  SCALE_IN_COUNT=$(vmss_count user) ./bench/bench.sh "$CAS" cas-burst 20 "$RUNS" agentpool=user | csv scale-out.csv "$BENCH_HEADER"
  SCALE_IN_COUNT=$(claim_count bench-fixed) ./bench/bench.sh "$NAP" nap-burst 20 "$RUNS" bench=fixed | csv scale-out.csv "$BENCH_HEADER"
}
exp_waves() {
  export WAVES="5 5 5 5" WAVE_INTERVAL=30
  SCALE_IN_COUNT=$(vmss_count user) ./bench/bench.sh "$CAS" cas-waves 20 2 agentpool=user | csv scale-out.csv "$BENCH_HEADER"
  SCALE_IN_COUNT=$(claim_count bench-fixed) ./bench/bench.sh "$NAP" nap-waves 20 2 bench=fixed | csv scale-out.csv "$BENCH_HEADER"
  unset WAVES WAVE_INTERVAL
}
exp_large() { # 6 vCPU Pod: CAS D4 풀은 확장하지 못하고 NAP flex는 큰 VM을 고릅니다.
  CPU=6 TIMEOUT=150 ./bench/bench.sh "$CAS" cas-large 4 1 agentpool=user | csv scale-out.csv "$BENCH_HEADER"
  CPU=6 ./bench/bench.sh "$NAP" nap-large 4 1 bench=flex | csv scale-out.csv "$BENCH_HEADER"
}
exp_dealloc() { # 1회차는 새 VM, 2회차부터 할당 해제한 VM 재시작
  add_pool userdea --node-vm-size Standard_D4ds_v7 --max-count 10 --node-osdisk-type Managed --scale-down-mode Deallocate
  ./bench/bench.sh "$CAS" cas-dealloc 20 "$RUNS" agentpool=userdea | csv scale-out.csv "$BENCH_HEADER"
  del_pool userdea
}
exp_azurelinux() {
  add_pool userazl --node-vm-size Standard_D4ds_v7 --max-count 10 --os-sku AzureLinux
  ./bench/bench.sh "$CAS" cas-azl 20 2 agentpool=userazl | csv scale-out.csv "$BENCH_HEADER"
  del_pool userazl
  nap_apply manifests/nodepool-azurelinux.yaml
  ./bench/bench.sh "$NAP" nap-azl 20 2 bench=azl | csv scale-out.csv "$BENCH_HEADER"
}
exp_overprovision() {
  ./bench/overprovision.sh "$CAS" cas-overprov agentpool=user 2 | csv overprovisioning.csv scenario,run,pods_ready_s,placeholder_rescheduled_s
  ./bench/overprovision.sh "$NAP" nap-overprov bench=fixed 2 | csv overprovisioning.csv scenario,run,pods_ready_s,placeholder_rescheduled_s
}
exp_quota_fallback() {
  # 리전·계열 quota를 넘는 Standard_D96ds_v7을 1순위, Standard_D4ds_v7을 대체로 둡니다(구독 quota에 따라 결과가 달라짐).
  profile expander=priority
  az aks nodepool update -g "$RG" --cluster-name "$CAS" -n user --labels bench=q -o none
  add_pool big --node-vm-size Standard_D96ds_v7 --labels bench=q --max-count 2
  kubectl --context "$CAS" apply -f manifests/cas-priority-expander.yaml >/dev/null
  nap_apply manifests/nodepool-quota-fallback.yaml
  ./bench/bench.sh "$CAS" cas-quota 20 2 bench=q >/dev/null
  ./bench/bench.sh "$NAP" nap-quota 20 2 bench=q >/dev/null
  for r in 1 2; do
    python3 bench/fallback.py "$OUT/cas-quota/run$r" cas-quota "$r" aks-user
    python3 bench/fallback.py "$OUT/nap-quota/run$r" nap-quota "$r" fallback
  done | csv quota-fallback.csv scenario,run,preferred_attempt_s,preferred_failure_s,fallback_decision_s,first_node_ready_s,all_pods_ready_s,note
  nap_delete manifests/nodepool-quota-fallback.yaml
  del_pool big
  az aks nodepool update -g "$RG" --cluster-name "$CAS" -n user --labels "" -o none
  profile expander=random
}
exp_mixed() {
  local h=scenario,run,ready_big,ready_mem,ready_small,all_ready_s,nodes,skus,vcpu_alloc,mem_alloc_gib,cpu_request_ratio,mem_request_ratio,usd_per_hour
  profile expander=random
  add_pool mixgen --node-vm-size Standard_D4as_v7 --labels bench=mix --max-count 10
  TIMEOUT=420 ./bench/mixed.sh "$CAS" cas-one-pool bench=mix 1 | csv mixed-shapes.csv "$h"
  add_pool mixmem --node-vm-size Standard_E4as_v7 --labels bench=mix --max-count 10
  add_pool mixcpu --node-vm-size Standard_F8as_v7 --labels bench=mix --max-count 10
  ./bench/mixed.sh "$CAS" cas-three-pools-random bench=mix 2 | csv mixed-shapes.csv "$h"
  profile expander=least-waste
  ./bench/mixed.sh "$CAS" cas-three-pools-least-waste bench=mix 2 | csv mixed-shapes.csv "$h"
  profile expander=random
  for p in mixgen mixmem mixcpu; do del_pool $p; done
  nap_apply manifests/nodepool-mixed.yaml
  ./bench/mixed.sh "$NAP" nap-def-v7 bench=mix 2 | csv mixed-shapes.csv "$h"
}
exp_rightsize() { # 20 → 3 Pod, 12분 관찰
  add_pool big32 --node-vm-size Standard_D32als_v7 --max-count 2
  ./bench/rightsize.sh "$NAP" nap-flex bench=flex > "$OUT/rightsize-nap-flex.csv"
  ./bench/rightsize.sh "$CAS" cas-d4 agentpool=user > "$OUT/rightsize-cas-d4.csv"
  ./bench/rightsize.sh "$CAS" cas-d32 agentpool=big32 > "$OUT/rightsize-cas-d32.csv"
  del_pool big32
}
exp_zone1() {
  add_pool userz1 --node-vm-size Standard_D4ds_v7 --max-count 10 --zones 1
  sed "s/eastus2-1/$LOC-1/" manifests/nodepool-zone1.yaml | kubectl --context "$NAP" apply -f - >/dev/null
  ./bench/bench.sh "$CAS" cas-zone1 20 "$RUNS" agentpool=userz1 | csv zone1-burst.csv "$BENCH_HEADER"
  ./bench/bench.sh "$NAP" nap-zone1 20 "$RUNS" bench=zone1 | csv zone1-burst.csv "$BENCH_HEADER"
  del_pool userz1
}
exp_burst40() { # 2 vCPU VM 40대. VMSS 10대 제한 정책을 피하려고 CAS는 max 10 풀 4개를 균형 확장
  for p in d2 d2b d2c d2d; do add_pool $p --node-vm-size Standard_D2ds_v7 --labels bench=d2x --max-count 10; done
  profile balance-similar-node-groups=true
  nap_apply manifests/nodepool-d2.yaml
  ./bench/bench.sh "$CAS" cas-d2x40 40 1 bench=d2x | csv burst-40-nodes.csv "$BENCH_HEADER"
  ./bench/bench.sh "$NAP" nap-d2x40 40 1 bench=d2 | csv burst-40-nodes.csv "$BENCH_HEADER"
  for p in d2 d2b d2c d2d; do del_pool $p; done
}
exp_quota_staleness() {
  BASELINE_USAGE=$(az vm list-usage -l "$LOC" --query "[?name.value=='StandardDdsv7Family'].currentValue | [0]" -o tsv) \
    ./bench/quota-staleness.sh "$NAP" "$CAS" "$LOC" > "$OUT/quota-staleness.csv"
}
exp_migration() { # in-place.sh가 probe(web 6 replica + client)를 배포하고 경로 1을 실행합니다.
  ./migrate/in-place.sh | tee "$OUT/migration.log"
  kubectl --context "$CAS" -n migrate logs deploy/client > "$OUT/migration-probe.log"
}
exp_drift() { # migration 뒤 NAP drift로 노드 전체 교체. preStop 없음 → preStop.sleep 10s 순서
  local ctx=$CAS
  drift_round() { # drift_round <label 값> <결과 이름>
    local start; start=$(date -u +%FT%TZ)
    kubectl --context "$ctx" patch nodepool default --type merge \
      -p "{\"spec\":{\"template\":{\"metadata\":{\"labels\":{\"rotation\":\"$1\"}}}}}" >/dev/null
    log "drift $1 시작"
    old_claims() { # drift 시작 전에 만들어진 NodeClaim 수. 조회에 실패하면 nonzero로 반환해 완료로 오인하지 않습니다.
      local j; j=$(kubectl --context "$ctx" get nodeclaims -l karpenter.sh/nodepool=default -o json) || return 1
      python3 -c "import json,sys;print(sum(c['metadata']['creationTimestamp']<'$start' for c in json.load(sys.stdin)['items']))" <<<"$j"
    }
    local n
    until n=$(old_claims) && [[ $n == 0 ]]; do sleep 15; done
    kubectl --context "$ctx" -n migrate rollout status deploy/web --timeout=15m >/dev/null
    local end; end=$(date -u +%FT%TZ)
    kubectl --context "$ctx" -n migrate logs deploy/client --since-time="$start" |
      awk -v s="$start" -v e="$end" -v n="$2" '$1>=s && $1<=e {t++; if ($2!="200") f++} END {printf "%s,%s,%s,%d,%d\n", n, s, e, t, f}'
  }
  # 이전 실행에서 남은 preStop을 지우고 rollout이 끝난 뒤 시작합니다.
  if [[ -n $(kubectl --context "$ctx" -n migrate get deploy web -o jsonpath='{.spec.template.spec.containers[0].lifecycle}') ]]; then
    kubectl --context "$ctx" -n migrate patch deploy web --type json \
      -p '[{"op":"remove","path":"/spec/template/spec/containers/0/lifecycle"}]' >/dev/null
    kubectl --context "$ctx" -n migrate rollout status deploy/web --timeout=15m >/dev/null
  fi
  drift_round "r1-$(date +%s)" drift-no-prestop | csv drift.csv round,start,end,requests,failed
  # preStop을 먼저 적용하고 rollout이 끝난 뒤 drift를 시작해야 두 조건이 섞이지 않습니다.
  kubectl --context "$ctx" -n migrate patch deploy web --type strategic -p \
    '{"spec":{"template":{"spec":{"containers":[{"name":"podinfo","lifecycle":{"preStop":{"sleep":{"seconds":10}}}}]}}}}' >/dev/null
  kubectl --context "$ctx" -n migrate rollout status deploy/web --timeout=15m >/dev/null
  drift_round "r2-$(date +%s)" drift-prestop-10s | csv drift.csv round,start,end,requests,failed
}

list=${EXPERIMENT:-}
# azd up도 이 hook을 실행하므로 값이 없으면 안내만 하고 끝냅니다.
[[ -n $list ]] || { echo "실행할 실험이 없습니다. 예: azd env set EXPERIMENT scale-out && azd hooks run postdeploy"; exit 0; }
for e in ${list//,/ }; do
  fn=exp_${e//-/_}
  declare -F "$fn" >/dev/null || { echo "알 수 없는 실험: $e" >&2; exit 1; }
  log "실험 $e 시작"; "$fn"; log "실험 $e 완료"
done
echo "결과: $OUT"
