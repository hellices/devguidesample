#!/usr/bin/env bash
# 사용법: quota-staleness.sh <nap-context> <cas-context> <region>
# 1) 대조군: NAP가 pref64(D64ds_v7)를 고르는지 확인
# 2) CAS user 풀(D4ds_v7) 노드 6대로 Ddsv7 계열 quota를 점유하고 11분 대기 → NAP가 alt로 바꾸는지 확인
# 3) 점유 해제 직후부터 60초마다 NAP 선택을 확인해 pref64로 돌아오기까지 걸린 시간을 기록
# 확인용 NodeClaim은 선택 결과만 본 뒤 바로 삭제합니다.
set -euo pipefail
NAP=$1 CAS=$2 REGION=$3
HERE=$(cd "$(dirname "$0")" && pwd)
log() { echo "[$(date -u +%T)] $*" >&2; }
fam() { az vm list-usage -l "$REGION" -o tsv --query "[?name.value=='StandardDdsv7Family'].currentValue"; }

kubectl --context "$NAP" apply -f "$HERE/../manifests/inflate.yaml" -f "$HERE/../manifests/nodepool-quota-staleness.yaml" >/dev/null
kubectl --context "$NAP" -n bench patch deployment inflate --type strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"pause","resources":{"requests":{"cpu":"1","memory":"1Gi"}}}]}}}}' >/dev/null
kubectl --context "$NAP" -n bench patch deployment inflate --type json -p \
  '[{"op":"add","path":"/spec/template/spec/nodeSelector","value":{"bench":"stale"}}]' >/dev/null

probe() { # 출력: "<선택을 읽은 epoch 초> <선택된 NodePool 목록>"
  kubectl --context "$NAP" -n bench scale deployment inflate --replicas 20 >/dev/null
  sleep 15
  local pools seen
  seen=$(date +%s)
  pools=$(kubectl --context "$NAP" get nodeclaims -o jsonpath='{range .items[*]}{.metadata.labels.karpenter\.sh/nodepool}{"\n"}{end}' | sort | uniq -c | tr -s ' ' | tr '\n' ';')
  kubectl --context "$NAP" -n bench scale deployment inflate --replicas 0 >/dev/null
  kubectl --context "$NAP" delete nodeclaims -l 'karpenter.sh/nodepool in (pref64,alt)' --wait=false >/dev/null 2>&1 || true
  until [[ -z $(kubectl --context "$NAP" get nodeclaims -l 'karpenter.sh/nodepool in (pref64,alt)' --no-headers 2>/dev/null) ]]; do sleep 5; done
  echo "$seen $pools"
}

echo "phase,elapsed_s,ddsv7_usage,chosen"   # elapsed_s: 반납 시점부터 NodePool 선택을 읽은 시각까지
r=$(probe); echo "control,,$(fam),${r#* }"

kubectl --context "$CAS" apply -f "$HERE/../manifests/inflate.yaml" >/dev/null
kubectl --context "$CAS" -n bench patch deployment inflate --type strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"pause","resources":{"requests":{"cpu":"1","memory":"1Gi"}}}]}}}}' >/dev/null
kubectl --context "$CAS" -n bench patch deployment inflate --type json -p \
  '[{"op":"add","path":"/spec/template/spec/nodeSelector","value":{"agentpool":"user"}}]' >/dev/null
kubectl --context "$CAS" -n bench scale deployment inflate --replicas 18 >/dev/null
kubectl --context "$CAS" -n bench rollout status deployment/inflate --timeout=15m >/dev/null
log "consumer nodes ready; Ddsv7 usage $(fam). waiting 11 minutes for NAP quota refresh"
sleep 660
r=$(probe); echo "consumed,,$(fam),${r#* }"

kubectl --context "$CAS" -n bench scale deployment inflate --replicas 0 >/dev/null
log "waiting for consumer VMs to be deleted"
until [[ $(fam) -le ${BASELINE_USAGE:-16} ]]; do sleep 15; done  # 두 클러스터 시스템 풀(D4ds_v7 × 4)
rel=$(date +%s); log "released; Ddsv7 usage $(fam)"
while (( $(date +%s) - rel <= 1200 )); do
  r=$(probe); chosen=${r#* }
  echo "released,$(( ${r%% *} - rel )),$(fam),$chosen"
  [[ $chosen == *pref64* ]] && break
  sleep 45
done
