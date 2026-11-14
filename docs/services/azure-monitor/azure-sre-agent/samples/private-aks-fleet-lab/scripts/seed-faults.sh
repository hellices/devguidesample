#!/usr/bin/env bash
# Seeds or resets test conditions (unhealthy pods, single-replica deployment,
# and blocking PodDisruptionBudget) across target Private AKS clusters.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

MODE="${1:-seed}"
C03="${CLUSTER_03:-aks-priv-03}"
C06="${CLUSTER_06:-aks-priv-06}"
C10="${CLUSTER_10:-aks-priv-10}"

if [[ "$MODE" == "seed" ]]; then
  echo "==> Seeding preflight & pod failure conditions on ${C03}, ${C06}, ${C10}"
  az aks command invoke -g "$RESOURCE_GROUP" -n "$C03" --command "
    kubectl create ns banking --dry-run=client -o yaml | kubectl apply -f -
    kubectl create deploy banking-fx-sync -n banking --image=docker.io/library/nginx:broken-fx-v4.0.9 --replicas=1 --dry-run=client -o yaml | kubectl apply -f -
  " >/dev/null

  az aks command invoke -g "$RESOURCE_GROUP" -n "$C06" --command "
    kubectl create ns messaging --dry-run=client -o yaml | kubectl apply -f -
    kubectl create deploy sms-gateway-single -n messaging --image=docker.io/library/nginx:1.25-alpine --replicas=1 --dry-run=client -o yaml | kubectl apply -f -
    kubectl create deploy sms-retry-worker -n messaging --image=docker.io/library/nginx:1.25-alpine --replicas=1 --dry-run=client -o yaml | kubectl apply -f -
    kubectl patch deploy sms-retry-worker -n messaging --type=json -p='[{\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/command\",\"value\":[\"sh\",\"-c\",\"exit 1\"]}]'
  " >/dev/null

  az aks command invoke -g "$RESOURCE_GROUP" -n "$C10" --command "
    kubectl create ns payments-canary --dry-run=client -o yaml | kubectl apply -f -
    kubectl create deploy legacy-batch-sync -n payments-canary --image=mcr.microsoft.com/mirror/docker/library/nginx:nonexistent-broken-tag-v99.99 --replicas=2 --dry-run=client -o yaml | kubectl apply -f -
    cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: naked-audit-shipper
  namespace: payments-canary
  annotations:
    kubectl.kubernetes.io/last-applied-configuration: '{\"apiVersion\":\"flowcontrol.apiserver.k8s.io/v1beta3\",\"kind\":\"FlowSchema\"}'
spec:
  nodeSelector:
    dedicated: nonexistent-node-pool
  containers:
  - name: shipper
    image: mcr.microsoft.com/oss/nginx/nginx:1.25
    volumeMounts:
    - name: scratch
      mountPath: /var/cache/scratch
  volumes:
  - name: scratch
    emptyDir: {}
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: legacy-batch-sync-pdb
  namespace: payments-canary
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: legacy-batch-sync
YAML
  " >/dev/null
  echo "==> Fault conditions (9-point preflight failure scenarios) seeded."
elif [[ "$MODE" == "reset" ]]; then
  echo "==> Resetting workloads to healthy state on ${C03}, ${C06}, ${C10}"
  az aks command invoke -g "$RESOURCE_GROUP" -n "$C03" --command "
    kubectl set image deploy/banking-fx-sync nginx=docker.io/library/nginx:1.25-alpine -n banking || true
  " >/dev/null
  az aks command invoke -g "$RESOURCE_GROUP" -n "$C06" --command "
    kubectl scale deploy/sms-gateway-single -n messaging --replicas=2 || true
    kubectl patch deploy sms-retry-worker -n messaging --type=json -p='[{\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/command\",\"value\":[\"nginx\",\"-g\",\"daemon off;\"]}]' || true
  " >/dev/null
  az aks command invoke -g "$RESOURCE_GROUP" -n "$C10" --command "
    kubectl set image deploy/legacy-batch-sync nginx=docker.io/library/nginx:1.25-alpine -n payments-canary || true
  " >/dev/null
  echo "==> Workloads restored to Running."
else
  echo "Usage: $0 [seed|reset]" >&2
  exit 1
fi
