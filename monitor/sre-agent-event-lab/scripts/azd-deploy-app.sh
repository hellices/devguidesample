#!/usr/bin/env bash
set -euo pipefail

# `postdeploy` hook: the cloud half of the lab's two-phase deployment.
#
# Why a second phase exists at all
# --------------------------------
# The lab runs on Container Apps pulling from ACR with a user-assigned
# managed identity. One ARM deployment creates the registry, the identity,
# the `AcrPull` role assignment and the Container App -- but it cannot
# deploy the lab image: that image does not exist until something builds
# it, and a role assignment created moments ago is not necessarily usable
# by the pull that would immediately follow. So provisioning leaves a
# public placeholder image running (ingress on 80, no probes) and this
# hook, which runs in the deploy phase, does the rest:
#
#   1. wait until the workload identity's `AcrPull` assignment is visible
#      at exactly the lab registry's scope (up to 5 minutes),
#   2. build the image *in ACR* (never locally -- the lab requires no
#      Docker daemon),
#   3. point the app's registry configuration at the same identity, move
#      ingress to the app's port, and roll the app onto the new image,
#   4. verify a new healthy revision and a healthy `/healthz`,
#   5. record the built image in the azd environment, so a later
#      `azd provision` keeps the lab image and its matching probes instead
#      of reverting to the placeholder.
#
# Step 1 is a read-consistency check on ARM, not a proof that the registry
# data plane will accept the token; it is the strongest signal available
# without attempting a pull, and it removes the common failure where the
# very first pull races the role assignment.
#
# azd 1.29 runs project-level `predeploy`/`postdeploy` hooks even for a
# project that declares no services (verified against azd 1.29.0, and in
# azd's own `cli/azd/internal/cmd/up_graph.go`, which keeps those steps
# for "Zero-service projects"), so `azd deploy` and `azd up` both reach
# this hook without the lab declaring a service that would drag in a local
# Docker build.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
LAB_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
readonly LAB_ROOT
readonly APP_DIR="${LAB_ROOT}/app"
# The lab image serves HTTP on 8000; the placeholder image the first
# provision leaves running serves 80, so ingress has to move with the image.
readonly APP_TARGET_PORT=8000
readonly IMAGE_REPOSITORY="sre-event-lab"
# AcrPull, by role definition ID: a display name can be reused by a custom
# role, this GUID cannot.
readonly ACR_PULL_ROLE_DEFINITION_ID="7f951dda-4ed3-4680-a7ca-43fe172d538d"

# Every wait below is a budget, not a guess, and each one is overridable so
# a slow tenant does not need a code change (and so tests can run fast).
readonly ACR_PULL_TIMEOUT_SECONDS="${SRE_ACR_PULL_TIMEOUT_SECONDS:-300}"
readonly ACR_PULL_POLL_INTERVAL_SECONDS="${SRE_ACR_PULL_POLL_INTERVAL_SECONDS:-10}"
readonly REVISION_READY_TIMEOUT_SECONDS="${SRE_REVISION_READY_TIMEOUT_SECONDS:-600}"
readonly HEALTH_TIMEOUT_SECONDS="${SRE_HEALTH_TIMEOUT_SECONDS:-600}"
readonly DEPLOY_POLL_INTERVAL_SECONDS="${SRE_DEPLOY_POLL_INTERVAL_SECONDS:-10}"

for command_name in az azd curl; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

# Every value below is a deployment output azd refreshes into this hook's
# environment. A missing one means provisioning has not run (or the
# environment is stale), which is worth saying before spending any Azure
# call on it.
readonly MISSING_OUTPUT_HINT="is missing; run 'azd provision' (or 'azd up') first"
: "${AZURE_SUBSCRIPTION_ID:?${MISSING_OUTPUT_HINT}}"
: "${AZURE_RESOURCE_GROUP:?${MISSING_OUTPUT_HINT}}"
: "${AZURE_ACR_NAME:?${MISSING_OUTPUT_HINT}}"
: "${AZURE_CONTAINER_APP_NAME:?${MISSING_OUTPUT_HINT}}"
: "${AZURE_CONTAINER_APP_FQDN:?${MISSING_OUTPUT_HINT}}"
: "${AZURE_CONTAINER_APP_PRINCIPAL_ID:?${MISSING_OUTPUT_HINT}}"
: "${AZURE_WORKLOAD_IDENTITY_RESOURCE_ID:?${MISSING_OUTPUT_HINT}}"

# `az account show` fails with a raw Azure CLI error when no one is signed
# in; guard it so the hook fails fast with one clear, actionable message
# instead of that raw stderr or an unexplained `set -e` abort.
if ! ACTIVE_SUBSCRIPTION_ID="$(az account show --query id -o tsv 2>/dev/null)"; then
  echo "Azure CLI is not signed in. Run 'az login', then re-run this command." >&2
  exit 1
fi
readonly ACTIVE_SUBSCRIPTION_ID
if [[ "${ACTIVE_SUBSCRIPTION_ID}" != "${AZURE_SUBSCRIPTION_ID}" ]]; then
  echo "Azure CLI is signed in to ${ACTIVE_SUBSCRIPTION_ID}." >&2
  echo "Every lab operation is pinned to ${AZURE_SUBSCRIPTION_ID} instead." >&2
fi

ACR_RESOURCE_ID="$(az acr show \
  --name "${AZURE_ACR_NAME}" \
  --subscription "${AZURE_SUBSCRIPTION_ID}" \
  --query id \
  -o tsv)"
readonly ACR_RESOURCE_ID

# `AZURE_ACR_LOGIN_SERVER` is a deployment output, but this hook is also
# run by hand (`azd hooks run postdeploy`) against environments written by
# older provisions, so fall back to the registry itself.
ACR_LOGIN_SERVER="${AZURE_ACR_LOGIN_SERVER:-}"
if [[ -z "${ACR_LOGIN_SERVER}" ]]; then
  ACR_LOGIN_SERVER="$(az acr show \
    --name "${AZURE_ACR_NAME}" \
    --subscription "${AZURE_SUBSCRIPTION_ID}" \
    --query loginServer \
    -o tsv)"
fi
readonly ACR_LOGIN_SERVER

lowercase() {
  printf '%s' "${1}" | tr '[:upper:]' '[:lower:]'
}

# True once the workload identity holds AcrPull at *exactly* the lab
# registry. `az role assignment list` without `--include-inherited` matches
# the scope exactly (azure-cli lowercases both sides), so an AcrPull
# granted higher up -- at the resource group or the subscription -- is
# deliberately not accepted here: it is not the assignment this lab
# creates, and treating it as one would let the gate pass while the lab's
# own assignment is still propagating.
#
# `--assignee-principal-type` is not a `role assignment list` option --
# verified against the installed Azure CLI (2.89.1): passing it here fails
# with `ERROR: unrecognized arguments: --assignee-principal-type
# ServicePrincipal`. `--assignee-object-id` alone already bypasses
# Microsoft Graph for the assignee *filter*; `--fill-principal-name` and
# `--fill-role-definition-name` default to `true` and each would still
# query Graph to populate fields this poll never reads, so both are set to
# `false` to keep the poll working with no Graph reachability at all.
acr_pull_is_visible() {
  local granted expected line
  granted="$(az role assignment list \
    --assignee-object-id "${AZURE_CONTAINER_APP_PRINCIPAL_ID}" \
    --scope "${ACR_RESOURCE_ID}" \
    --subscription "${AZURE_SUBSCRIPTION_ID}" \
    --fill-principal-name false \
    --fill-role-definition-name false \
    --query "[?ends_with(roleDefinitionId, '${ACR_PULL_ROLE_DEFINITION_ID}')].scope" \
    -o tsv 2>/dev/null || true)"
  expected="$(lowercase "${ACR_RESOURCE_ID}")"
  while IFS= read -r line; do
    # ARM echoes the scope as it was written (`resourceGroups` or
    # `resourcegroups`); resource IDs are case-insensitive, and a casing
    # difference must not stall the deployment for the full budget.
    if [[ -n "${line}" && "$(lowercase "${line}")" == "${expected}" ]]; then
      return 0
    fi
  done <<<"${granted}"
  return 1
}

echo "Waiting for AcrPull on ${ACR_RESOURCE_ID} (up to ${ACR_PULL_TIMEOUT_SECONDS}s)..."
acr_pull_started="${SECONDS}"
until acr_pull_is_visible; do
  if (( SECONDS - acr_pull_started >= ACR_PULL_TIMEOUT_SECONDS )); then
    echo "The workload identity ${AZURE_CONTAINER_APP_PRINCIPAL_ID} still has no" >&2
    echo "AcrPull assignment at ${ACR_RESOURCE_ID} after ${ACR_PULL_TIMEOUT_SECONDS}s." >&2
    echo "Nothing was built or deployed. Re-run 'azd provision' to restore the" >&2
    echo "assignment, then 'azd deploy' -- or raise SRE_ACR_PULL_TIMEOUT_SECONDS." >&2
    exit 1
  fi
  sleep "${ACR_PULL_POLL_INTERVAL_SECONDS}"
done
echo "AcrPull is in place; building the lab image."

IMAGE_TAG="run-$(date -u +%Y%m%dT%H%M%SZ)"
readonly IMAGE_TAG
readonly CONTAINER_IMAGE="${ACR_LOGIN_SERVER}/${IMAGE_REPOSITORY}:${IMAGE_TAG}"

# Built by the registry from the sources, so the lab needs no local Docker.
az acr build \
  --registry "${AZURE_ACR_NAME}" \
  --image "${IMAGE_REPOSITORY}:${IMAGE_TAG}" \
  --subscription "${AZURE_SUBSCRIPTION_ID}" \
  "${APP_DIR}"

# The app must pull with the identity the AcrPull assignment was granted
# to; the placeholder image needed no registry credentials at all.
az containerapp registry set \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --name "${AZURE_CONTAINER_APP_NAME}" \
  --subscription "${AZURE_SUBSCRIPTION_ID}" \
  --server "${ACR_LOGIN_SERVER}" \
  --identity "${AZURE_WORKLOAD_IDENTITY_RESOURCE_ID}" \
  --output none

# Ingress is app-level configuration and does not create a revision, so move
# it to the lab port before the new image starts serving.
az containerapp ingress update \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --name "${AZURE_CONTAINER_APP_NAME}" \
  --subscription "${AZURE_SUBSCRIPTION_ID}" \
  --target-port "${APP_TARGET_PORT}" \
  --output none

PREVIOUS_REVISION="$(az containerapp show \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --name "${AZURE_CONTAINER_APP_NAME}" \
  --subscription "${AZURE_SUBSCRIPTION_ID}" \
  --query properties.latestRevisionName \
  -o tsv)"
readonly PREVIOUS_REVISION

az containerapp update \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --name "${AZURE_CONTAINER_APP_NAME}" \
  --subscription "${AZURE_SUBSCRIPTION_ID}" \
  --image "${CONTAINER_IMAGE}" \
  --output none

wait_for_new_revision_ready() {
  local timeout_seconds="${1:-600}"
  local started="${SECONDS}"

  while (( SECONDS - started < timeout_seconds )); do
    local latest_revision
    latest_revision="$(az containerapp show \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${AZURE_CONTAINER_APP_NAME}" \
      --subscription "${AZURE_SUBSCRIPTION_ID}" \
      --query properties.latestRevisionName \
      -o tsv)"
    if [[ -n "${latest_revision}" && "${latest_revision}" != "${PREVIOUS_REVISION}" ]]; then
      local health active
      health="$(az containerapp revision list \
        --resource-group "${AZURE_RESOURCE_GROUP}" \
        --name "${AZURE_CONTAINER_APP_NAME}" \
        --subscription "${AZURE_SUBSCRIPTION_ID}" \
        --query "[?name=='${latest_revision}'].properties.healthState | [0]" \
        -o tsv 2>/dev/null || true)"
      active="$(az containerapp revision list \
        --resource-group "${AZURE_RESOURCE_GROUP}" \
        --name "${AZURE_CONTAINER_APP_NAME}" \
        --subscription "${AZURE_SUBSCRIPTION_ID}" \
        --query "[?name=='${latest_revision}'].properties.active | [0]" \
        -o tsv 2>/dev/null || true)"
      if [[ "${health}" == "Healthy" && "${active}" == "true" ]]; then
        return 0
      fi
    fi
    sleep "${DEPLOY_POLL_INTERVAL_SECONDS}"
  done

  echo "A new healthy revision did not become active within ${timeout_seconds}s." >&2
  return 1
}

wait_for_new_revision_ready "${REVISION_READY_TIMEOUT_SECONDS}"

health_started="${SECONDS}"
until curl --fail --silent --show-error "https://${AZURE_CONTAINER_APP_FQDN}/healthz" >/dev/null; do
  if (( SECONDS - health_started >= HEALTH_TIMEOUT_SECONDS )); then
    echo "Health endpoint did not return HTTP 200 within ${HEALTH_TIMEOUT_SECONDS}s." >&2
    exit 1
  fi
  sleep "${DEPLOY_POLL_INTERVAL_SECONDS}"
done

# Only a verified-healthy image is recorded: persisting one that never came
# up would make the next `azd provision` deploy it again as if it were
# known good. `--cwd` because azd runs hooks from wherever the operator
# invoked it, which need not be the lab.
azd env set SRE_IMAGE_TAG "${IMAGE_TAG}" --cwd "${LAB_ROOT}"
azd env set SRE_CONTAINER_IMAGE "${CONTAINER_IMAGE}" --cwd "${LAB_ROOT}"

echo "Deployed ${CONTAINER_IMAGE}; https://${AZURE_CONTAINER_APP_FQDN}/healthz is healthy."
