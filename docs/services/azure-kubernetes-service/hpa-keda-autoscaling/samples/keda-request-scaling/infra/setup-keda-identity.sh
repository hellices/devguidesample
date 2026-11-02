#!/usr/bin/env bash
# azd postprovision에서 호출: Bicep이 만든 KEDA용 관리 ID(federated credential 포함)를 keda-operator에 연결합니다.
#   CTX(kube context), KEDA_CLIENT_ID  필수
set -euo pipefail
CTX=${CTX:?} CLIENT_ID=${KEDA_CLIENT_ID:?}
[[ $CLIENT_ID =~ ^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$ ]] || { echo "KEDA_CLIENT_ID는 GUID여야 합니다: '${CLIENT_ID}'" >&2; exit 2; }
kubectl --context "$CTX" --request-timeout=30s -n kube-system annotate serviceaccount keda-operator \
  azure.workload.identity/client-id="$CLIENT_ID" --overwrite
# annotation은 새 Pod부터 적용됩니다. 이전 실행이 annotation 뒤 재시작 전에 실패했을 수 있으므로
# annotation 값이 이미 같아도 매번 keda-operator를 다시 시작합니다.
kubectl --context "$CTX" --request-timeout=30s -n kube-system rollout restart deploy keda-operator
# --request-timeout은 watch 요청도 끊으므로 대기 시간(5분)보다 길게 둡니다.
kubectl --context "$CTX" --request-timeout=6m -n kube-system rollout status deploy keda-operator --timeout=5m
