# Microsoft Foundry Toolbox for MCP

This example publishes Microsoft Learn MCP tools through a Foundry Toolbox. It has a normal `learn-tools` service and a separate `learn-tools-search` service that demonstrates deferred discovery. It does not provision API Management, a model deployment or a new Foundry project.

Use the [MCP operating architecture](../../../docs/guides/azure-architecture/mcp-configuration/index.md) to distinguish agent runtime, Toolbox discovery, APIM governance and backend hosting. This sample demonstrates tooling with Learn; it is not a comparison of customer MCP products.

## Prerequisites

- An existing Microsoft Foundry project and its project endpoint.
- The **Foundry User** role on that project for the developer and the appropriate consuming identity.
- Azure Developer CLI 1.29+, the `microsoft.foundry` extension, Azure CLI, Node.js 22.19+ and `jq`.
- Connectivity to the Foundry project endpoint. A private project requires its private route and DNS configuration.

## Configure and publish

Run from this sample directory. Use a separate environment from the Container Apps/APIM lab.

```bash
azd extension install microsoft.foundry
azd auth login
az login
azd env new toolboxdemo
azd env set AZURE_SUBSCRIPTION_ID "$(az account show --query id -o tsv)"

read -r -p "Foundry project endpoint: " PROJECT_ENDPOINT
azd env set FOUNDRY_PROJECT_ENDPOINT "$PROJECT_ENDPOINT"
azd ai toolbox list --project-endpoint "$PROJECT_ENDPOINT"
azd deploy learn-tools
```

Use an unused toolbox name. If `learn-tools` already belongs to another application, rename the service and corresponding commands before deploying; do not update or delete that shared toolbox.

The declared `learn-tools` service is a managed Toolbox configuration, not a container-hosted MCP application. The external Learn MCP server remains the backend. `require_approval: never` is limited here to that read-only documentation source; choose an approval policy appropriate to other tools.

## Connect an MCP client

```bash
azd ai toolbox show learn-tools --project-endpoint "$PROJECT_ENDPOINT" --output json
export TOOLBOX_ENDPOINT="${PROJECT_ENDPOINT%/}/toolboxes/learn-tools/mcp?api-version=v1"

umask 077
mkdir -p .private
az account get-access-token --scope https://ai.azure.com/.default -o json \
  | jq --arg url "$TOOLBOX_ENDPOINT" '{mcpServers:{toolbox:{
      type:"streamable-http",url:$url,headers:{Authorization:("Bearer "+.accessToken)}
    }}}' > .private/toolbox-client.json

npx --yes @modelcontextprotocol/inspector@2.5.0 --cli \
  --config .private/toolbox-client.json --server toolbox --method tools/list
```

Use the actual tool name from `tools/list`; Toolbox can qualify names. Select the Learn search tool and call it:

```bash
read -r -p "Learn search tool name from tools/list: " SEARCH_TOOL
npx --yes @modelcontextprotocol/inspector@2.5.0 --cli \
  --config .private/toolbox-client.json --server toolbox \
  --method tools/call --tool-name "$SEARCH_TOOL" \
  --tool-arg 'query=Azure MCP hosting options'
```

The consumer authenticates to Foundry. The downstream Learn request is anonymous. Do not pass the Foundry access token to an arbitrary downstream MCP server.

## Compare normal discovery and Tool search

Use an unused `learn-tools-search` name; check the project toolbox list before deploying. Deploy only the second service when you want this comparison:

```bash
azd deploy learn-tools-search
export SEARCH_ENDPOINT="${PROJECT_ENDPOINT%/}/toolboxes/learn-tools-search/mcp?api-version=v1"
jq --arg url "$SEARCH_ENDPOINT" '.mcpServers.toolbox.url=$url' \
  .private/toolbox-client.json > .private/toolbox-search-client.json

npx --yes @modelcontextprotocol/inspector@2.5.0 --cli \
  --config .private/toolbox-search-client.json --server toolbox --method tools/list
```

Look for `tool_search` and `call_tool`. Explicitly pinned or auto-pinned tools may also appear; do not require the result count to be exactly two.

Search for the capability you need:

```bash
npx --yes @modelcontextprotocol/inspector@2.5.0 --cli \
  --config .private/toolbox-search-client.json --server toolbox \
  --method tools/call --tool-name tool_search \
  --tool-arg 'query=Search official Microsoft documentation' --tool-arg limit=3
```

Read the returned tool definitions. To invoke the selected tool, open the Inspector against this configuration, select `call_tool`, and fill its actual `inputSchema` with the selected tool name and arguments:

```bash
npx --yes @modelcontextprotocol/inspector@2.5.0 \
  --config .private/toolbox-search-client.json
```

Learn has only a few tools, so this is a protocol/configuration demonstration, **not a token-savings benchmark**. For a business catalog, compare the same model, task set, permissions and toolbox version with and without Tool search. Record cumulative model input/output tokens, cache usage, search round-trips, task latency and correctness. Do not infer end-to-end savings from the smaller initial `tools/list` alone.

Tool search uses metadata ranking; improve descriptions and `additional_search_text`, then pin only genuinely frequent tools. It does not replace backend authorization or API gateway policy.

## Use the tools from a hosted agent

Follow [hosted-agent.md](hosted-agent.md) for the maintained Foundry hosted-agent sample. That agent is a consumer of Toolbox; it is not the MCP backend server.

## Versions and cleanup

Use the version-specific endpoint before promoting a new default version:

```text
<project-endpoint>/toolboxes/learn-tools/versions/<version>/mcp?api-version=v1
```

```bash
azd ai toolbox versions list learn-tools --project-endpoint "$PROJECT_ENDPOINT"
read -r -p "Version to make default: " TOOLBOX_VERSION
azd ai toolbox publish learn-tools "$TOOLBOX_VERSION" --project-endpoint "$PROJECT_ENDPOINT"
```

Delete only this toolbox when finished:

```bash
azd ai toolbox delete learn-tools --project-endpoint "$PROJECT_ENDPOINT"
azd ai toolbox delete learn-tools-search --project-endpoint "$PROJECT_ENDPOINT"
```

Delete `learn-tools-search` only if you created it. Do not delete a shared Foundry project or its resource group to remove this example. The local `.private/` client files contain short-lived bearer tokens and must not be committed.

## Verification scope

The configuration and commands were checked against the official Toolbox documentation and installed CLI help. This example is not included in the live Container Apps/APIM execution captures.

Sources: [Toolbox overview](https://learn.microsoft.com/azure/foundry/agents/concepts/toolbox-overview), [create and manage a toolbox](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox), [Tool search](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-search), [network isolation](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox-network-isolation).
