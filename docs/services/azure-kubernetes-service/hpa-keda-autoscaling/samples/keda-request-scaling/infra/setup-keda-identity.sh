#!/usr/bin/env bash
# keda-operator가 사용할 사용자 할당 관리 ID를 만들고 federated credential을 연결합니다.
set -euo pipefail
RG=${RG:-rg-aks-autoscale-lab} CLUSTER=${CLUSTER:-aks-nap} CTX=${CTX:-aks-nap}

ISSUER=$(az aks show -g "$RG" -n "$CLUSTER" --query oidcIssuerProfile.issuerUrl -o tsv)
CLIENT_ID=$(az identity create -g "$RG" -n id-keda --query clientId -o tsv)
az identity federated-credential create -g "$RG" --identity-name id-keda -n keda-operator \
  --issuer "$ISSUER" --subject system:serviceaccount:kube-system:keda-operator \
  --audience api://AzureADTokenExchange -o none

kubectl --context "$CTX" -n kube-system annotate serviceaccount keda-operator \
  azure.workload.identity/client-id="$CLIENT_ID" --overwrite
kubectl --context "$CTX" -n kube-system rollout restart deploy keda-operator
kubectl --context "$CTX" -n kube-system rollout status deploy keda-operator
echo "KEDA_CLIENT_ID=$CLIENT_ID"
