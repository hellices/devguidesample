#!/usr/bin/env bash
# 2026-04-23 이후 만든 AGC association은 서브넷 NSG를 그대로 적용합니다.
# aks-appgateway 서브넷에 NSG가 연결되어 있고 기본 규칙(AllowVNetInBound, AllowAzureLoadBalancerInBound,
# DenyAllInBound)만 있으면 Internet에서 오는 frontend 포트(80·443)가 막히므로 허용 규칙을 추가합니다.
# NSG가 연결되어 있지 않으면 할 일이 없습니다. AllowAzureLoadBalancerInBound는 그대로 둡니다.
# 규칙 priority는 PRIORITY(기본 200, 100~4096)로 바꿀 수 있습니다.
set -euo pipefail
RG=${AZURE_RESOURCE_GROUP:?} CLUSTER=${AKS_CLUSTER_NAME:?}
MC=$(az aks show -g "$RG" -n "$CLUSTER" --query nodeResourceGroup -o tsv)
# 노드 리소스 그룹의 모든 VNet에서 aks-appgateway 서브넷을 찾고, 정확히 하나일 때만 진행합니다.
ROWS=$(az network vnet list -g "$MC" --query "[].subnets[?name=='aks-appgateway'][].[id, networkSecurityGroup.id || '']" -o tsv)
COUNT=$(grep -c . <<<"$ROWS" || true)
if (( COUNT != 1 )); then
  echo "노드 리소스 그룹 ${MC}에서 aks-appgateway 서브넷을 ${COUNT}개 찾았습니다. 정확히 1개여야 합니다." >&2
  exit 1
fi
NSG_ID=$(cut -f2 <<<"$ROWS")
if [[ -z $NSG_ID ]]; then
  echo "aks-appgateway 서브넷에 NSG가 없어 frontend 허용 규칙이 필요하지 않습니다."
  exit 0
fi
NSG_RG=$(cut -d/ -f5 <<<"$NSG_ID") NSG=${NSG_ID##*/}
RULE=allow-agc-frontend-http PRIORITY=${PRIORITY:-200}
[[ $PRIORITY =~ ^[0-9]+$ ]] && (( 10#$PRIORITY >= 100 && 10#$PRIORITY <= 4096 )) || {
  echo "PRIORITY는 100~4096 정수여야 합니다: '${PRIORITY}'" >&2; exit 2; }
PRIORITY=$((10#$PRIORITY))
# 같은 방향(Inbound)의 다른 규칙이 PRIORITY를 쓰고 있으면 충돌하므로 100~4096에서 비어 있는 가장 낮은 값을 씁니다.
USED=$(az network nsg rule list -g "$NSG_RG" --nsg-name "$NSG" \
  --query "[?name!='$RULE' && direction=='Inbound'].priority" -o tsv)
used() { [[ $'\n'$USED$'\n' == *$'\n'"$1"$'\n'* ]]; }
if used "$PRIORITY"; then
  p=100
  while (( p <= 4096 )) && used "$p"; do p=$(( p + 1 )); done
  (( p <= 4096 )) || { echo "NSG ${NSG}에 비어 있는 Inbound priority(100~4096)가 없습니다." >&2; exit 1; }
  echo "NSG ${NSG}에서 다른 규칙이 쓰는 priority(${PRIORITY}) 대신 비어 있는 가장 낮은 priority(${p})로 설정합니다."
  PRIORITY=$p
fi
RULE_ARGS=(--priority "$PRIORITY" --direction Inbound --access Allow --protocol Tcp
  --source-address-prefixes Internet --source-port-ranges '*' --destination-address-prefixes '*' --destination-port-ranges 80 443)
# AGC frontend 주소는 이 스크립트에서 알 수 없으므로 destination은 모든 주소(*)로 명시합니다.
# 같은 이름의 규칙이 있으면 priority·access·direction·protocol·source·destination·source/destination 포트를 비교해 다를 때만 기대값으로 고칩니다.
if rule=$(az network nsg rule show -g "$NSG_RG" --nsg-name "$NSG" -n "$RULE" -o json 2>/dev/null); then
  if python3 -c '
import json, sys
r = json.load(sys.stdin)
def vals(one, many):
    v = ([r[one]] if r.get(one) else []) + (r.get(many) or [])
    return sorted({str(x).lower() for x in v})
ok = str(r.get("priority")) == sys.argv[1] \
    and [str(r.get(k, "")).lower() for k in ("access", "direction", "protocol")] == ["allow", "inbound", "tcp"] \
    and vals("sourceAddressPrefix", "sourceAddressPrefixes") == ["internet"] \
    and vals("sourcePortRange", "sourcePortRanges") == ["*"] \
    and vals("destinationAddressPrefix", "destinationAddressPrefixes") == ["*"] \
    and vals("destinationPortRange", "destinationPortRanges") == ["443", "80"]
sys.exit(0 if ok else 1)' "$PRIORITY" <<<"$rule"; then
    echo "NSG ${NSG}의 ${RULE} 규칙이 이미 기대값과 같습니다."
    exit 0
  fi
  echo "NSG ${NSG}의 ${RULE} 규칙 값이 달라 기대값으로 수정합니다."
  az network nsg rule update -g "$NSG_RG" --nsg-name "$NSG" -n "$RULE" "${RULE_ARGS[@]}" -o none
  exit 0
fi
az network nsg rule create -g "$NSG_RG" --nsg-name "$NSG" -n "$RULE" "${RULE_ARGS[@]}" -o none
