#!/usr/bin/env bash
# postdeploy: applies the producer and slow consumer with Workload Identity service accounts.
# The producer starts at zero replicas and run-scenario.sh drives the measured lag rise and
# recovery. The consumer manifest omits replicas, so a redeploy never restarts a running consumer.
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

kube rollout status deploy/eventhubs-slow-consumer -n "$NS" --timeout 300s
log "workloads applied. Run ./scripts/run-scenario.sh to produce lag and recovery."
