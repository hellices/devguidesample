# Azure MCP + Entra ID walkthrough

Read the [Azure MCP solution guide](../../../docs/guides/azure-architecture/mcp-configuration/index.md) for APIM, Toolbox, IQ tools and the distinction between MCP authorization and OBO. Follow [walkthrough.md](walkthrough.md) for this sample's concrete deployment and requests. GitHub, Azure, AKS and Learn are demonstration backends, not competing architecture choices.

## What is deployed

- Internal Azure API Management Developer gateway: native REST-to-MCP and a Microsoft Learn MCP proxy.
- Internal Container Apps environment: Azure MCP 2.0.5 with Entra OBO and a Python MCP server.
- AKS cluster for the local AKS MCP example and an optional private-network tunnel.
- ACR for `azd` remote builds, private DNS and managed identities.

One project resource group plus AKS/Container Apps managed resource groups are created. Three Entra app registrations are tracked separately because they are directory objects, not ARM resources.

## Prerequisites

- Azure Developer CLI (`azd`) 1.29+, Azure CLI and Bicep.
- Python 3.13 for local MCP clients; the azd identity hook also supports Python 3.9+.
- Node.js 22.19+, npm, `curl`, `jq`, `kubectl`, `kubelogin` and GitHub CLI.
- An Azure subscription with permissions to create resources and role assignments.
- Entra permissions to register applications and grant the operator's delegated permission to ARM.

Use Bash for the documented commands. No local Docker daemon is required: `docker.remoteBuild: true` uses ACR.

## Deploy

Run inside this sample directory:

```bash
az login
azd auth login
azd env new mcpdemo01
azd env set AZURE_SUBSCRIPTION_ID "$(az account show --query id -o tsv)"
azd env set AZURE_LOCATION koreacentral
python3 scripts/identity.py prepare
azd provision --preview
azd up
```

Choose a unique environment name of 6–10 lowercase letters/digits. The template creates `rg-<environment>`. It does not adopt unrelated resource groups.

Prepare the directory objects before `azd provision --preview`, because `azd` resolves required Bicep inputs before a provisioning hook. `azd up` also performs this idempotent preparation through its `preup` hook, then provisions Bicep, builds the image in ACR and deploys the declared `mcp` service. The hooks only manage Entra objects; they do not run a custom Azure deployment pipeline.

The `.azure/` directory contains environment settings and a short-lived credential. It is ignored by Git. Do not publish it or capture `azd env get-values` output. `azd provision` alone leaves a placeholder Python application until `azd deploy mcp` runs.

## Follow the scenarios

Use the [sample walkthrough](walkthrough.md) in order:

1. Inspect the deployed resources and private endpoints.
2. Connect local GitHub, Azure, AKS and Microsoft Learn MCP clients.
3. Connect from the local PC to the internal endpoints.
4. Obtain Entra access tokens and inspect an unauthenticated response.
5. Call an existing REST API as an APIM MCP tool.
6. Call Azure MCP and the Python MCP tool with OBO.
7. Call Microsoft Learn through APIM.
8. Check 401/403 behavior and remove the environment when finished.

[requests/](requests/) contains JSON-RPC request bodies, not tests. [mcp.example.json](mcp.example.json) shows VS Code MCP connections. [network/](network/) provides an optional loopback-only CONNECT tunnel for a workstation without a VPN route to the VNet.

## Application configuration

The Python application runs `service.app:create_app` on port 8000.

| Setting | Purpose |
|---|---|
| `ENTRA_TENANT_ID` | Tenant GUID used for issuer and JWKS |
| `ENTRA_API_CLIENT_ID` | Intended access-token audience |
| `ENTRA_API_CLIENT_SECRET` | Short-lived confidential-client credential for the OBO example |
| `ENTRA_ALLOWED_CLIENT_IDS` | Required, nonempty client allowlist |
| `MCP_RESOURCE_URL` | HTTPS MCP URL |
| `LAB_SUBSCRIPTION_ID`, `LAB_RESOURCE_GROUP` | Fixed ARM resource-group target |

The authenticated `/mcp` endpoint exposes `lab_inventory`, `read_lab_resource_group` and `learn_search`. `/healthz` and `/inventory` contain no protected business data. The REST inventory rejects Authorization headers so an APIM policy that accidentally forwards a token is visible.

Native Azure MCP uses a separate Entra API and `Mcp.Tools.ReadWrite`. Its managed identity authenticates the confidential client through federation; the downstream ARM request uses the user's OBO token. Container Apps authentication restricts permitted client applications.

## Cleanup

Close any local port-forward first. Remove ARM resources with:

```bash
azd down
```

Then explicitly remove this environment's Entra objects:

```bash
python3 scripts/identity.py remove --confirm "$(azd env get-value AZURE_ENV_NAME)"
```

The identity command checks recorded app IDs and ownership tags. It does not grant tenant-wide consent or remove unrelated apps. Keep `.azure/` until both cleanup steps have finished.

APIM Developer, the AKS node and other infrastructure incur charges even when no MCP tool is called. The `expiresOn` tag is informational, not automatic cleanup.
