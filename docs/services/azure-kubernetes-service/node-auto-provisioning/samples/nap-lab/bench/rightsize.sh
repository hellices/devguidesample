#!/usr/bin/env bash
# 사용법: rightsize.sh <kube-context> <scenario> <nodeSelector key=value>
#   FROM=20 TO=3      축소 전후 replica 수(Pod당 1 vCPU)
#   WINDOW=720        축소 후 관찰 시간(초)
#   PRICES=<json>     prices.py 출력(생략하면 results/prices-$AZURE_LOCATION.json)
# 축소 후 30초마다 노드 구성·시간당 비용과, 축소 직전에 있던 Pod 외에 새로 생긴 Pod 수(이동 횟수)를 기록합니다.
# 노드 수·vCPU·비용은 selector에 맞는 노드 중 CAS가 VM을 삭제해 NotReady로 남은 객체를 뺀 값입니다(k8sutil.vm_removed).
# 생성 중인 NotReady 노드는 포함합니다. Ready 노드 수는 ready_nodes, 제외한 잔류 객체 수는 removed_nodes 열에 둡니다.
# 가격 파일에 없는 SKU가 있으면 usd_per_hour는 unknown입니다.
# capacity.cpu가 없는 노드가 있으면 vcpu는 unknown입니다.
# 첫 행(기준)은 축소 직전 상태이며 elapsed_s는 축소 시작 기준 0 이하의 실제 오프셋입니다. 이후 행은 축소 시작 뒤 경과 초입니다.
set -euo pipefail
USAGE="사용법: rightsize.sh <kube-context> <scenario> <nodeSelector key=value>"
CTX=${1:?$USAGE} SCENARIO=${2:?$USAGE} SELECTOR=${3:?$USAGE}
FROM=${FROM:-20} TO=${TO:-3} WINDOW=${WINDOW:-720}
HERE=$(cd "$(dirname "$0")" && pwd)
PRICES=${PRICES:-$HERE/../results/prices-${AZURE_LOCATION:?PRICES 또는 AZURE_LOCATION이 필요합니다}.json}
[[ -f $PRICES ]] || { echo "가격 파일이 없습니다: $PRICES (bench/prices.py로 생성)" >&2; exit 1; }
k() { kubectl --context "$CTX" "$@"; }
log() { echo "[$(date -u +%T)] $SCENARIO $*" >&2; }
pods() { k -n bench get pods -l app=inflate -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort; }
node_state() { # "노드수 Ready노드수 잔류객체수 vCPU합 시간당비용 SKU목록"
  k get nodes -l "$SELECTOR" -o json | python3 -c "
import json,sys
sys.path.insert(0, sys.argv[2])
from k8sutil import qty, vm_removed
p=json.load(open(sys.argv[1]))
a=json.load(sys.stdin)['items']
n=[x for x in a if not vm_removed(x)]
r=[x for x in n if any(c['type']=='Ready' and c['status']=='True' for c in x['status'].get('conditions', []))]
s={}
for x in n:
  t=x['metadata']['labels'].get('node.kubernetes.io/instance-type','?'); s[t]=s.get(t,0)+1
usd='unknown' if any(t not in p for t in s) else round(sum(p[t]*c for t,c in s.items()),3)
cpu=[x['status'].get('capacity', {}).get('cpu') for x in n]
vcpu='unknown' if any(v is None for v in cpu) else round(sum(qty(v) for v in cpu))
print(len(n), len(r), len(a)-len(n), vcpu, usd, ' '.join(f'{t}x{c}' for t,c in sorted(s.items())))" "$PRICES" "$HERE"
}

k apply -f "$HERE/../manifests/inflate.yaml" >/dev/null
# 중간 실패·중단에도 inflate를 0으로 되돌립니다. 정리 실패가 원래 종료 상태를 덮지 않습니다.
trap 'k -n bench scale deployment inflate --replicas 0 >/dev/null 2>&1 || log "cleanup failed"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
k -n bench patch deployment inflate --type strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"pause","resources":{"requests":{"cpu":"1","memory":"1Gi"}}}]}}}}' >/dev/null
k -n bench patch deployment inflate --type json -p \
  "[{\"op\":\"add\",\"path\":\"/spec/template/spec/nodeSelector\",\"value\":{\"${SELECTOR%%=*}\":\"${SELECTOR#*=}\"}}]" >/dev/null
k -n bench scale deployment inflate --replicas "$FROM" >/dev/null
k -n bench rollout status deployment/inflate --timeout=20m >/dev/null
sleep 60
echo "elapsed_s,nodes,vcpu,usd_per_hour,skus,pods,moved_pods,ready_nodes,removed_nodes"
# 축소 직전 Pod 집합을 기준으로 삼아, 축소 직후 재생성된 Pod도 이동으로 집계합니다.
# 기준 행의 Pod 수는 FROM이 아니라 실제로 조회한 Pod 수입니다(빈 출력은 0).
base=$(pods); seen="$base"
read -r n ready gone c usd skus < <(node_state)
base_at=$(date +%s)
k -n bench scale deployment inflate --replicas "$TO" >/dev/null
start=$(date +%s)
# 기준 행의 elapsed_s는 기준 측정을 마친 시각에서 축소 명령 완료 시각(start)을 뺀 실제 값입니다(보통 0~-2).
echo "$(( base_at - start )),$n,$c,$usd,$skus,$(grep -c . <<<"$base" || true),0,$ready,$gone"
while :; do
  cur=$(pods); seen=$(printf '%s\n%s\n' "$seen" "$cur" | sort -u)
  moved=$(comm -13 <(echo "$base") <(echo "$seen") | grep -c . || true)
  read -r n ready gone c usd skus < <(node_state)
  echo "$(( $(date +%s) - start )),$n,$c,$usd,$skus,$(echo "$cur" | grep -c .),$moved,$ready,$gone"
  # 관찰 시간을 넘기지 않도록 남은 시간이 30초보다 짧으면 그만큼만 기다립니다.
  left=$(( WINDOW - ($(date +%s) - start) ))
  (( left > 0 )) || break
  sleep $(( left < 30 ? left : 30 ))
done
log "done"
