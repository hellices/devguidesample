#!/usr/bin/env bash
# 사용법: quota-staleness.sh [nap-context] [cas-context] [region]
#   생략한 인수는 NAP_CLUSTER_NAME, CAS_CLUSTER_NAME, AZURE_LOCATION을 씁니다(context 이름 = 클러스터 이름).
#   BASELINE_USAGE  실험 전 StandardDdsv7Family 사용량(두 클러스터 시스템 풀 합계). 필수
#   PROBE_TIMEOUT=300  NAP NodeClaim 선택을 기다릴 최대 시간(초). 넘으면 실패로 종료
# 1) 대조군: NAP가 pref64(D64ds_v7)를 고르는지 확인
# 2) CAS user 풀(D4ds_v7) 노드 6대로 Ddsv7 계열 quota를 점유하고 11분 대기 → NAP가 alt로 바꾸는지 확인
# 3) 점유 해제 직후부터 60초마다 NAP 선택을 확인해 pref64로 돌아오기까지 걸린 시간을 기록
# 확인용 NodeClaim은 선택 결과만 본 뒤 바로 삭제합니다.
set -euo pipefail
NAP=${1:-${NAP_CLUSTER_NAME:?nap-context 인수 또는 NAP_CLUSTER_NAME이 필요합니다}}
CAS=${2:-${CAS_CLUSTER_NAME:?cas-context 인수 또는 CAS_CLUSTER_NAME이 필요합니다}}
REGION=${3:-${AZURE_LOCATION:?region 인수 또는 AZURE_LOCATION이 필요합니다}}
BASELINE_USAGE=${BASELINE_USAGE:?BASELINE_USAGE(실험 전 StandardDdsv7Family 사용량)가 필요합니다}
PROBE_TIMEOUT=${PROBE_TIMEOUT:-300}
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

probe() { # 출력: "<선택을 읽은 epoch 초> <선택된 NodePool 목록>"
  kubectl --context "$NAP" -n bench scale deployment inflate --replicas 20 >/dev/null
  # NodeClaim이 생기고 두 번 연속 같은 결과가 나올 때까지 기다립니다. timeout이면 빈 결과를 기록하지 않고 실패합니다.
  local pools="" prev="" seen start
  start=$(date +%s)
  while :; do
    sleep 5
    if pools=$(claims) && [[ -n $pools && $pools == "$prev" ]]; then break; fi
    prev=$pools
    if (( $(date +%s) - start > PROBE_TIMEOUT )); then
      log "timeout: no NodeClaim for pref64/alt within ${PROBE_TIMEOUT}s"
      kubectl --context "$NAP" -n bench scale deployment inflate --replicas 0 >/dev/null || true
      return 1
    fi
  done
  seen=$(date +%s)
  kubectl --context "$NAP" -n bench scale deployment inflate --replicas 0 >/dev/null
  kubectl --context "$NAP" delete nodeclaims -l 'karpenter.sh/nodepool in (pref64,alt)' --wait=false >/dev/null 2>&1 || true
  until [[ -z $(kubectl --context "$NAP" get nodeclaims -l 'karpenter.sh/nodepool in (pref64,alt)' --no-headers 2>/dev/null) ]]; do sleep 5; done
  echo "$seen $pools"
}

echo "phase,elapsed_s,ddsv7_usage,chosen"   # elapsed_s: 반납 시점부터 NodePool 선택을 읽은 시각까지
r=$(probe); echo "control,,$(usage),${r#* }"

kubectl --context "$CAS" apply -f "$HERE/../manifests/inflate.yaml" >/dev/null
kubectl --context "$CAS" -n bench patch deployment inflate --type strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"pause","resources":{"requests":{"cpu":"1","memory":"1Gi"}}}]}}}}' >/dev/null
kubectl --context "$CAS" -n bench patch deployment inflate --type json -p \
  '[{"op":"add","path":"/spec/template/spec/nodeSelector","value":{"agentpool":"user"}}]' >/dev/null
kubectl --context "$CAS" -n bench scale deployment inflate --replicas 18 >/dev/null
kubectl --context "$CAS" -n bench rollout status deployment/inflate --timeout=15m >/dev/null
log "consumer nodes ready; Ddsv7 usage $(usage). waiting 11 minutes for NAP quota refresh"
sleep 660
r=$(probe); echo "consumed,,$(usage),${r#* }"

kubectl --context "$CAS" -n bench scale deployment inflate --replicas 0 >/dev/null
log "waiting for consumer VMs to be deleted"
# 조회에 성공한 정수 값만 비교합니다. 실패는 재시도하고 30분 안에 반납되지 않으면 실패로 종료합니다.
wait_start=$(date +%s)
until cur=$(fam) && (( cur <= BASELINE_USAGE )); do
  (( $(date +%s) - wait_start <= 1800 )) || { log "timeout: Ddsv7 usage not back to $BASELINE_USAGE"; exit 1; }
  sleep 15
done
rel=$(date +%s); log "released; Ddsv7 usage $cur"
while (( $(date +%s) - rel <= 1200 )); do
  r=$(probe); chosen=${r#* }
  echo "released,$(( ${r%% *} - rel )),$(usage),$chosen"
  [[ $chosen == *pref64* ]] && break
  sleep 45
done
