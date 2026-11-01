#!/usr/bin/env bash
# 사용법: quota-staleness.sh [nap-context] [cas-context] [region]
#   생략한 인수는 NAP_CLUSTER_NAME, CAS_CLUSTER_NAME, AZURE_LOCATION을 씁니다(context 이름 = 클러스터 이름).
#   BASELINE_USAGE  실험 전 StandardDdsv7Family 사용량(두 클러스터 시스템 풀 합계). 필수
#   PROBE_TIMEOUT=300  NAP NodeClaim 선택을 기다릴 최대 시간(초). 넘으면 실패로 종료
#                      확인용 Pod 20개가 모두 노드에 배정되거나 지정(nominated)되고 NodeClaim 목록이 두 번 연속 같아야 선택으로 봅니다.
#   STRICT=0           1이면 사전 조건(대조군 pref64, 점유 중 alt)이 맞지 않을 때 끝에서 실패로 종료.
#                      기본 0은 경고와 precondition 열만 남깁니다(공개 실행의 대조군은 alt를 골랐음).
# 반납 뒤 1200초 안에 pref64가 나오지 않으면 timeout 행(censored)을 남기고 실패로 종료합니다.
# 반납 뒤 probe가 실패하면 그 회차는 기록하지 않고 1200초 기한 안에서 다시 시도합니다.
# 1) 대조군: NAP가 pref64(D64ds_v7)를 고르는지 확인
# 2) CAS user 풀(D4ds_v7) 노드 6대로 Ddsv7 계열 quota를 점유하고 11분 대기 → NAP가 alt로 바꾸는지 확인
# 3) 점유 해제 직후부터 60초마다 NAP 선택을 확인해 pref64로 돌아오기까지 걸린 시간을 기록
# 확인용 NodeClaim은 선택 결과만 본 뒤 바로 삭제합니다.
set -euo pipefail
NAP=${1:-${NAP_CLUSTER_NAME:?nap-context 인수 또는 NAP_CLUSTER_NAME이 필요합니다}}
CAS=${2:-${CAS_CLUSTER_NAME:?cas-context 인수 또는 CAS_CLUSTER_NAME이 필요합니다}}
REGION=${3:-${AZURE_LOCATION:?region 인수 또는 AZURE_LOCATION이 필요합니다}}
BASELINE_USAGE=${BASELINE_USAGE:?BASELINE_USAGE(실험 전 StandardDdsv7Family 사용량)가 필요합니다}
PROBE_TIMEOUT=${PROBE_TIMEOUT:-300} STRICT=${STRICT:-0}
[[ $BASELINE_USAGE =~ ^[0-9]+$ ]] || { echo "BASELINE_USAGE는 정수여야 합니다: $BASELINE_USAGE" >&2; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
log() { echo "[$(date -u +%T)] $*" >&2; }
fam() { # 조회 실패나 정수가 아닌 출력은 nonzero
  local v
  v=$(az vm list-usage -l "$REGION" -o tsv --query "[?name.value=='StandardDdsv7Family'].currentValue") || return 1
  [[ $v =~ ^[0-9]+$ ]] || return 1
  echo "$v"
}
usage() { fam || echo unknown; }   # 기록용. 실패를 0으로 남기지 않습니다.

# 실패·중단으로 끝나도 quota를 점유하는 CAS 소비용 Pod와 NAP 확인용 Pod를 0으로 되돌립니다.
# 첫 리소스 변경과 첫 probe 전에 등록합니다. CAS는 소비용 Pod를 배포한 뒤에만 되돌립니다.
cas_used=0
cleanup() {
  if (( cas_used )); then
    kubectl --context "$CAS" -n bench scale deployment inflate --replicas 0 >/dev/null 2>&1 || log "cleanup failed: CAS inflate"
  fi
  kubectl --context "$NAP" -n bench scale deployment inflate --replicas 0 >/dev/null 2>&1 || log "cleanup failed: NAP inflate"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

kubectl --context "$NAP" apply -f "$HERE/../manifests/inflate.yaml" -f "$HERE/../manifests/nodepool-quota-staleness.yaml" >/dev/null
kubectl --context "$NAP" -n bench patch deployment inflate --type strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"pause","resources":{"requests":{"cpu":"1","memory":"1Gi"}}}]}}}}' >/dev/null
kubectl --context "$NAP" -n bench patch deployment inflate --type json -p \
  '[{"op":"add","path":"/spec/template/spec/nodeSelector","value":{"bench":"stale"}}]' >/dev/null

claims() { # 대상 NodePool의 NodeClaim을 "<개수> <NodePool>;" 목록으로 출력. 조회 실패는 nonzero
  local out
  out=$(kubectl --context "$NAP" get nodeclaims -l 'karpenter.sh/nodepool in (pref64,alt)' \
    -o jsonpath='{range .items[*]}{.metadata.labels.karpenter\.sh/nodepool}{"\n"}{end}') || return 1
  [[ -z $out ]] || sort <<<"$out" | uniq -c | tr -s ' ' | tr '\n' ';'
}

PROBE_PODS=20
unplaced() { # 확인용 Pod 중 노드 배정(spec.nodeName·status.nominatedNodeName)도 Karpenter Nominated 이벤트도 없는 Pod 수.
  # 아직 생성되지 않은 Pod(PROBE_PODS 미달분)도 셉니다. 삭제 중인 Pod는 제외하고, 조회 실패는 nonzero
  local pods nominated
  pods=$(kubectl --context "$NAP" -n bench get pods -l app=inflate \
    -o jsonpath='{range .items[*]}{.metadata.name}|{.metadata.deletionTimestamp}|{.spec.nodeName}|{.status.nominatedNodeName}{"\n"}{end}') || return 1
  nominated=$(kubectl --context "$NAP" -n bench get events --field-selector reason=Nominated,involvedObject.kind=Pod \
    -o jsonpath='{range .items[*]}{.involvedObject.name}{"\n"}{end}') || return 1
  awk -F'|' -v want="$PROBE_PODS" 'NR == FNR { nom[$1] = 1; next }
    $1 != "" && $2 == "" { n++; if ($3 == "" && $4 == "" && !($1 in nom)) u++ }
    END { print u + (n < want ? want - n : 0) }' <(echo "$nominated") <(echo "$pods")
}

drop_claims() { # 확인용 NodeClaim을 삭제하고 사라질 때까지(최대 900초) 기다립니다. 남으면 nonzero
  local left start
  kubectl --context "$NAP" delete nodeclaims -l 'karpenter.sh/nodepool in (pref64,alt)' --wait=false >/dev/null 2>&1 || true
  start=$(date +%s)
  until left=$(kubectl --context "$NAP" get nodeclaims -l 'karpenter.sh/nodepool in (pref64,alt)' --no-headers) && [[ -z $left ]]; do
    (( $(date +%s) - start <= 900 )) || { log "timeout: probe NodeClaims not deleted within 900s"; return 1; }
    sleep 5
  done
}

probe() { # 출력: "<선택을 읽은 epoch 초> <선택된 NodePool 목록>"
  # 이전 probe·실행에서 남은 Pod나 pref64/alt NodeClaim이 있으면 이번 선택과 섞이므로 먼저 비웁니다. 정리에 실패하면 probe를 시작하지 않습니다.
  kubectl --context "$NAP" -n bench scale deployment inflate --replicas 0 >/dev/null || { log "probe: scale to 0 failed"; return 1; }
  drop_claims || { log "probe: leftover pref64/alt NodeClaims; not starting probe"; return 1; }
  kubectl --context "$NAP" -n bench scale deployment inflate --replicas "$PROBE_PODS" >/dev/null
  # 배정·지정되지 않은 Pod가 0개이고 NodeClaim 목록이 두 번 연속 같을 때까지 기다립니다.
  # 일부 Pod만 반영된 중간 선택을 기록하지 않습니다. timeout이면 빈 결과를 기록하지 않고 실패합니다.
  local pools="" prev="" left seen start
  start=$(date +%s)
  while :; do
    sleep 5
    pools=$(claims) || pools=""
    left=$(unplaced) || left=unknown
    if [[ -n $pools && $pools == "$prev" && $left == 0 ]]; then break; fi
    prev=$pools
    if (( $(date +%s) - start > PROBE_TIMEOUT )); then
      log "timeout: pref64/alt NodeClaim selection not stable within ${PROBE_TIMEOUT}s (unplaced pods: ${left})"
      kubectl --context "$NAP" -n bench scale deployment inflate --replicas 0 >/dev/null || true
      drop_claims || true   # timeout 전에 생긴 NodeClaim도 정상 경로와 같이 정리합니다.
      return 1
    fi
  done
  seen=$(date +%s)
  kubectl --context "$NAP" -n bench scale deployment inflate --replicas 0 >/dev/null
  drop_claims || return 1
  echo "$seen $pools"
}

pool_set() { # 선택 결과의 NodePool 집합(예: pref64, alt, alt+pref64). 없으면 빈 값
  grep -oE 'pref64|alt' <<<"$1" | sort -u | paste -sd+ - || true
}
precondition_failed=0
check() { # check <phase> <기대 NodePool> <chosen>: 결과를 pc에 ok 또는 failed(...)로 남깁니다.
  local got
  got=$(pool_set "$3")
  if [[ $got == "$2" ]]; then pc=ok; return; fi
  pc="failed($1 chose ${got:-none})"
  precondition_failed=1
  log "WARNING: precondition $pc, expected $2"
}

echo "phase,elapsed_s,ddsv7_usage,chosen,precondition"   # elapsed_s: 반납 시점부터 NodePool 선택을 읽은 시각까지
r=$(probe); check control pref64 "${r#* }"; echo "control,,$(usage),${r#* },$pc"

cas_used=1
kubectl --context "$CAS" apply -f "$HERE/../manifests/inflate.yaml" >/dev/null
kubectl --context "$CAS" -n bench patch deployment inflate --type strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"pause","resources":{"requests":{"cpu":"1","memory":"1Gi"}}}]}}}}' >/dev/null
kubectl --context "$CAS" -n bench patch deployment inflate --type json -p \
  '[{"op":"add","path":"/spec/template/spec/nodeSelector","value":{"agentpool":"user"}}]' >/dev/null
kubectl --context "$CAS" -n bench scale deployment inflate --replicas 18 >/dev/null
kubectl --context "$CAS" -n bench rollout status deployment/inflate --timeout=15m >/dev/null
log "consumer nodes ready; Ddsv7 usage $(usage). waiting 11 minutes for NAP quota refresh"
sleep 660
r=$(probe); check consumed alt "${r#* }"; echo "consumed,,$(usage),${r#* },$pc"

kubectl --context "$CAS" -n bench scale deployment inflate --replicas 0 >/dev/null
log "waiting for consumer VMs to be deleted"
# 조회에 성공한 정수 값만 비교합니다. 실패는 재시도하고 30분 안에 반납되지 않으면 실패로 종료합니다.
wait_start=$(date +%s)
until cur=$(fam) && (( cur <= BASELINE_USAGE )); do
  (( $(date +%s) - wait_start <= 1800 )) || { log "timeout: Ddsv7 usage not back to $BASELINE_USAGE"; exit 1; }
  sleep 15
done
rel=$(date +%s); log "released; Ddsv7 usage $cur"
found=0
while (( $(date +%s) - rel <= 1200 )); do
  # probe 실패는 기록하지 않고 기한 안에서 다시 시도합니다. 기한을 넘기면 아래 timeout 행으로 끝납니다.
  if ! r=$(probe); then log "WARNING: probe failed after release; retrying"; sleep 45; continue; fi
  chosen=${r#* }; el=$(( ${r%% *} - rel ))
  echo "released,$el,$(usage),$chosen,"
  # 선택을 읽은 시각이 1200초를 넘었으면 pref64여도 기한 안 복귀로 보지 않고 timeout(censored)으로 남깁니다.
  (( el <= 1200 )) || break
  # 대조군과 같이 NodePool 집합이 정확히 pref64일 때만 복귀로 봅니다(alt와 섞이면 아님).
  [[ $(pool_set "$chosen") == pref64 ]] && { found=1; break; }
  sleep 45
done
if (( ! found )); then
  echo "timeout,1200,$(usage),censored,"
  log "timeout: pref64 not chosen within 1200s after release (censored)"
  exit 1
fi
if (( precondition_failed )) && [[ $STRICT == 1 ]]; then
  log "STRICT=1: precondition failed"
  exit 1
fi
