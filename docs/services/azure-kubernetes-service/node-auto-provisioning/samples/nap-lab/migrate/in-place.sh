#!/usr/bin/env bash
# Path 1 리허설: 모든 풀의 CAS 비활성화 → NAP 활성화 → 고정 user pool을 단계적으로 축소 → 풀 삭제
#   AZURE_RESOURCE_GROUP, CAS_CLUSTER_NAME  필수. kube context 이름은 클러스터 이름과 같습니다(CTX로 변경).
#   POOL=user  축소·삭제할 고정 풀
# probe(web·client)는 이후 drift 실험이 쓰므로 지우지 않습니다. NAP 활성화 전에 실패·중단하면 CAS 설정만 되돌립니다.
# 중단 뒤 다시 실행하면 CAS가 꺼진 풀은 건너뛰고, 남은 노드 수부터 축소하며, 풀이 이미 없으면 축소·삭제를 건너뜁니다.
set -euo pipefail
RG=${AZURE_RESOURCE_GROUP:?AZURE_RESOURCE_GROUP이 필요합니다}
CLUSTER=${CAS_CLUSTER_NAME:?CAS_CLUSTER_NAME이 필요합니다}
POOL=${POOL:-user} CTX=${CTX:-$CLUSTER}
HERE=$(cd "$(dirname "$0")" && pwd)
source "$HERE/../bench/lib.sh"
# 풀 이름은 az 조회식(JMESPath)에 들어가므로 Azure·클러스터를 바꾸기 전에 AKS 노드 풀 이름 규칙으로 확인합니다.
[[ $POOL =~ ^[a-z][a-z0-9]{0,11}$ ]] || { echo "POOL은 소문자로 시작하는 소문자·숫자 12자 이하여야 합니다: ${POOL}" >&2; exit 2; }
k() { kubectl --context "$CTX" --request-timeout="$KUBE_RT" "$@"; }
log() { echo "[$(date -u +%T)] $*"; }
pool_count() { # 풀이 없으면 빈 값, 있으면 노드 수를 출력합니다. 조회 실패나 정수 하나가 아닌 값은 nonzero
  local out
  out=$(azq aks nodepool list -g "$RG" --cluster-name "$CLUSTER" --query "[?name=='$POOL'].count" -o tsv) || return 1
  [[ -z $out || $out =~ ^[0-9]+$ ]] || { log "pool $POOL count is not a single integer: ${out}"; return 1; }
  echo "$out"
}
web_nodes() { # web Pod가 있는 노드별 Pod 수. RESTARTS 열 형식에 영향받지 않도록 nodeName을 직접 읽습니다.
  local out
  out=$(k -n migrate get pods -l app=web -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}') || return 1
  awk 'NF' <<<"$out" | sort | uniq -c
}
web_state=""
web_ready() { # 새 revision의 replica가 모두 Ready·Available이고 전체 Pod 수가 spec과 같으면 성공. 조회 실패는 nonzero
  # 일부 Pod 누락이나 이전 revision Pod(status.replicas > spec.replicas)가 남은 상태로 진행하지 않습니다.
  local gen obs want total updated ready avail
  web_state=$(k -n migrate get deploy web -o jsonpath='{.metadata.generation},{.status.observedGeneration},{.spec.replicas},{.status.replicas},{.status.updatedReplicas},{.status.readyReplicas},{.status.availableReplicas}') || return 1
  IFS=, read -r gen obs want total updated ready avail <<<"$web_state"
  [[ -n $want && $obs == "$gen" && ${total:-0} == "$want" && ${updated:-0} == "$want" && ${ready:-0} == "$want" && ${avail:-0} == "$want" ]]
}
wait_web_ready() { # 15분 제한
  wait_until 900 2 web_ready && return 0
  log "timeout: web not ready (generation,observed,spec,replicas,updated,ready,available=${web_state})"; return 1
}

log "deploy probe"; k apply -f "$HERE/probe.yaml" >/dev/null; wait_web_ready
web_nodes
# client가 요청을 보내 200 응답을 기록하기 전에 바꾸면 전환 중 실패를 측정하지 못하므로, 풀·NAP를 바꾸기 전에 확인합니다.
log "wait for client 200 sample"
# 확인 시작 뒤에 기록된 200 응답만 인정합니다(이전 실행·확인 전 로그의 200으로 통과하지 않게).
client_since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
client_ok() { local out; out=$(k -n migrate logs deploy/client --since-time="$client_since") || return 1; grep -q ' 200$' <<<"$out"; }
wait_until 120 5 client_ok || { log "client 로그에 120초 안에 200 응답이 없습니다. 변경 전에 중단합니다"; exit 1; }

# AllowClusterAutoscalerAndNAP 없이 NAP를 켜려면 CAS가 켜진 풀이 하나도 없어야 합니다.
# 변경 전 각 풀의 min/max를 저장하고, NAP 활성화 전에 실패·중단하면 CAS를 원래 값으로 되돌립니다.
cas_pools=$(azq aks nodepool list -g "$RG" --cluster-name "$CLUSTER" \
  --query "[?enableAutoScaling].[name,minCount,maxCount]" -o tsv)
disabled=""   # "<풀> <min> <max>" 줄 목록. 실패한 변경도 일부 적용됐을 수 있어 호출 전에 기록합니다.
rollback() {
  local rc=$? p min max
  trap '' INT TERM   # 복구 중 들어온 중단 신호로 복구가 끊기지 않게 합니다.
  # NAP 활성화 요청이 실패로 끝나도 실제로는 적용됐을 수 있습니다. NAP가 켜졌거나 확인하지 못하면 CAS를 다시 켜지 않습니다.
  if [[ -n $disabled ]]; then
    local mode
    if ! mode=$(azq aks show -g "$RG" -n "$CLUSTER" --query nodeProvisioningProfile.mode -o tsv); then
      log "rollback skipped: node provisioning mode 조회 실패. CAS를 다시 켜지 않습니다. 풀 상태를 직접 확인하세요"; exit "$rc"
    fi
    if [[ $mode == Auto ]]; then
      log "rollback skipped: NAP(mode Auto)가 켜져 있어 CAS를 다시 켜지 않습니다"; exit "$rc"
    fi
  fi
  while read -r -u 3 p min max; do
    [[ -n $p ]] || continue
    log "rollback: enable cluster autoscaler on $p (min $min, max $max)"
    azop aks nodepool update -g "$RG" --cluster-name "$CLUSTER" -n "$p" --enable-cluster-autoscaler \
      --min-count "$min" --max-count "$max" -o none || log "rollback failed: $p"
  done 3<<<"$disabled"
  exit "$rc"
}
trap rollback EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
while read -r -u 3 p min max; do
  [[ -n $p ]] || continue
  count=$(azq aks nodepool show -g "$RG" --cluster-name "$CLUSTER" -n "$p" --query count -o tsv) || count=unknown
  log "disable cluster autoscaler on $p (count stays ${count})"
  disabled+="$p $min $max"$'\n'
  azop aks nodepool update -g "$RG" --cluster-name "$CLUSTER" -n "$p" --disable-cluster-autoscaler -o none
done 3<<<"$cas_pools"

log "enable NAP"
azop aks update -g "$RG" -n "$CLUSTER" --node-provisioning-mode Auto -o none
trap - EXIT INT TERM   # NAP가 켜졌으므로 이후 실패는 CAS로 되돌리지 않습니다.
log "NAP enabled"; k get nodepools.karpenter.sh

while :; do
  # 조건식 안의 $(pool_count)는 조회 실패가 set -e로 전파되지 않으므로 일반 명령으로 읽습니다.
  count=$(pool_count)
  if [[ -z $count ]]; then log "pool $POOL not found; skip scale-down and delete"; break; fi
  if (( 10#$count == 0 )); then
    log "delete empty pool $POOL"
    azop aks nodepool delete -g "$RG" --cluster-name "$CLUSTER" -n "$POOL" -o none
    break
  fi
  next=$(( 10#$count - 1 ))
  log "scale $POOL to $next"
  azop aks nodepool scale -g "$RG" --cluster-name "$CLUSTER" -n "$POOL" --node-count "$next" -o none
  wait_web_ready
  nodes=$(k get nodes -l karpenter.sh/nodepool -o name)
  n=$(count_matching . <<<"$nodes")
  log "wave done: ${n} NAP nodes"
done

web_nodes
log "done"
