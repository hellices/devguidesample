#!/usr/bin/env bash
# preprovision: validates the operator context and prepares non-secret azd inputs.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands az azd curl openssl ssh-keygen kubectl kubelogin helm python3

AZURE_SUBSCRIPTION_ID="$(env_value AZURE_SUBSCRIPTION_ID)"
[[ -n "$AZURE_SUBSCRIPTION_ID" ]] || die "run azd env set AZURE_SUBSCRIPTION_ID <subscription-id> first"
assert_active_subscription

LOCATION="$(env_value AZURE_LOCATION)"
if [[ -z "$LOCATION" ]]; then
  azd_env set AZURE_LOCATION koreacentral
fi

for namespace in Microsoft.EventHub Microsoft.ContainerService Microsoft.Compute Microsoft.Insights \
  Microsoft.KeyVault Microsoft.ContainerRegistry Microsoft.Network Microsoft.Storage Microsoft.ManagedIdentity; do
  state="$(az provider show --subscription "$AZURE_SUBSCRIPTION_ID" --namespace "$namespace" --query registrationState -o tsv)"
  [[ "$state" == "Registered" ]] || die "resource provider is not registered: $namespace ($state)"
done

EGRESS_IP="$(curl -4 --fail --silent --show-error --max-time 10 https://api.ipify.org)"
[[ "$EGRESS_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "could not determine an IPv4 egress address"
azd_env set OPERATOR_EGRESS_CIDR "${EGRESS_IP}/32"
log "Grafana and the AKS API server will accept only the current operator egress /32."

USER_TYPE="$(az account show --query user.type -o tsv)"
if [[ "$USER_TYPE" == "user" ]]; then
  PRINCIPAL_ID="$(az ad signed-in-user show --query id -o tsv)"
  PRINCIPAL_TYPE=User
else
  PRINCIPAL_ID="$(az ad sp show --id "$(az account show --query user.name -o tsv)" --query id -o tsv)"
  PRINCIPAL_TYPE=ServicePrincipal
fi
azd_env set AZURE_PRINCIPAL_ID "$PRINCIPAL_ID"
azd_env set AZURE_PRINCIPAL_TYPE "$PRINCIPAL_TYPE"

if [[ -z "$(env_value GRAFANA_ADMIN_PASSWORD)" ]]; then
  azd_env set GRAFANA_ADMIN_PASSWORD "$(openssl rand -base64 30 | tr -d '/+=' | cut -c1-32)"
fi

KEY_DIR="$(state_dir)"
if [[ ! -f "$KEY_DIR/gateway_ed25519" ]]; then
  ssh-keygen -q -t ed25519 -N '' -C eventhubs-otel-lab -f "$KEY_DIR/gateway_ed25519"
elif [[ ! -s "$KEY_DIR/gateway_ed25519.pub" ]]; then
  ssh-keygen -y -f "$KEY_DIR/gateway_ed25519" >"$KEY_DIR/gateway_ed25519.pub"
fi
azd_env set GATEWAY_ADMIN_SSH_PUBLIC_KEY "$(<"$KEY_DIR/gateway_ed25519.pub")"
log "preprovision checks passed."
