#!/usr/bin/env bash
# 사용법: quota-staleness.sh [nap-context] [cas-context] [region]
#   생략한 인수는 NAP_CLUSTER_NAME, CAS_CLUSTER_NAME, AZURE_LOCATION을 씁니다(context 이름 = 클러스터 이름).
#   BASELINE_USAGE  실험 전 StandardDdsv7Family 사용량(두 클러스터 시스템 풀 합계). 필수
#   PROBE_TIMEOUT=300  NAP NodeClaim 선택을 기다릴 최대 시간(초). 넘으면 실패로 종료
#                      확인용 Pod 20개가 모두 노드에 배정되거나 이번 probe의 Nominated 이벤트로 살아 있는 NodeClaim에
#                      지정되고 NodeClaim 목록이 두 번 연속 같아야 선택으로 봅니다.
#   STRICT=0           1이면 사전 조건(대조군 pref64, 점유 중 alt)이 맞지 않을 때 끝에서 실패로 종료.
#                      기본 0은 경고와 precondition 열만 남깁니다(공개 실행의 대조군은 alt를 골랐음).
# 반납 뒤 1200초 안(elapsed_s < 1200)에 pref64가 나오지 않으면 timeout 행(censored)을 남기고 실패로 종료합니다.
# 반납 뒤 probe가 실패하면 그 회차는 기록하지 않고 1200초 기한 안에서 다시 시도합니다.
# 1) 대조군: NAP가 pref64(D64ds_v7)를 고르는지 확인
# 2) CAS user 풀(D4ds_v7) 노드 6대로 Ddsv7 계열 quota를 점유하고 11분 대기 → NAP가 alt로 바꾸는지 확인
# 3) 점유 해제 직후부터 확인 사이에 45초씩 쉬며 NAP 선택을 확인해 pref64로 돌아오기까지 걸린 시간을 기록
# 확인용 NodeClaim은 선택 결과만 본 뒤 바로 삭제합니다.
set -euo pipefail
NAP=${1:-${NAP_CLUSTER_NAME:?nap-context 인수 또는 NAP_CLUSTER_NAME이 필요합니다}}
CAS=${2:-${CAS_CLUSTER_NAME:?cas-context 인수 또는 CAS_CLUSTER_NAME이 필요합니다}}
REGION=${3:-${AZURE_LOCATION:?region 인수 또는 AZURE_LOCATION이 필요합니다}}
BASELINE_USAGE=${BASELINE_USAGE:?BASELINE_USAGE(실험 전 StandardDdsv7Family 사용량)가 필요합니다}
PROBE_TIMEOUT=${PROBE_TIMEOUT:-300} STRICT=${STRICT:-0}
HERE=$(cd "$(dirname "$0")" && pwd)
source "$HERE/lib.sh"
# Azure·클러스터를 호출하기 전에 입력을 모두 확인합니다. 정수는 10진수로 정규화합니다(앞자리 0을 8진수로 읽지 않음).
BASELINE_USAGE=$(int_arg BASELINE_USAGE "$BASELINE_USAGE" 0) || exit 2
PROBE_TIMEOUT=$(int_arg PROBE_TIMEOUT "$PROBE_TIMEOUT" 1) || exit 2
[[ $STRICT == 0 || $STRICT == 1 ]] || { echo "STRICT는 0 또는 1이어야 합니다: ${STRICT}" >&2; exit 2; }
[[ $REGION =~ ^[a-z0-9]+$ ]] || { echo "region은 Azure 리전 이름(소문자·숫자)이어야 합니다: ${REGION}" >&2; exit 2; }
log() { echo "[$(date -u +%T)] $*" >&2; }
kn() { kubectl --context "$NAP" --request-timeout="$KUBE_RT" "$@"; }
kc() { kubectl --context "$CAS" --request-timeout="$KUBE_RT" "$@"; }
fam() { # 조회 실패나 정수 하나가 아닌 출력은 nonzero
  local v
  v=$(azq vm list-usage -l "$REGION" -o tsv --query "[?name.value=='StandardDdsv7Family'].currentValue") || return 1
  [[ $v =~ ^[0-9]+$ ]] || return 1
  echo "$v"
}
usage() { fam || echo unknown; }   # 기록용. 실패를 0으로 남기지 않습니다.

# 실패·중단으로 끝나도 quota를 점유하는 CAS 소비용 Pod와 NAP 확인용 Pod를 0으로 되돌립니다.
# 첫 리소스 변경과 첫 probe 전에 등록합니다. CAS는 소비용 Pod를 배포한 뒤에만 되돌립니다.
cas_used=0
cleanup() {
  if (( cas_used )); then
    kc -n bench scale deployment inflate --replicas 0 >/dev/null || log "cleanup failed: CAS inflate"
  fi
  kn -n bench scale deployment inflate --replicas 0 >/dev/null || log "cleanup failed: NAP inflate"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

kn apply -f "$HERE/../manifests/inflate.yaml" -f "$HERE/../manifests/nodepool-quota-staleness.yaml" >/dev/null
kn -n bench patch deployment inflate --type strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"pause","resources":{"requests":{"cpu":"1","memory":"1Gi"}}}]}}}}' >/dev/null
kn -n bench patch deployment inflate --type json -p \
  '[{"op":"add","path":"/spec/template/spec/nodeSelector","value":{"bench":"stale"}}]' >/dev/null

claims() { # 대상 NodePool의 NodeClaim을 정렬한 "<이름> <NodePool>;" 목록으로 출력. 조회 실패는 nonzero
  # 개수가 같아도 NodeClaim이 교체되면 다른 값이 되도록 이름을 포함해 안정 여부를 비교합니다.
  local out
  out=$(kn get nodeclaims -l 'karpenter.sh/nodepool in (pref64,alt)' \
    -o jsonpath='{range .items[*]}{.metadata.name} {.metadata.labels.karpenter\.sh/nodepool}{"\n"}{end}') || return 1
  [[ -z $out ]] || LC_ALL=C sort <<<"$out" | tr '\n' ';'
}
summary() { # claims 출력을 기록용 "<개수> <NodePool>;" 목록으로 바꿉니다(이전 결과 CSV와 같은 형식).
  [[ -z $1 ]] || tr ';' '\n' <<<"$1" | awk 'NF { print $2 }' | sort | uniq -c | tr -s ' ' | tr '\n' ';'
}

PROBE_PODS=20
PROBE_START=""   # probe()가 확인용 Pod를 늘리기 직전 UTC 시각으로 설정합니다.
unplaced() { # 확인용 Pod 중 노드 배정(spec.nodeName·status.nominatedNodeName)이 없고 지정 이벤트도 없는 Pod 수.
  # Karpenter는 nominatedNodeName을 쓰지 않으므로 Nominated 이벤트를 씁니다. 같은 Pod(uid)를 가리키고, 이번 probe 시작 뒤
  # 발생했고, 메시지의 nodeclaim/<이름>이 지금 살아 있는 pref64/alt NodeClaim일 때만 지정으로 봅니다.
  # 아직 생성되지 않은 Pod(PROBE_PODS 미달분)도 셉니다. 삭제 중인 Pod는 제외하고, 조회 실패는 nonzero
  local pods events live
  pods=$(kn -n bench get pods -l app=inflate \
    -o jsonpath='{range .items[*]}{.metadata.uid}|{.metadata.deletionTimestamp}|{.spec.nodeName}|{.status.nominatedNodeName}{"\n"}{end}') || return 1
  events=$(kn -n bench get events --field-selector reason=Nominated,involvedObject.kind=Pod \
    -o jsonpath='{range .items[*]}{.involvedObject.uid}|{.lastTimestamp}|{.eventTime}|{.message}{"\n"}{end}') || return 1
  live=$(kn get nodeclaims -l 'karpenter.sh/nodepool in (pref64,alt)' \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}') || return 1
  awk -F'|' -v want="$PROBE_PODS" -v start="${PROBE_START:0:19}" '
    FILENAME == ARGV[1] { if ($1 != "") live[$1] = 1; next }
    FILENAME == ARGV[2] {
      t = ($2 ~ /^[0-9]/) ? $2 : $3   # lastTimestamp가 없으면 eventTime
      if ($1 == "" || t !~ /^[0-9]/ || substr(t, 1, 19) < start) next
      if (match($0, /nodeclaim\/[^ ,|]+/) && (substr($0, RSTART + 10, RLENGTH - 10) in live)) nom[$1] = 1
      next
    }
    $1 != "" && $2 == "" { n++; if ($3 == "" && $4 == "" && !($1 in nom)) u++ }
    END { print u + (n < want ? want - n : 0) }' <(echo "$live") <(echo "$events") <(echo "$pods")
}

no_claims() { # pref64/alt NodeClaim이 하나도 없으면 성공. 조회 실패는 nonzero
  local out
  out=$(kn get nodeclaims -l 'karpenter.sh/nodepool in (pref64,alt)' -o name) || return 1
  [[ -z ${out//[[:space:]]/} ]]
}
drop_claims() { # 확인용 NodeClaim을 삭제하고 사라질 때까지(최대 900초) 기다립니다. 남으면 nonzero
  # 삭제 요청이 실패해도 이미 지워졌을 수 있으므로 경고만 남기고 실제로 사라졌는지로 판단합니다.
  kn delete nodeclaims -l 'karpenter.sh/nodepool in (pref64,alt)' --wait=false >/dev/null || log "WARNING: probe NodeClaim 삭제 요청 실패"
  wait_until 900 5 no_claims || { log "timeout: probe NodeClaims not deleted within 900s"; return 1; }
}

probe() { # 출력: "<선택을 읽은 epoch 초> <선택된 NodePool 목록>"
  # 이전 probe·실행에서 남은 Pod나 pref64/alt NodeClaim이 있으면 이번 선택과 섞이므로 먼저 비웁니다. 정리에 실패하면 probe를 시작하지 않습니다.
  kn -n bench scale deployment inflate --replicas 0 >/dev/null || { log "probe: scale to 0 failed"; return 1; }
  drop_claims || { log "probe: leftover pref64/alt NodeClaims; not starting probe"; return 1; }
  # probe는 $(...) 안에서 실행돼 errexit가 적용되지 않으므로 중요한 명령의 실패를 직접 확인합니다.
  PROBE_START=$(date -u +%FT%TZ)
  kn -n bench scale deployment inflate --replicas "$PROBE_PODS" >/dev/null || {
    log "probe: scale to ${PROBE_PODS} failed"; kn -n bench scale deployment inflate --replicas 0 >/dev/null || log "probe: cleanup scale to 0 failed"
    drop_claims || true; return 1; }
  # 배정·지정되지 않은 Pod가 0개이고 NodeClaim 목록이 두 번 연속 같을 때까지 기다립니다.
  # 일부 Pod만 반영된 중간 선택을 기록하지 않습니다. timeout이면 빈 결과를 기록하지 않고 실패합니다.
  # 마감 시각 이후에 끝난 확인은 안정돼도 timeout으로 봅니다. 대기는 남은 시간을 넘기지 않습니다.
  local ids="" prev="" pending rest seen start
  start=$(date +%s)
  while :; do
    rest=$(( start + PROBE_TIMEOUT - $(date +%s) ))
    if (( rest > 0 )); then sleep "$(( rest < 5 ? rest : 5 ))"; fi
    ids=$(claims) || ids=""
    pending=$(unplaced) || pending=unknown
    if (( $(date +%s) - start >= PROBE_TIMEOUT )); then
      log "timeout: pref64/alt NodeClaim selection not stable within ${PROBE_TIMEOUT}s (unplaced pods: ${pending})"
      kn -n bench scale deployment inflate --replicas 0 >/dev/null || log "probe: cleanup scale to 0 failed"
      drop_claims || true   # timeout 전에 생긴 NodeClaim도 정상 경로와 같이 정리합니다.
      return 1
    fi
    if [[ -n $ids && $ids == "$prev" && $pending == 0 ]]; then break; fi
    prev=$ids
  done
  seen=$(date +%s)
  kn -n bench scale deployment inflate --replicas 0 >/dev/null || {
    log "probe: scale to 0 failed"; drop_claims || true; return 1; }
  drop_claims || return 1
  local chosen; chosen=$(summary "$ids") || return 1
  echo "$seen $chosen"
}

pool_set() { # 선택 결과의 NodePool 집합(예: pref64, alt, alt+pref64). 없으면 빈 값
  # ';'로 나눈 항목의 마지막 필드(NodePool label)만 씁니다. NodeClaim 이름(pref64-xxxxx 등)은 보지 않습니다.
  tr ';' '\n' <<<"$1" | awk 'NF { print $NF }' | sort -u | paste -sd+ -
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
kc apply -f "$HERE/../manifests/inflate.yaml" >/dev/null
kc -n bench patch deployment inflate --type strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"pause","resources":{"requests":{"cpu":"1","memory":"1Gi"}}}]}}}}' >/dev/null
kc -n bench patch deployment inflate --type json -p \
  '[{"op":"add","path":"/spec/template/spec/nodeSelector","value":{"agentpool":"user"}}]' >/dev/null
kc -n bench scale deployment inflate --replicas 18 >/dev/null
# rollout status는 자체 --timeout까지 watch하므로 요청 제한을 그보다 길게 둡니다.
kubectl --context "$CAS" --request-timeout=16m -n bench rollout status deployment/inflate --timeout=15m >/dev/null
log "consumer nodes ready; Ddsv7 usage $(usage). waiting 11 minutes for NAP quota refresh"
sleep 660
r=$(probe); check consumed alt "${r#* }"; echo "consumed,,$(usage),${r#* },$pc"

kc -n bench scale deployment inflate --replicas 0 >/dev/null
log "waiting for consumer VMs to be deleted"
# 조회에 성공한 정수 값만 비교합니다. 실패는 재시도하고 30분 안에 반납되지 않으면 실패로 종료합니다.
released() { cur=$(fam) || return 1; (( 10#$cur <= BASELINE_USAGE )); }
wait_until 1800 15 released || { log "timeout: Ddsv7 usage not back to ${BASELINE_USAGE}"; exit 1; }
rel=$(date +%s); log "released; Ddsv7 usage $cur"
# 반납 뒤 1200초 기한: 기한 안(elapsed_s < 1200)에 읽은 선택만 복귀로 인정하고, 대기는 남은 시간을 넘기지 않습니다.
found=0
wait_retry() { local rest=$(( rel + 1200 - $(date +%s) )); if (( rest > 0 )); then sleep "$(( rest < 45 ? rest : 45 ))"; fi; }
while (( $(date +%s) - rel < 1200 )); do
  # probe 실패는 기록하지 않고 기한 안에서 다시 시도합니다. 기한을 넘기면 아래 timeout 행으로 끝납니다.
  if ! r=$(probe); then log "WARNING: probe failed after release; retrying"; wait_retry; continue; fi
  chosen=${r#* }; el=$(( ${r%% *} - rel ))
  echo "released,$el,$(usage),$chosen,"
  # 선택을 읽은 시각이 1200초 이상이면 pref64여도 기한 안 복귀로 보지 않고 timeout(censored)으로 남깁니다.
  (( el < 1200 )) || break
  # 대조군과 같이 NodePool 집합이 정확히 pref64일 때만 복귀로 봅니다(alt와 섞이면 아님).
  got=$(pool_set "$chosen")
  [[ $got == pref64 ]] && { found=1; break; }
  wait_retry
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
