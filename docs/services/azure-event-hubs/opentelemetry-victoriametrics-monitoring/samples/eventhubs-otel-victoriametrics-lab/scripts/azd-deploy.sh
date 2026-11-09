#!/usr/bin/env bash
# postdeploy: applies the producer and slow consumer with Workload Identity service accounts.
# Both start at zero replicas; run-scenario.sh drives the measured lag rise and recovery.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands az azd kubectl
load_env AZURE_SUBSCRIPTION_ID AZURE_ENV_NAME PREMIUM_NAMESPACE_NAME WORKLOAD_EVENTHUB_NAME \
  WORKLOAD_CONSUMER_GROUP CHECKPOINT_ACCOUNT_URL PRODUCER_CLIENT_ID CONSUMER_CLIENT_ID WORKLOAD_IMAGE
assert_active_subscription
NS=eventhubs-observability

sed -e "s|__PRODUCER_CLIENT_ID__|$PRODUCER_CLIENT_ID|g" \
    -e "s|__CONSUMER_CLIENT_ID__|$CONSUMER_CLIENT_ID|g" \
    -e "s|__WORKLOAD_IMAGE__|$WORKLOAD_IMAGE|g" \
    -e "s|__EVENT_HUB_NAMESPACE__|$PREMIUM_NAMESPACE_NAME.servicebus.windows.net|g" \
    -e "s|__EVENT_HUB_NAME__|$WORKLOAD_EVENTHUB_NAME|g" \
    -e "s|__EVENT_HUB_CONSUMER_GROUP__|$WORKLOAD_CONSUMER_GROUP|g" \
    -e "s|__CHECKPOINT_ACCOUNT_URL__|${CHECKPOINT_ACCOUNT_URL%/}|g" \
    "$LAB_ROOT/k8s/workloads.yaml" | kube apply -f -

# kubectl apply would reset replicas to the manifest value; keep a running consumer across redeploys.
current="$(kube get deploy eventhubs-slow-consumer -n "$NS" -o jsonpath='{.status.replicas}' 2>/dev/null || true)"
if [[ -z "$current" || "$current" == "0" ]]; then
  kube scale deploy/eventhubs-slow-consumer -n "$NS" --replicas 1
fi
kube rollout status deploy/eventhubs-slow-consumer -n "$NS" --timeout 300s
log "workloads applied. Run ./scripts/run-scenario.sh to produce lag and recovery."
