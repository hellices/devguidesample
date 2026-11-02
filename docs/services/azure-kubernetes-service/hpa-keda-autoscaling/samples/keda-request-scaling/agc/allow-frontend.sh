#!/usr/bin/env bash
# 2026-04-23 이후 만든 AGC association은 서브넷 NSG를 그대로 적용합니다.
# aks-appgateway 서브넷에 NSG가 연결되어 있고 기본 규칙(AllowVNetInBound, AllowAzureLoadBalancerInBound,
# DenyAllInBound)만 있으면 Internet에서 오는 frontend 포트(80·443)가 막히므로 허용 규칙을 추가합니다.
# NSG가 연결되어 있지 않으면 할 일이 없습니다. AllowAzureLoadBalancerInBound는 그대로 둡니다.
# 규칙 priority는 200을 쓰고, 다른 Inbound 규칙이 쓰고 있으면 100~4096에서 비어 있는 가장 낮은 값을 씁니다.
set -euo pipefail
RG=${AZURE_RESOURCE_GROUP:?} CLUSTER=${AKS_CLUSTER_NAME:?}
RULE=allow-agc-frontend-http
MC=$(az aks show -g "$RG" -n "$CLUSTER" --query nodeResourceGroup -o tsv)
# 빈 값이면 az가 구독 전체를 조회하므로 이름을 확인합니다.
[[ $MC =~ ^[A-Za-z0-9._()-]+$ ]] || { echo "노드 리소스 그룹 이름이 올바르지 않습니다: '${MC}'" >&2; exit 1; }
# 노드 리소스 그룹의 모든 VNet에서 aks-appgateway 서브넷을 찾고, 정확히 하나일 때만 진행합니다.
ROWS=$(az network vnet list -g "$MC" --query "[].subnets[?name=='aks-appgateway'][].[id, networkSecurityGroup.id || '']" -o tsv)
COUNT=$(grep -c . <<<"$ROWS" || [[ $? == 1 ]])
if (( COUNT != 1 )); then
  echo "노드 리소스 그룹 ${MC}에서 aks-appgateway 서브넷을 ${COUNT}개 찾았습니다. 정확히 1개여야 합니다." >&2
  exit 1
fi
NSG_ID=$(cut -f2 <<<"$ROWS")
if [[ -z $NSG_ID ]]; then
  echo "aks-appgateway 서브넷에 NSG가 없어 frontend 허용 규칙이 필요하지 않습니다."
  exit 0
fi
# NSG ID에서 리소스 그룹과 이름을 읽습니다. 형식이 다르면 다른 리소스를 바꾸지 않도록 중단합니다.
[[ $NSG_ID =~ ^/subscriptions/[^/]+/[Rr]esource[Gg]roups/([^/]+)/providers/[Mm]icrosoft\.[Nn]etwork/[Nn]etwork[Ss]ecurity[Gg]roups/([^/]+)$ ]] ||
  { echo "NSG ID 형식이 올바르지 않습니다: '${NSG_ID}'" >&2; exit 1; }
NSG_RG=${BASH_REMATCH[1]} NSG=${BASH_REMATCH[2]}
# 규칙 목록을 한 번 읽어 priority와 기존 규칙 값을 함께 판단합니다. 조회가 실패하면 중단합니다.
RULES=$(az network nsg rule list -g "$NSG_RG" --nsg-name "$NSG" -o json)
# 출력: <create|update|keep|full> <priority>
#  - 같은 방향(Inbound)의 다른 규칙이 200을 쓰면 100~4096에서 비어 있는 가장 낮은 값을 고릅니다.
#  - 같은 이름의 규칙이 있으면 priority·access·direction·protocol·source·destination·source/destination 포트를 비교합니다.
PLAN=$(python3 -c '
import json, sys
rule = sys.argv[1].lower()
rules = json.load(sys.stdin)
used = {int(r["priority"]) for r in rules
        if str(r.get("name", "")).lower() != rule and str(r.get("direction", "")).lower() == "inbound"
        and r.get("priority") is not None}
p = 200
if p in used:
    p = next((x for x in range(100, 4097) if x not in used), None)
    if p is None:
        print("full 0"); sys.exit(0)
mine = [r for r in rules if str(r.get("name", "")).lower() == rule]
if not mine:
    print("create", p); sys.exit(0)
r = mine[0]
def vals(one, many):
    v = ([r[one]] if r.get(one) else []) + (r.get(many) or [])
    return sorted({str(x).lower() for x in v})
ok = str(r.get("priority")) == str(p) \
    and [str(r.get(k, "")).lower() for k in ("access", "direction", "protocol")] == ["allow", "inbound", "tcp"] \
    and vals("sourceAddressPrefix", "sourceAddressPrefixes") == ["internet"] \
    and vals("sourcePortRange", "sourcePortRanges") == ["*"] \
    and vals("destinationAddressPrefix", "destinationAddressPrefixes") == ["*"] \
    and vals("destinationPortRange", "destinationPortRanges") == ["443", "80"]
print("keep" if ok else "update", p)' "$RULE" <<<"$RULES")
read -r ACTION PRIORITY <<<"$PLAN"
[[ $ACTION =~ ^(create|update|keep|full)$ && $PRIORITY =~ ^[0-9]+$ ]] || { echo "규칙 판단 결과가 올바르지 않습니다: '${PLAN}'" >&2; exit 1; }
if [[ $ACTION == full ]]; then
  echo "NSG ${NSG}에 비어 있는 Inbound priority(100~4096)가 없습니다." >&2; exit 1
fi
if (( PRIORITY != 200 )); then
  echo "NSG ${NSG}에서 다른 규칙이 쓰는 priority(200) 대신 비어 있는 가장 낮은 priority(${PRIORITY})로 설정합니다."
fi
# AGC frontend 주소는 이 스크립트에서 알 수 없으므로 destination은 모든 주소(*)로 명시합니다.
RULE_ARGS=(--priority "$PRIORITY" --direction Inbound --access Allow --protocol Tcp
  --source-address-prefixes Internet --source-port-ranges '*' --destination-address-prefixes '*' --destination-port-ranges 80 443)
case $ACTION in
  keep) echo "NSG ${NSG}의 ${RULE} 규칙이 이미 기대값과 같습니다." ;;
  update)
    echo "NSG ${NSG}의 ${RULE} 규칙 값이 달라 기대값으로 수정합니다."
    az network nsg rule update -g "$NSG_RG" --nsg-name "$NSG" -n "$RULE" "${RULE_ARGS[@]}" -o none ;;
  create) az network nsg rule create -g "$NSG_RG" --nsg-name "$NSG" -n "$RULE" "${RULE_ARGS[@]}" -o none ;;
esac
