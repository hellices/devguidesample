#!/usr/bin/env bash
# 사용법: rightsize.sh <kube-context> <scenario> <nodeSelector key=value>
#   FROM=20 TO=3      축소 전후 replica 수(Pod당 1 vCPU)
#   WINDOW=720        축소 후 관찰 시간(초)
#   PRICES=<json>     prices.py 출력(생략하면 results/prices-$AZURE_LOCATION.json)
# 축소 후 30초마다 노드 구성·시간당 비용과, 축소 직전에 있던 Pod 외에 새로 생긴 Pod 수(이동 횟수)를 기록합니다.
# 노드 수·vCPU·비용은 Ready 여부와 관계없이 selector에 맞는 전체 노드 기준이고, Ready 노드 수는 ready_nodes 열에 따로 둡니다.
# 가격 파일에 없는 SKU가 있으면 usd_per_hour는 unknown입니다.
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
node_state() { # "노드수 Ready노드수 vCPU합 시간당비용 SKU목록"
  k get nodes -l "$SELECTOR" -o json | python3 -c "
import json,sys
sys.path.insert(0, sys.argv[2])
from k8sutil import qty
p=json.load(open(sys.argv[1]))
n=json.load(sys.stdin)['items']
r=[x for x in n if any(c['type']=='Ready' and c['status']=='True' for c in x['status'].get('conditions', []))]
s={}
for x in n:
  t=x['metadata']['labels'].get('node.kubernetes.io/instance-type','?'); s[t]=s.get(t,0)+1
usd='unknown' if any(t not in p for t in s) else round(sum(p[t]*c for t,c in s.items()),3)
print(len(n), len(r), round(sum(qty(x['status']['capacity']['cpu']) for x in n)), usd, ' '.join(f'{t}x{c}' for t,c in sorted(s.items())))" "$PRICES" "$HERE"
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
echo "elapsed_s,nodes,vcpu,usd_per_hour,skus,pods,moved_pods,ready_nodes"
read -r n ready c usd skus < <(node_state); echo "-60,$n,$c,$usd,$skus,$FROM,0,$ready"

# 축소 직전 Pod 집합을 기준으로 삼아, 축소 직후 재생성된 Pod도 이동으로 집계합니다.
base=$(pods); seen="$base"
k -n bench scale deployment inflate --replicas "$TO" >/dev/null
start=$(date +%s)
while (( $(date +%s) - start <= WINDOW )); do
  cur=$(pods); seen=$(printf '%s\n%s\n' "$seen" "$cur" | sort -u)
  moved=$(comm -13 <(echo "$base") <(echo "$seen") | grep -c . || true)
  read -r n ready c usd skus < <(node_state)
  echo "$(( $(date +%s) - start )),$n,$c,$usd,$skus,$(echo "$cur" | grep -c .),$moved,$ready"
  sleep 30
done
log "done"
