#!/usr/bin/env bash
# 사용법: rightsize.sh <kube-context> <scenario> <nodeSelector key=value>
#   FROM=20 TO=3      축소 전후 replica 수(Pod당 1 vCPU)
#   WINDOW=720        축소 후 관찰 시간(초)
#   PRICES=<json>     prices.py 출력
# 축소 후 30초마다 노드 구성·시간당 비용과, 축소 시점에 남아 있던 Pod 외에 새로 생긴 Pod 수(이동 횟수)를 기록합니다.
set -euo pipefail
CTX=$1 SCENARIO=$2 SELECTOR=$3
FROM=${FROM:-20} TO=${TO:-3} WINDOW=${WINDOW:-720}
HERE=$(cd "$(dirname "$0")" && pwd); PRICES=${PRICES:-$HERE/../results/prices-eastus2.json}
k() { kubectl --context "$CTX" "$@"; }
log() { echo "[$(date -u +%T)] $SCENARIO $*" >&2; }
pods() { k -n bench get pods -l app=inflate -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort; }
node_state() { # "노드수 vCPU합 시간당비용 SKU목록"
  k get nodes -l "$SELECTOR" -o json | python3 -c "
import json,sys
p=json.load(open('$PRICES'))
n=[x for x in json.load(sys.stdin)['items'] if any(c['type']=='Ready' and c['status']=='True' for c in x['status']['conditions'])]
s={}
for x in n:
  t=x['metadata']['labels'].get('node.kubernetes.io/instance-type','?'); s[t]=s.get(t,0)+1
print(len(n), sum(int(x['status']['capacity']['cpu']) for x in n), round(sum(p.get(t,0)*c for t,c in s.items()),3), ' '.join(f'{t}x{c}' for t,c in sorted(s.items())))"
}

k apply -f "$HERE/../manifests/inflate.yaml" >/dev/null
k -n bench patch deployment inflate --type strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"pause","resources":{"requests":{"cpu":"1","memory":"1Gi"}}}]}}}}' >/dev/null
k -n bench patch deployment inflate --type json -p \
  "[{\"op\":\"add\",\"path\":\"/spec/template/spec/nodeSelector\",\"value\":{\"${SELECTOR%%=*}\":\"${SELECTOR#*=}\"}}]" >/dev/null
k -n bench scale deployment inflate --replicas "$FROM" >/dev/null
k -n bench rollout status deployment/inflate --timeout=20m >/dev/null
sleep 60
echo "elapsed_s,nodes,vcpu,usd_per_hour,skus,pods,moved_pods"
read -r n c usd skus < <(node_state); echo "-60,$n,$c,$usd,$skus,$FROM,0"

k -n bench scale deployment inflate --replicas "$TO" >/dev/null
sleep 5
base=$(pods); seen="$base"
start=$(date +%s)
while (( $(date +%s) - start <= WINDOW )); do
  cur=$(pods); seen=$(printf '%s\n%s\n' "$seen" "$cur" | sort -u)
  moved=$(comm -13 <(echo "$base") <(echo "$seen") | grep -c . || true)
  read -r n c usd skus < <(node_state)
  echo "$(( $(date +%s) - start )),$n,$c,$usd,$skus,$(echo "$cur" | grep -c .),$moved"
  sleep 30
done
k -n bench scale deployment inflate --replicas 0 >/dev/null
log "done"
