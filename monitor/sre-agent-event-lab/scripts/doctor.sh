#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

# `require_lab_config` may return before every value below is assigned (a
# missing required setting makes it `return 1` immediately). Seeding these
# names from the process environment keeps every later `${NAME}`/`-n` check
# well-defined under `set -u` no matter how far configuration loading got.
# The process environment is exactly where `common.sh`'s `setting` takes its
# highest-precedence value from, so this reads the same source it would --
# it does not invent a fallback, and any name that survives here unset stays
# empty rather than becoming a configuration value on its own.
SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-}"
RESOURCE_GROUP="${RESOURCE_GROUP:-}"
AZURE_ENV_NAME="${AZURE_ENV_NAME:-}"
SRE_AGENT_RESOURCE_ID="${SRE_AGENT_RESOURCE_ID:-}"

ANY_FAIL=0
AZURE_SAFE=1

# report CHECK STATUS DETAIL -- the doctor output contract: a single
# tab-separated line per check. STATUS is PASS, FAIL, or MANUAL; only FAIL
# marks the overall run unhealthy (`acknowledge`d MANUAL items are a human
# decision, not this script's to make).
report() {
  local check_name="$1" status="$2" detail="$3"
  printf '%s\t%s\t%s\n' "${check_name}" "${status}" "${detail}"
  if [[ "${status}" == "FAIL" ]]; then
    ANY_FAIL=1
  fi
}

# 1. Required commands ------------------------------------------------------
MISSING_COMMANDS=()
for command_name in az azd jq curl python3; do
  command -v "${command_name}" >/dev/null 2>&1 || MISSING_COMMANDS+=("${command_name}")
done
if [[ "${#MISSING_COMMANDS[@]}" -eq 0 ]]; then
  report "Required commands" PASS "az, azd, jq, curl, python3 found on PATH."
else
  AZURE_SAFE=0
  report "Required commands" FAIL "Install missing commands: ${MISSING_COMMANDS[*]}."
fi

# Log Analytics CLI extension ------------------------------------------------
# `az monitor log-analytics query` -- the only read behind the telemetry
# check and behind `baseline.sh`/`query-evidence.sh` -- ships in an extension
# that is not installed with the core CLI, so its absence is a prerequisite
# failure with its own row rather than a mysterious empty query result.
if ! command -v az >/dev/null 2>&1; then
  AZURE_SAFE=0
  report "Log Analytics CLI extension" FAIL "Blocked: install the Azure CLI first, then run: az extension add --name ${LOG_ANALYTICS_EXTENSION_NAME}"
elif log_analytics_extension_installed; then
  report "Log Analytics CLI extension" PASS "az monitor log-analytics query is available (extension ${LOG_ANALYTICS_EXTENSION_NAME})."
else
  AZURE_SAFE=0
  report "Log Analytics CLI extension" FAIL "az monitor log-analytics query is unavailable. Install it: az extension add --name ${LOG_ANALYTICS_EXTENSION_NAME}"
fi

# Azure CLI login ------------------------------------------------------------
if login_error="$(az account show --query id -o tsv 2>&1 1>/dev/null)"; then
  report "Azure CLI login" PASS "Signed in to Azure CLI."
else
  AZURE_SAFE=0
  report "Azure CLI login" FAIL "Run: az login -- ${login_error:-not signed in}"
fi

# azd authentication ---------------------------------------------------------
# azd keeps its own credential store: `az login` alone does not make
# `azd env`/`azd provision` work. `azd auth login --check-status` is the only
# non-interactive read of that state and always exits 0, so the row is
# decided by the status it prints, never by its exit code.
AZD_AUTH_STATUS=""
if command -v azd >/dev/null 2>&1; then
  AZD_AUTH_STATUS="$(azd_auth_status)"
fi
case "${AZD_AUTH_STATUS}" in
  success)
    report "azd authentication" PASS "azd reports an authenticated session (azd auth login --check-status)."
    ;;
  unauthenticated)
    AZURE_SAFE=0
    report "azd authentication" FAIL "azd is not signed in. Run: azd auth login"
    ;;
  *)
    AZURE_SAFE=0
    report "azd authentication" FAIL "azd did not report a login status. Check it by hand: azd auth login --check-status, then run: azd auth login"
    ;;
esac

# azd configuration -----------------------------------------------------------
# `require_lab_config` must run in *this* shell (not a subshell) so the
# resolved SUBSCRIPTION_ID/RESOURCE_GROUP/etc. it makes readonly survive for
# every check below; only its stderr is captured to a scratch file.
mkdir -p "${EVIDENCE_ROOT}"
CONFIG_ERROR_FILE="${EVIDENCE_ROOT}/.doctor-config-error"
: >"${CONFIG_ERROR_FILE}"
if require_lab_config 2>"${CONFIG_ERROR_FILE}"; then
  report "azd configuration" PASS "Resolved subscription ${SUBSCRIPTION_ID}, resource group ${RESOURCE_GROUP}, environment ${AZURE_ENV_NAME}."
else
  AZURE_SAFE=0
  CONFIG_DETAIL="$(tr '\n' ' ' <"${CONFIG_ERROR_FILE}" | sed 's/[[:space:]]*$//')"
  report "azd configuration" FAIL "${CONFIG_DETAIL:-Missing required azd configuration.}"
  # `load_lab_config` returns before its `readonly` line whenever a
  # required setting is missing, so none of these names are readonly yet
  # on this path -- safe (and necessary, under `set -u`) to re-seed them.
  SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-}"
  RESOURCE_GROUP="${RESOURCE_GROUP:-}"
  AZURE_ENV_NAME="${AZURE_ENV_NAME:-}"
  SRE_AGENT_RESOURCE_ID="${SRE_AGENT_RESOURCE_ID:-}"
fi
rm -f "${CONFIG_ERROR_FILE}"

# 2. Subscription equality ---------------------------------------------------
if [[ "${AZURE_SAFE}" -eq 1 ]]; then
  if subscription_error="$(verify_subscription 2>&1 1>/dev/null)"; then
    report "Subscription match" PASS "Active subscription matches ${SUBSCRIPTION_ID}."
  else
    AZURE_SAFE=0
    report "Subscription match" FAIL "${subscription_error}"
  fi
else
  report "Subscription match" FAIL "Blocked: resolve the failing check above first."
fi

# 3. Resource group tags -----------------------------------------------------
if [[ "${AZURE_SAFE}" -eq 1 ]]; then
  if rg_error="$(verify_lab_resource_group 2>&1 1>/dev/null)"; then
    report "Resource group tags" PASS "Resource group ${RESOURCE_GROUP} is tagged purpose=sre-agent-event-lab, azd-env-name=${AZURE_ENV_NAME}."
  else
    AZURE_SAFE=0
    report "Resource group tags" FAIL "${rg_error}"
  fi
else
  report "Resource group tags" FAIL "Blocked: resolve the failing check above first."
fi

if [[ "${AZURE_SAFE}" -eq 1 ]]; then
  APP_NAME="$(deployment_output containerAppName)"
  APP_FQDN="$(deployment_output containerAppFqdn)"
  WORKSPACE_CUSTOMER_ID="$(deployment_output workspaceCustomerId)"
  TELEMETRY_SERVICE_NAME="$(deployment_output telemetryServiceName)"
else
  APP_NAME=""
  APP_FQDN=""
  WORKSPACE_CUSTOMER_ID=""
  TELEMETRY_SERVICE_NAME=""
fi

# 4. Container App health and /healthz ---------------------------------------
if [[ "${AZURE_SAFE}" -eq 1 && -n "${APP_NAME}" ]]; then
  health_state="$(az containerapp revision list \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${APP_NAME}" \
    --query "[?properties.active].properties.healthState | [0]" \
    -o tsv 2>/dev/null || true)"
  if [[ "${health_state}" == "Healthy" ]]; then
    report "Container App health" PASS "Active revision of ${APP_NAME} is Healthy."
  else
    report "Container App health" FAIL "Active revision health is '${health_state:-unknown}'. Investigate: az containerapp revision list --resource-group ${RESOURCE_GROUP} --name ${APP_NAME}"
  fi
elif [[ "${AZURE_SAFE}" -eq 1 ]]; then
  report "Container App health" FAIL "Deployment output containerAppName is empty. Run: azd provision"
else
  report "Container App health" FAIL "Blocked: resolve the failing check above first."
fi

if [[ "${AZURE_SAFE}" -eq 1 && -n "${APP_FQDN}" ]]; then
  http_status="$(curl --max-time 10 --silent --output /dev/null --write-out '%{http_code}' "https://${APP_FQDN}/healthz" 2>/dev/null || echo 000)"
  if [[ "${http_status}" == "200" ]]; then
    report "Health endpoint" PASS "https://${APP_FQDN}/healthz returned HTTP 200."
  else
    report "Health endpoint" FAIL "https://${APP_FQDN}/healthz returned HTTP ${http_status}. Investigate: curl -v https://${APP_FQDN}/healthz"
  fi
elif [[ "${AZURE_SAFE}" -eq 1 ]]; then
  report "Health endpoint" FAIL "Deployment output containerAppFqdn is empty. Run: azd provision"
else
  report "Health endpoint" FAIL "Blocked: resolve the failing check above first."
fi

# 5. Application Insights request telemetry in the last 30 minutes ----------
# The query projects and `take`s real rows instead of `| count`: KQL's
# `count` always returns exactly one row (`Count: 0` for an empty table), so
# a row count taken from it can never distinguish data from no data. The
# extension prints a flat JSON array, and `log_analytics_row_count` parses
# that shape (see common.sh).
if [[ "${AZURE_SAFE}" -eq 1 && -n "${WORKSPACE_CUSTOMER_ID}" && -n "${TELEMETRY_SERVICE_NAME}" ]]; then
  request_rows="$(log_analytics_row_count "${WORKSPACE_CUSTOMER_ID}" PT30M \
    "AppRequests | where AppRoleName == '${TELEMETRY_SERVICE_NAME}' | project TimeGenerated, Name | take 1")"
  if [[ "${request_rows:-0}" -gt 0 ]]; then
    report "Application Insights telemetry" PASS "AppRequests present for ${TELEMETRY_SERVICE_NAME} in the last 30 minutes."
  else
    report "Application Insights telemetry" FAIL "No AppRequests telemetry in the last 30 minutes for role ${TELEMETRY_SERVICE_NAME}. Run: lab.sh baseline"
  fi
elif [[ "${AZURE_SAFE}" -eq 1 ]]; then
  report "Application Insights telemetry" FAIL "Deployment outputs workspaceCustomerId/telemetryServiceName are empty. Run: azd provision"
else
  report "Application Insights telemetry" FAIL "Blocked: resolve the failing check above first."
fi

# 6. Three alert rules enabled ------------------------------------------------
if [[ "${AZURE_SAFE}" -eq 1 ]]; then
  DISABLED_RULES=()
  for rule_name in alert-sre-lab-s1-http500 alert-sre-lab-s2-latency alert-sre-lab-s3-storage-rbac; do
    rule_json="$(az rest --method get \
      --url "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/microsoft.insights/scheduledqueryrules/${rule_name}?api-version=2023-12-01" \
      -o json 2>/dev/null || true)"
    if [[ -z "${rule_json}" ]]; then
      rule_json='{}'
    fi
    rule_enabled="$(jq -r '.properties.enabled // false' <<<"${rule_json}" 2>/dev/null || echo false)"
    if [[ "${rule_enabled}" != "true" ]]; then
      DISABLED_RULES+=("${rule_name}")
    fi
  done
  if [[ "${#DISABLED_RULES[@]}" -eq 0 ]]; then
    report "Alert rules enabled" PASS "alert-sre-lab-s1-http500, alert-sre-lab-s2-latency, alert-sre-lab-s3-storage-rbac are all enabled."
  else
    report "Alert rules enabled" FAIL "Not enabled or missing: ${DISABLED_RULES[*]}. Re-enable: az resource update --ids <ruleResourceId> --set properties.enabled=true (or re-run azd provision)."
  fi
else
  report "Alert rules enabled" FAIL "Blocked: resolve the failing check above first."
fi

# 7. SRE Agent resource, only when SRE_AGENT_RESOURCE_ID is configured -------
if [[ -n "${SRE_AGENT_RESOURCE_ID}" ]]; then
  if [[ "${AZURE_SAFE}" -eq 1 ]]; then
    if az resource show --ids "${SRE_AGENT_RESOURCE_ID}" -o none 2>/dev/null; then
      report "SRE Agent resource" PASS "Resource exists: ${SRE_AGENT_RESOURCE_ID}."
    else
      report "SRE Agent resource" FAIL "Resource not found: ${SRE_AGENT_RESOURCE_ID}. Verify: az resource show --ids ${SRE_AGENT_RESOURCE_ID}"
    fi
  else
    report "SRE Agent resource" FAIL "Blocked: resolve the failing check above first."
  fi
fi

# 8. Reader role assignment on the lab resource group ------------------------
# `--include-inherited` is deliberate: Reader granted at the subscription (or
# management group) gives the Agent exactly the effective read access it
# needs on this resource group, and omitting the flag hides those grants
# entirely -- `az role assignment list` returns only assignments made at the
# queried scope without it -- which would report a working setup as broken.
# The detail still distinguishes the two, because an operator who requires an
# explicit resource-group-scoped assignment has to be able to see that the
# access is only inherited.
if [[ "${AZURE_SAFE}" -eq 1 ]]; then
  RESOURCE_GROUP_SCOPE="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}"
  if [[ ! -f "${AGENT_SETUP_FILE}" ]]; then
    report "Reader role assignment" FAIL "Agent setup evidence missing: ${AGENT_SETUP_FILE}. Run: lab.sh acknowledge agent-setup after recording the Agent identities."
  elif ! AGENT_SETUP_JSON="$(jq '.' "${AGENT_SETUP_FILE}" 2>/dev/null)"; then
    # A hand-edited or truncated evidence file is one FAIL row, not a raw
    # `jq` abort: under `set -e` an unguarded parse would kill the run and
    # swallow every remaining check, including the MANUAL rows an operator
    # still needs.
    report "Reader role assignment" FAIL "Agent setup evidence is not valid JSON: ${AGENT_SETUP_FILE}. Recreate it: lab.sh acknowledge agent-setup"
  else
    agent_principal_id="$(jq -r '.agent_principal_id // empty' <<<"${AGENT_SETUP_JSON}" 2>/dev/null || true)"
    agent_uami_principal_id="$(jq -r '.agent_user_assigned_principal_id // empty' <<<"${AGENT_SETUP_JSON}" 2>/dev/null || true)"
    if [[ -z "${agent_principal_id}" || -z "${agent_uami_principal_id}" ]]; then
      report "Reader role assignment" FAIL "Agent setup evidence is missing agent_principal_id/agent_user_assigned_principal_id: ${AGENT_SETUP_FILE}."
    else
      MISSING_READER=()
      INHERITED_READER=()
      for principal_id in "${agent_principal_id}" "${agent_uami_principal_id}"; do
        assignments_json="$(az role assignment list \
          --resource-group "${RESOURCE_GROUP}" \
          --assignee-object-id "${principal_id}" \
          --include-inherited \
          -o json 2>/dev/null || true)"
        if [[ -z "${assignments_json}" ]]; then
          assignments_json='[]'
        fi
        direct_count="$(jq --arg scope "${RESOURCE_GROUP_SCOPE}" '
          [.[]? | select((.roleDefinitionName // "") == "Reader")
                | select(((.scope // "") | ascii_downcase) == ($scope | ascii_downcase))]
          | length' <<<"${assignments_json}" 2>/dev/null || echo 0)"
        inherited_scope="$(jq -r --arg scope "${RESOURCE_GROUP_SCOPE}" '
          [.[]? | select((.roleDefinitionName // "") == "Reader")
                | select(((.scope // "") | ascii_downcase) != ($scope | ascii_downcase))
                | .scope]
          | first // empty' <<<"${assignments_json}" 2>/dev/null || true)"
        if [[ "${direct_count:-0}" -gt 0 ]]; then
          continue
        elif [[ -n "${inherited_scope}" ]]; then
          INHERITED_READER+=("${principal_id} (inherited from ${inherited_scope})")
        else
          MISSING_READER+=("${principal_id}")
        fi
      done
      if [[ "${#MISSING_READER[@]}" -gt 0 ]]; then
        report "Reader role assignment" FAIL "Missing Reader on ${RESOURCE_GROUP} (direct or inherited) for: ${MISSING_READER[*]}. Grant: az role assignment create --assignee-object-id <id> --assignee-principal-type ServicePrincipal --role Reader --resource-group ${RESOURCE_GROUP}"
      elif [[ "${#INHERITED_READER[@]}" -gt 0 ]]; then
        report "Reader role assignment" PASS "Reader is effective on ${RESOURCE_GROUP} for both recorded Agent identities; not assigned directly for: ${INHERITED_READER[*]}. Inherited access is sufficient to read the lab; assign it on ${RESOURCE_GROUP} if the setup must be scoped to this lab only."
      else
        report "Reader role assignment" PASS "Reader is assigned directly on ${RESOURCE_GROUP} for both recorded Agent identities."
      fi
    fi
  fi
else
  report "Reader role assignment" FAIL "Blocked: resolve the failing check above first."
fi

# 9. Portal-only settings: never inferred, always MANUAL ---------------------
# No official stable Azure SRE Agent API currently reads back the
# repository connection, knowledge sources, incident platform, or response
# plan mode, so these are never reported as PASS/FAIL -- doing so would
# mean guessing. They stay MANUAL until an official stable API can prove
# them, matching the portal path an operator needs to check by hand.
report "Repository connection" MANUAL "No official stable API exposes the Agent's repository connection state. Verify in the portal: https://sre.azure.com > Agent > Settings > Repository."
report "Knowledge source" MANUAL "No official stable API exposes configured knowledge sources. Verify in the portal: https://sre.azure.com > Agent > Settings > Knowledge."
report "Incident platform" MANUAL "No official stable API exposes the incident platform connection. Verify in the portal: https://sre.azure.com > Agent > Settings > Incident platform."
report "Response plan" MANUAL "No official stable API confirms the response plan mode. Verify in the portal: https://sre.azure.com > Agent > Response plans (must be Review)."

exit "${ANY_FAIL}"
