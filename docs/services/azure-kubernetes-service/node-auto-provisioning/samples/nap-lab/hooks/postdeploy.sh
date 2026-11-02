#!/usr/bin/env bash
# azd postdeploy hook: EXPERIMENT 환경 값에 적은 실험을 차례로 실행하고 결과를 out/<azd 환경>/에 남깁니다.
#   azd env set EXPERIMENT "scale-out waves"   # 공백 또는 쉼표로 여러 개
#   azd env set RUNS 3                         # 반복 횟수(일부 실험은 고정)
#   azd hooks run postdeploy                   # 또는 azd deploy
# 실험: scale-out waves large dealloc azurelinux overprovision quota-fallback mixed rightsize
#       zone1 burst40 quota-staleness migration drift
# migration은 CAS 클러스터에 NAP를 켜므로 CAS 실험을 모두 끝낸 뒤 마지막에 실행합니다.
# 실험 이름·RUNS 등 입력은 첫 실험을 시작하기 전에 모두 확인합니다.
# 결과 CSV는 실험이 성공했을 때만 행을 덧붙이고(header가 다르면 실패), rightsize-*.csv·quota-staleness.csv·migration*.log는 덮어씁니다.
set -euo pipefail
cd "$(dirname "$0")/.."
source bench/lib.sh
list=${EXPERIMENT:-}
# azd up도 이 hook을 실행하므로 값이 없으면 환경 값 확인·Azure 호출 전에 안내만 하고 끝냅니다.
[[ -n ${list//[[:space:],]/} ]] || { echo "실행할 실험이 없습니다. 예: azd env set EXPERIMENT scale-out && azd hooks run postdeploy"; exit 0; }
: "${AZURE_RESOURCE_GROUP:?}" "${CAS_CLUSTER_NAME:?}" "${NAP_CLUSTER_NAME:?}" "${AZURE_LOCATION:?}" "${AZURE_ENV_NAME:?}"
RG=$AZURE_RESOURCE_GROUP CAS=$CAS_CLUSTER_NAME NAP=$NAP_CLUSTER_NAME LOC=$AZURE_LOCATION
RUNS=$(int_arg RUNS "${RUNS:-3}" 1) || exit 2
# 리전은 매니페스트 sed 치환과 파일 이름에, 환경 이름은 결과 경로에 들어가므로 형식을 확인합니다.
[[ $LOC =~ ^[a-z0-9]+$ ]] || { echo "AZURE_LOCATION은 Azure 리전 이름(소문자·숫자)이어야 합니다: ${LOC}" >&2; exit 2; }
[[ $AZURE_ENV_NAME =~ ^[A-Za-z0-9-]+$ ]] || { echo "AZURE_ENV_NAME은 영문자·숫자·'-'만 쓸 수 있습니다: ${AZURE_ENV_NAME}" >&2; exit 2; }
export OUT=out/$AZURE_ENV_NAME PRICES=results/prices-$LOC.json
log() { echo "[$(date -u +%T)] $*" >&2; }
k() { local ctx=$1; shift; kubectl --context "$ctx" --request-timeout="$KUBE_RT" "$@"; }   # k <context> <kubectl 인수...>

BENCH_HEADER=scenario,run,replicas,decision_s,vm_launched_s,first_node_ready_s,last_node_ready_s,all_pods_ready_s,new_nodes,skus,scale_in_s,wave_latency_s
# csv <file> <header>: 표준 입력을 <file>.pending에 모으고 그대로 출력합니다. 실험이 성공해야 commit_csv가 결과 CSV에
# 덧붙이므로, 중간에 실패한 실험의 일부 행이 재실행 결과와 섞이지 않습니다. 기존 header가 다르면 섞지 않고 실패합니다.
csv() {
  local f=$OUT/$1 first=""
  if [[ -s $f ]]; then
    IFS= read -r first < "$f" || true
    [[ $first == "$2" ]] || { log "${f}의 header가 현재 형식과 다릅니다. 파일을 옮긴 뒤 다시 실행하세요"; return 1; }
  elif [[ ! -s $f.pending ]]; then
    echo "$2" > "$f.pending"
  fi
  tee -a "$f.pending"
}
commit_csv() { # 성공한 실험의 .pending 행을 결과 CSV에 덧붙이고 지웁니다.
  local p
  for p in "$OUT"/*.pending; do
    [[ -e $p ]] || continue
    cat "$p" >> "${p%.pending}" && rm -f "$p"
  done
}

# scale_in_cmd <CAS 풀>: 그 풀의 VMSS가 정확히 하나일 때 남은 VM 수를 출력하는 명령을 SCALE_CMD에 설정합니다.
# $(...) 안에서 부르면 실패가 전파되지 않으므로 일반 명령으로 호출합니다.
scale_in_cmd() {
  local nrg s
  nrg=$(azq aks show -g "$RG" -n "$CAS" --query nodeResourceGroup -o tsv) || return 1
  [[ -n $nrg ]] || { log "CAS 노드 리소스 그룹을 찾지 못했습니다"; return 1; }
  s=$(azq vmss list -g "$nrg" --query "[?tags.\"aks-managed-poolName\"=='$1'].name" -o tsv) || return 1
  [[ -n $s && $s != *$'\n'* ]] || { log "CAS 풀 $1의 VMSS가 정확히 하나가 아닙니다: ${s:-없음}"; return 1; }
  printf -v SCALE_CMD 'az vmss list-instances -g %q -n %q --query %q -o tsv' "$nrg" "$s" 'length(@)'
}
claim_cmd() { # claim_cmd <NodePool>: 남은 NodeClaim 수를 출력하는 명령을 SCALE_CMD에 설정합니다.
  printf -v SCALE_CMD 'kubectl --context %q --request-timeout=%q get nodeclaims -l %q -o name | wc -l' \
    "$NAP" "$KUBE_RT" "karpenter.sh/nodepool=$1"
}
pool_exists() { # 목록에 있으면 0, 없으면 1, 조회 실패(인증·네트워크 등)는 2
  local found
  found=$(azq aks nodepool list -g "$RG" --cluster-name "$CAS" --query "[?name=='$1'].name" -o tsv) || return 2
  [[ -n $found ]]
}
add_pool() { # add_pool <name> <az aks nodepool add 추가 인수...>. 이미 있으면 그대로 씁니다.
  local name=$1 rc=0; shift
  pool_exists "$name" || rc=$?
  (( rc != 2 )) || return 1
  (( rc != 0 )) || return 0
  log "CAS 풀 $name 추가"
  azop aks nodepool add -g "$RG" --cluster-name "$CAS" -n "$name" --mode User --node-count 0 \
    --enable-cluster-autoscaler --min-count 0 "$@" -o none
}
del_pool() { # 노드 풀 10개 제한 정책이 있는 구독을 위해 실험이 끝나면 풀을 지웁니다.
  # 목록에 없을 때만 이미 지워진 것으로 봅니다. 조회 실패는 nonzero로 반환합니다.
  local rc=0
  pool_exists "$1" || rc=$?
  (( rc != 2 )) || return 1
  (( rc != 1 )) || return 0
  log "CAS 풀 $1 삭제"; azop aks nodepool delete -g "$RG" --cluster-name "$CAS" -n "$1" -o none
}
profile() { azop aks update -g "$RG" -n "$CAS" --cluster-autoscaler-profile "$@" -o none; }
nap_apply() { k "$NAP" apply -f "$@" >/dev/null; }
# NodePool 삭제는 NodeClaim 정리를 기다리므로 자체 --timeout보다 긴 요청 제한을 둡니다.
nap_delete() { kubectl --context "$NAP" --request-timeout=16m delete --ignore-not-found --timeout=15m -f "$@" >/dev/null; }
# 풀·autoscaler profile을 바꾸는 실험은 함수 본문을 subshell ( ... )로 실행하고 on_exit <정리 명령...>을 등록합니다.
# benchmark가 실패·중단돼도 정리 명령을 실행하고 원래 실패 상태로 끝납니다. 정리 실패는 성공만 실패로 바꿉니다.
finish() {
  local rc=$?
  trap '' INT TERM   # 정리 중 들어온 중단 신호로 정리가 끊기지 않게 합니다.
  "$@" || { log "정리 실패: $*"; (( rc )) || rc=1; }
  exit "$rc"
}
# 정리 명령은 등록할 때 인용해 trap 문자열로 고정합니다.
# shellcheck disable=SC2064
on_exit() { local cmd; printf -v cmd '%q ' "$@"; trap "finish $cmd" EXIT; trap 'exit 130' INT; trap 'exit 143' TERM; }

exp_scale_out() {
  scale_in_cmd user
  SCALE_IN_COUNT=$SCALE_CMD ./bench/bench.sh "$CAS" cas-burst 20 "$RUNS" agentpool=user | csv scale-out.csv "$BENCH_HEADER"
  claim_cmd bench-fixed
  SCALE_IN_COUNT=$SCALE_CMD ./bench/bench.sh "$NAP" nap-burst 20 "$RUNS" bench=fixed | csv scale-out.csv "$BENCH_HEADER"
}
exp_waves() {
  scale_in_cmd user
  SCALE_IN_COUNT=$SCALE_CMD WAVES="5 5 5 5" WAVE_INTERVAL=30 \
    ./bench/bench.sh "$CAS" cas-waves 20 2 agentpool=user | csv scale-out.csv "$BENCH_HEADER"
  claim_cmd bench-fixed
  SCALE_IN_COUNT=$SCALE_CMD WAVES="5 5 5 5" WAVE_INTERVAL=30 \
    ./bench/bench.sh "$NAP" nap-waves 20 2 bench=fixed | csv scale-out.csv "$BENCH_HEADER"
}
exp_large() { # 6 vCPU Pod: CAS D4 풀은 확장하지 못하고 NAP flex는 큰 VM을 고릅니다.
  CPU=6 TIMEOUT=150 ./bench/bench.sh "$CAS" cas-large 4 1 agentpool=user | csv scale-out.csv "$BENCH_HEADER"
  CPU=6 ./bench/bench.sh "$NAP" nap-large 4 1 bench=flex | csv scale-out.csv "$BENCH_HEADER"
}
exp_dealloc() ( # 1회차는 새 VM, 2회차부터 할당 해제한 VM 재시작
  on_exit del_pool userdea
  add_pool userdea --node-vm-size Standard_D4ds_v7 --max-count 10 --node-osdisk-type Managed --scale-down-mode Deallocate
  ./bench/bench.sh "$CAS" cas-dealloc 20 "$RUNS" agentpool=userdea | csv scale-out.csv "$BENCH_HEADER"
)
exp_azurelinux() (
  on_exit del_pool userazl
  add_pool userazl --node-vm-size Standard_D4ds_v7 --max-count 10 --os-sku AzureLinux
  ./bench/bench.sh "$CAS" cas-azl 20 2 agentpool=userazl | csv scale-out.csv "$BENCH_HEADER"
  del_pool userazl
  nap_apply manifests/nodepool-azurelinux.yaml
  ./bench/bench.sh "$NAP" nap-azl 20 2 bench=azl | csv scale-out.csv "$BENCH_HEADER"
)
exp_overprovision() { # overprovision.sh는 header를 직접 출력하므로 첫 줄을 떼고 붙입니다.
  ./bench/overprovision.sh "$CAS" cas-overprov agentpool=user 2 | tail -n +2 | csv overprovisioning.csv scenario,run,pods_ready_s,placeholder_rescheduled_s
  ./bench/overprovision.sh "$NAP" nap-overprov bench=fixed 2 | tail -n +2 | csv overprovisioning.csv scenario,run,pods_ready_s,placeholder_rescheduled_s
}
undo_quota_fallback() {
  local rc=0
  nap_delete manifests/nodepool-quota-fallback.yaml || rc=1
  del_pool big || rc=1
  azop aks nodepool update -g "$RG" --cluster-name "$CAS" -n user --labels "" -o none || rc=1
  profile expander=random || rc=1
  return "$rc"
}
exp_quota_fallback() (
  # 리전·계열 quota를 넘는 Standard_D96ds_v7을 1순위, Standard_D4ds_v7을 대체로 둡니다(구독 quota에 따라 결과가 달라짐).
  on_exit undo_quota_fallback
  profile expander=priority
  azop aks nodepool update -g "$RG" --cluster-name "$CAS" -n user --labels bench=q -o none
  add_pool big --node-vm-size Standard_D96ds_v7 --labels bench=q --max-count 2
  k "$CAS" apply -f manifests/cas-priority-expander.yaml >/dev/null
  nap_apply manifests/nodepool-quota-fallback.yaml
  ./bench/bench.sh "$CAS" cas-quota 20 2 bench=q >/dev/null
  ./bench/bench.sh "$NAP" nap-quota 20 2 bench=q >/dev/null
  for r in 1 2; do
    python3 bench/fallback.py "$OUT/cas-quota/run$r" cas-quota "$r" aks-user
    python3 bench/fallback.py "$OUT/nap-quota/run$r" nap-quota "$r" fallback
  done | csv quota-fallback.csv scenario,run,preferred_attempt_s,preferred_failure_s,fallback_decision_s,first_node_ready_s,all_pods_ready_s,note
)
undo_mixed() {
  local rc=0 p
  for p in mixgen mixmem mixcpu; do del_pool "$p" || rc=1; done
  profile expander=random || rc=1
  return "$rc"
}
exp_mixed() (
  h=scenario,run,ready_big,ready_mem,ready_small,all_ready_s,nodes,skus,vcpu_alloc,mem_alloc_gib,cpu_request_ratio,mem_request_ratio,usd_per_hour
  on_exit undo_mixed
  profile expander=random
  add_pool mixgen --node-vm-size Standard_D4as_v7 --labels bench=mix --max-count 10
  TIMEOUT=420 ./bench/mixed.sh "$CAS" cas-one-pool bench=mix 1 | csv mixed-shapes.csv "$h"
  add_pool mixmem --node-vm-size Standard_E4as_v7 --labels bench=mix --max-count 10
  add_pool mixcpu --node-vm-size Standard_F8as_v7 --labels bench=mix --max-count 10
  ./bench/mixed.sh "$CAS" cas-three-pools-random bench=mix 2 | csv mixed-shapes.csv "$h"
  profile expander=least-waste
  ./bench/mixed.sh "$CAS" cas-three-pools-least-waste bench=mix 2 | csv mixed-shapes.csv "$h"
  for p in mixgen mixmem mixcpu; do del_pool "$p"; done
  nap_apply manifests/nodepool-mixed.yaml
  ./bench/mixed.sh "$NAP" nap-def-v7 bench=mix 2 | csv mixed-shapes.csv "$h"
)
exp_rightsize() ( # 20 → 3 Pod, 12분 관찰
  on_exit del_pool big32
  add_pool big32 --node-vm-size Standard_D32als_v7 --max-count 2
  ./bench/rightsize.sh "$NAP" nap-flex bench=flex > "$OUT/rightsize-nap-flex.csv"
  ./bench/rightsize.sh "$CAS" cas-d4 agentpool=user > "$OUT/rightsize-cas-d4.csv"
  ./bench/rightsize.sh "$CAS" cas-d32 agentpool=big32 > "$OUT/rightsize-cas-d32.csv"
)
exp_zone1() (
  on_exit del_pool userz1
  add_pool userz1 --node-vm-size Standard_D4ds_v7 --max-count 10 --zones 1
  sed "s/eastus2-1/${LOC}-1/" manifests/nodepool-zone1.yaml | k "$NAP" apply -f - >/dev/null
  ./bench/bench.sh "$CAS" cas-zone1 20 "$RUNS" agentpool=userz1 | csv zone1-burst.csv "$BENCH_HEADER"
  ./bench/bench.sh "$NAP" nap-zone1 20 "$RUNS" bench=zone1 | csv zone1-burst.csv "$BENCH_HEADER"
)
undo_burst40() { # 풀을 지우고 balance-similar-node-groups를 기본값 false로 되돌립니다.
  local rc=0 p
  for p in d2 d2b d2c d2d; do del_pool "$p" || rc=1; done
  profile balance-similar-node-groups=false || rc=1
  return "$rc"
}
exp_burst40() ( # 2 vCPU VM 40대. VMSS 10대 제한 정책을 피하려고 CAS는 max 10 풀 4개를 균형 확장
  on_exit undo_burst40
  for p in d2 d2b d2c d2d; do add_pool "$p" --node-vm-size Standard_D2ds_v7 --labels bench=d2x --max-count 10; done
  profile balance-similar-node-groups=true
  nap_apply manifests/nodepool-d2.yaml
  ./bench/bench.sh "$CAS" cas-d2x40 40 1 bench=d2x | csv burst-40-nodes.csv "$BENCH_HEADER"
  ./bench/bench.sh "$NAP" nap-d2x40 40 1 bench=d2 | csv burst-40-nodes.csv "$BENCH_HEADER"
)
exp_quota_staleness() {
  # 실험 전 사용량은 정수 하나로 읽힐 때만 씁니다. 조회 실패·빈 값으로 실험을 시작하지 않습니다.
  local base
  base=$(azq vm list-usage -l "$LOC" --query "[?name.value=='StandardDdsv7Family'].currentValue" -o tsv)
  [[ $base =~ ^[0-9]+$ ]] || { log "StandardDdsv7Family 사용량을 정수 하나로 읽지 못했습니다: ${base}"; return 1; }
  BASELINE_USAGE=$base ./bench/quota-staleness.sh "$NAP" "$CAS" "$LOC" > "$OUT/quota-staleness.csv"
}
exp_migration() { # in-place.sh가 probe(web 6 replica + client)를 배포하고 경로 1을 실행합니다.
  ./migrate/in-place.sh | tee "$OUT/migration.log"
  k "$CAS" -n migrate logs deploy/client > "$OUT/migration-probe.log"
}
exp_drift() { # migration 뒤 NAP drift로 노드 전체 교체. preStop 없음 → preStop.sleep 10s 순서
  local ctx=$CAS
  # client는 system 풀(nodeSelector)에 있어 NAP NodePool drift 대상이 아닙니다. 그래도 교체·재시작되면
  # deploy/client 로그가 현재 컨테이너만 보여 요청 수가 빠지므로 UID:restartCount로 확인합니다.
  # web·client는 컨테이너가 하나뿐이므로(migrate/probe.yaml) 아래 [0]은 그 컨테이너입니다.
  client_id() {
    k "$ctx" -n migrate get pods -l app=client \
      -o jsonpath='{range .items[*]}{.metadata.uid}:{.status.containerStatuses[0].restartCount}{"\n"}{end}'
  }
  # rollout status는 자체 --timeout까지 watch하므로 요청 제한을 그보다 길게 둡니다.
  web_rollout() { kubectl --context "$ctx" --request-timeout=16m -n migrate rollout status deploy/web --timeout=15m >/dev/null; }
  drift_round() { # drift_round <label 값> <결과 이름>
    local start client0 client1 row old end
    client0=$(client_id) || return 1
    [[ -n $client0 ]] || { log "drift $1: client Pod가 없습니다"; return 1; }
    # patch 직전 시각입니다. client 로그를 이 시각부터 셉니다.
    start=$(date -u +%FT%TZ)
    # patch 직전에 있던 대상 NodePool의 NodeClaim 이름을 교체 대상으로 기록합니다. 조회 실패는 실패로 봅니다.
    old=$(k "$ctx" get nodeclaims -l karpenter.sh/nodepool=default \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}') || return 1
    # 교체할 NodeClaim이 없으면 drift가 측정되지 않으므로 patch 전에 실패로 끝내고 drift.csv에 기록하지 않습니다.
    [[ -n ${old//[[:space:]]/} ]] || { log "drift $1: 교체할 default NodeClaim이 없습니다. drift.csv에 기록하지 않음"; return 1; }
    k "$ctx" patch nodepool default --type merge \
      -p "{\"spec\":{\"template\":{\"metadata\":{\"labels\":{\"rotation\":\"$1\"}}}}}" >/dev/null || return 1
    log "drift $1 시작"
    old_gone() { # patch 전 NodeClaim이 모두 사라지면 성공. 조회에 실패하면 nonzero로 반환해 완료로 오인하지 않습니다.
      local cur left
      cur=$(k "$ctx" get nodeclaims -l karpenter.sh/nodepool=default \
        -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}') || return 1
      left=$(awk 'NR == FNR { if ($0 != "") o[$0] = 1; next } ($0 in o) { n++ } END { print n + 0 }' \
        <(printf '%s\n' "$old") <(printf '%s\n' "$cur")) || return 1
      [[ $left == 0 ]]
    }
    wait_until 3600 15 old_gone || { log "drift $1: 60분 안에 교체가 끝나지 않았습니다"; return 1; }
    web_rollout || return 1
    end=$(date -u +%FT%TZ)
    row=$(k "$ctx" -n migrate logs deploy/client --since-time="$start" |
      awk -v s="$start" -v e="$end" -v n="$2" '$1>=s && $1<=e {t++; if ($2!="200") f++} END {printf "%s,%s,%s,%d,%d\n", n, s, e, t, f}') || return 1
    # client가 바뀌었거나 확인하지 못하면 불완전한 행을 drift.csv에 남기지 않고 경고와 함께 실패로 끝냅니다.
    client1=$(client_id) || client1="unknown"
    if [[ $client1 != "$client0" ]]; then
      log "WARNING drift $1: client Pod 교체·재시작으로 결과 불완전(${client0} → ${client1}). drift.csv에 기록하지 않음: ${row}"
      return 1
    fi
    echo "$row"
  }
  # 이전 실행에서 남은 preStop을 지우고 rollout이 끝난 뒤 시작합니다. 조회 실패는 lifecycle 없음으로 보지 않습니다.
  local lifecycle
  lifecycle=$(k "$ctx" -n migrate get deploy web -o jsonpath='{.spec.template.spec.containers[0].lifecycle}') || return 1
  if [[ -n $lifecycle ]]; then
    k "$ctx" -n migrate patch deploy web --type json \
      -p '[{"op":"remove","path":"/spec/template/spec/containers/0/lifecycle"}]' >/dev/null
    web_rollout
  fi
  drift_round "r1-$(date +%s)" drift-no-prestop | csv drift.csv round,start,end,requests,failed
  # preStop을 먼저 적용하고 rollout이 끝난 뒤 drift를 시작해야 두 조건이 섞이지 않습니다.
  k "$ctx" -n migrate patch deploy web --type strategic -p \
    '{"spec":{"template":{"spec":{"containers":[{"name":"podinfo","lifecycle":{"preStop":{"sleep":{"seconds":10}}}}]}}}}' >/dev/null
  web_rollout
  drift_round "r2-$(date +%s)" drift-prestop-10s | csv drift.csv round,start,end,requests,failed
}

# 이름을 모두 확인한 뒤 실행합니다. 뒤쪽 이름이 틀려 앞 실험만 실행되고 끝나지 않게 합니다.
# migration은 CAS 클러스터에 NAP를 켜므로 그 뒤에는 migration 이후가 전제인 drift만 올 수 있습니다.
read -r -a exps <<<"${list//,/ }"
migrated=0 uses_cas=0
for e in "${exps[@]}"; do
  declare -F "exp_${e//-/_}" >/dev/null || { echo "알 수 없는 실험: ${e}" >&2; exit 1; }
  if (( migrated )) && [[ $e != drift ]]; then
    echo "migration 뒤에는 drift만 실행할 수 있습니다: ${e}. CAS 실험을 migration 앞에 두세요" >&2; exit 1
  fi
  [[ $e == migration ]] && migrated=1
  [[ $e == migration || $e == drift ]] || uses_cas=1
done
# 이전 실행에서 이미 migration을 했다면 CAS 클러스터는 더 이상 CAS 결과를 낼 수 없습니다.
if (( uses_cas )); then
  mode=$(azq aks show -g "$RG" -n "$CAS" --query nodeProvisioningProfile.mode -o tsv) || exit 1
  [[ $mode != Auto ]] || { echo "${CAS}에 NAP가 이미 켜져 있어 CAS 실험을 실행할 수 없습니다" >&2; exit 1; }
fi
mkdir -p "$OUT"
# 실패한 이전 실행이 남긴 미확정 결과는 버립니다.
rm -f "$OUT"/*.pending
for e in "${exps[@]}"; do
  log "실험 $e 시작"; "exp_${e//-/_}"; commit_csv; log "실험 $e 완료"
done
echo "결과: $OUT"
