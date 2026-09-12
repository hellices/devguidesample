# MCP + Entra isolated Azure lab

Read-only examples for:

- GitHub and Microsoft Learn hosted MCP.
- Azure MCP 2.0.5 and AKS MCP 0.0.20 local stdio.
- Native Azure MCP with Entra OBO in an internal Container Apps environment.
- A separate Python MCP SDK 2.2.0 resource server.
- **APIM native REST-operation-to-MCP-tool conversion**, separately from an existing MCP proxy.

The [Korean lab guide](../../../docs/labs/azure-api-management/mcp-rest-and-upstream/index.md), [architecture research](../../../docs/research/azure-api-management/mcp-authentication-options/index.md), and [actual observations](../../../docs/cases/azure-api-management/mcp-entra-validation/index.md) explain scope, costs, diagrams and evidence.

## Boundaries

This is a paid, non-production lab. One explicit RG is created, plus AKS and Container Apps provider-managed RGs. Entra apps are tenant objects. Existing resources and the default kubeconfig are not adopted.

The private-network probe uses authenticated `kubectl port-forward`, not a corporate VPN. GitHub credentials are never uploaded to Azure. The public `/inventory` route contains only fictitious widgets; it is not a template for exposing business data.

## Setup and deployment

Run from the repository root with Python 3.13, Azure CLI, Bicep, Node 20+, `gh`, `kubectl` and `kubelogin`. Azure CLI must have a user login. The operator needs deployment, role-assignment and appropriate tenant app/consent permissions.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
export LAB_SAMPLE="samples/azure-api-management/mcp-entra-lab"
python -m pip install -r requirements-docs.txt -r "$LAB_SAMPLE/requirements.txt"
npm ci --prefix "$LAB_SAMPLE" --no-audit --no-fund

export LAB_PRIVATE="$(mktemp -d)"
chmod 700 "$LAB_PRIVATE"
export LAB_STATE="$LAB_PRIVATE/state.json"
export PYTHONPATH="$LAB_SAMPLE"

python -m cloud_lab --state "$LAB_STATE" plan --location koreacentral
python -m cloud_lab --state "$LAB_STATE" validate
python -m cloud_lab --state "$LAB_STATE" deploy-foundation
python -m entra_setup --state "$LAB_STATE" apps
python -m entra_setup --state "$LAB_STATE" grant-operator
python -m entra_setup --state "$LAB_STATE" federate-azure
python -m auth_probe --state "$LAB_STATE" --output "$LAB_SAMPLE/evidence/auth-local-live.json"

python -m cloud_stage --state "$LAB_STATE" build
python -m cloud_stage --state "$LAB_STATE" deploy-apps
python -m cloud_stage --state "$LAB_STATE" deploy-apim
python -m network_probe --state "$LAB_STATE" prepare
```

Keep the state directory for resuming and cleanup. It contains actual identifiers and a short-lived lab secret. Do not commit or publish it. Production images are built in ACR, so a local Docker daemon is not required.

In a separate terminal with the same environment:

```bash
python -m network_probe --state "$LAB_STATE" forward
```

This chooses an unused loopback port and writes its URL to private `network.json`. SDK clients use that HTTP CONNECT proxy while retaining end-to-end HTTPS hostname verification.

## Pinned AKS MCP runtime

The following is the **macOS arm64** asset verified in this run. For another platform choose the corresponding asset and its published digest from the same release.

```bash
export AKS_MCP_BIN="$LAB_PRIVATE/aks-mcp"
gh release download v0.0.20 --repo Azure/aks-mcp \
  --pattern aks-mcp-darwin-arm64 --output "$AKS_MCP_BIN"
printf '%s  %s\n' \
  '1104b6abfeec05de836b67f309c47bdfff4aaa1d21f78505a4a1c090a0ef5c61' \
  "$AKS_MCP_BIN" | shasum -a 256 -c - &&
  chmod 700 "$AKS_MCP_BIN"
```

Do not execute a download with a mismatched digest. AKS MCP 0.0.20 is local stdio-only; do not add removed HTTP/OBO/Helm flags.

## Real verification

```bash
python -m probe_upstreams --state "$LAB_STATE" --aks-binary "$AKS_MCP_BIN" \
  --output "$LAB_SAMPLE/evidence/upstreams.json"
python -m probe_cloud --state "$LAB_STATE" \
  --output "$LAB_SAMPLE/evidence/cloud.json"
python -m probe_native_gate --state "$LAB_STATE" \
  --output "$LAB_SAMPLE/evidence/native-client-gate.json" --exercise-denial
python -m pytest "$LAB_SAMPLE/tests" -q
```

Use `probe_upstreams --only github|learn|azure|aks` for targeted diagnosis. Azure stdio explicitly selects the Azure CLI credential; hosted Azure MCP instead uses the configured OBO strategy.

The probes validate MCP `is_error`, JSON/command status, requested resource-group membership, generated tool schemas and real backend correlation. A suite-complete record is written only after all its checks finish. An interrupted run is not a passing suite.

`probe_native_gate` is read-only by default. `--exercise-denial` deliberately removes only the Azure CLI client from the new native app's nonempty allowlist, verifies that the same otherwise-valid token is denied, and restores the original policy in `finally`. Run this opt-in test only while the lab is reserved for validation; it briefly blocks that client.

`evidence.py` accepts only allowlisted measurements. Render captured data, not invented portal screenshots:

```bash
python -m evidence "$LAB_SAMPLE/evidence/cloud.json" "$LAB_SAMPLE/evidence/cloud.html"
```

## Local development client configuration

[mcp.example.json](mcp.example.json) is a VS Code-style configuration to merge into a local `.vscode/mcp.json`. Keep real endpoint values in local inputs, not the public repository. Do not replace the repository's existing MCP configuration blindly.

- Local Azure/AKS credentials and remote GitHub authorization are separate.
- Private examples are explicitly **manual-token** clients. Tokens expire and are not automatically refreshed by a pasted input.
- Native Azure and custom/APIM API tokens have different audiences; their inputs must not be interchanged.
- The SDK probes are verified. Each IDE's trust prompts, interactive OAuth/PKCE and corporate private route require separate testing.
- Private HTTP endpoints need an actual private route. The SDK probe's per-client CONNECT proxy is not automatically inherited by VS Code.

## Configuration

The Python server uses `service.app:create_app` on port 8000. Required environment variables are `ENTRA_TENANT_ID` (GUID), `ENTRA_API_CLIENT_ID`, `ENTRA_API_CLIENT_SECRET`, `MCP_RESOURCE_URL` (HTTPS `/mcp`), `LAB_SUBSCRIPTION_ID`, `LAB_RESOURCE_GROUP` and a nonempty CSV `ENTRA_ALLOWED_CLIENT_IDS`. Missing/empty client allowlists fail closed.

The native Azure MCP container keeps its own token/scope validation, while Container Apps authentication separately enforces `defaultAuthorizationPolicy.allowedApplications`. App-registration preauthorization alone is not a caller ACL. Public exceptions are limited to health and protected-resource metadata; no extra client secret is used by this bearer-validation layer.

| Route | Purpose |
|---|---|
| `POST /mcp` | Entra-protected MCP |
| `GET /.well-known/oauth-protected-resource/mcp` | Public metadata, no business data |
| `GET /healthz` | Public liveness |
| `GET /inventory` | Fictitious REST fixture with a fresh invocation marker; rejects an Authorization header |
| `GET /delegated-resource-group` | Separately enforced authenticated OBO REST route |

App-only tokens can carry an `oid`; the delegated scope gate is essential. Entra's bare JWT `scp` is normalized to the qualified OAuth scope only after signature/audience validation. The server surfaces OBO errors rather than falling back to managed identity. Full Conditional Access reauthentication UI is not implemented.

## Cleanup

Stop the local tunnel first. Preview checks ownership without deleting anything:

```bash
python -m cleanup --state "$LAB_STATE"
```

Only after reviewing the private state's lab identity, explicitly confirm deletion:

```bash
python -m cleanup --state "$LAB_STATE" \
  --confirm-delete "$(jq -r .suffix "$LAB_STATE")"
```

The command verifies ownership, removes recorded service principals/apps, deletes the lab RG and checks provider-managed RG removal. Deletion requires real Graph/ARM permissions and was **not executed** for the published run; its ownership preview and unit guards were checked.

The expiry tag does not delete resources. PR creation/merge does not stop billing. The lab secret expires after two days; the native server's managed-identity federation is a separate credential mechanism.
