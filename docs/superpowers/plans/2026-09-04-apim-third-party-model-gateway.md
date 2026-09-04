# APIM Third-Party Model Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deployable reference configuration that attaches provider-native
Gemini, Anthropic, Bedrock, Vertex AI, and optional MCP resource-server APIs to
an existing APIM service, with documented security boundaries and offline
validation.

**Architecture:** The Bicep deployment imports one small OpenAPI contract per
provider, creates fixed APIM backends, and attaches a policy to each API. Common
fragments authenticate callers with Entra JWTs, rate limit requests, and perform
fail-closed inbound PII detection. Vertex traffic is sent only to a private
broker; the broker, not APIM, owns GCP Workload Identity Federation.

**Tech Stack:** Azure Bicep, Azure API Management policy XML, OpenAPI 3.0 JSON,
Python 3 standard library `unittest`, Bash, Azure CLI, Google Cloud CLI
instructions.

## Global Constraints

- Configure an **existing** APIM instance; do not create or alter live cloud
  resources in this task.
- Do not commit an API key, AWS credential, client secret, access token, or
  Google service-account JSON key.
- Use Key Vault-backed APIM named values for Gemini, Anthropic, Bedrock, and
  Azure Language PII secrets.
- Keep each provider's native API schema; do not use preview Unified Model API.
- Send Vertex requests only to a private broker. Do not implement the
  undocumented APIM-only managed-identity-to-Google-STS exchange.
- Document that Bedrock IAM-user keys are a documented APIM pattern but not the
  preferred production identity model.
- Configure inline PII detection to fail closed and block inbound PII. Do not
  claim that it safely redacts streaming output.
- Treat direct Entra v2 `scope` authorization as a private MCP compatibility
  profile, not full current MCP RFC 8707 compliance.
- Use `Microsoft.ApiManagement/service@2024-05-01` child resources and Bicep
  `loadTextContent()` for policy/OpenAPI assets.

---

## File Structure

| File | Responsibility |
|---|---|
| `apim/third-party-model-gateway/README.md` | Deployment prerequisites, parameterization, verification, supported routes, and known boundaries. |
| `apim/third-party-model-gateway/third-party-model-integration.md` | Official-source implementation guide and provider decision matrix. |
| `apim/third-party-model-gateway/infra/main.bicep` | Existing APIM child resources: named values, backends, OpenAPI APIs, policy fragments, and API policies. |
| `apim/third-party-model-gateway/infra/main.bicepparam` | Nonsecret deployment-parameter template. |
| `apim/third-party-model-gateway/openapi/*.json` | Minimal native provider contracts and the RFC 9728 MCP metadata route imported by APIM. |
| `apim/third-party-model-gateway/policies/common-*.xml` | Reusable caller-authentication, rate-limit, and PII inspection fragments. |
| `apim/third-party-model-gateway/policies/{gemini,anthropic,bedrock,vertex,mcp-resource-server,mcp-metadata}.xml` | Provider/resource-server routing, authentication, and MCP metadata policies. |
| `apim/third-party-model-gateway/scripts/configure-gcp-wif.sh` | Explicit, nonsecret GCP WIF prerequisite script for the Vertex broker identity. |
| `apim/third-party-model-gateway/scripts/validate.sh` | Runs Bicep compilation and static unit tests. |
| `apim/third-party-model-gateway/tests/test_gateway_artifacts.py` | Offline tests for artifact presence, JSON/XML parsing, cross-references, fixed backends, policy protections, and secret absence. |
| `aifoundry/ai-hub-llm-gateway-scaling-review.md` | Links the architectural assessment to the runnable APIM reference. |

## Interfaces

### Bicep Parameters

`infra/main.bicep` consumes:

```bicep
param apiManagementServiceName string
param apiPathPrefix string = 'ai'
param gatewayBaseUrl string
param entraTenantId string
param entraAudience string
param requiredScope string = 'ai.invoke'
param rateLimitCalls int = 60
param rateLimitRenewalPeriod int = 60
param maxInlinePiiCharacters int = 4096
param piiLanguage string = 'ko'
param languageEndpoint string
param geminiApiKeySecretIdentifier string
param anthropicApiKeySecretIdentifier string
param bedrockAccessKeySecretIdentifier string
param bedrockSecretKeySecretIdentifier string
param languageApiKeySecretIdentifier string
param bedrockRegion string
param vertexBrokerUrl string
param vertexBrokerResourceAudience string
param mcpAuthorizationServerOpenIdConfigurationUrl string
param mcpAuthorizationServerIssuer string
param mcpBackendUrl string
param mcpBackendResourceAudience string
```

Secret identifiers are Key Vault secret URIs, not secret values.

### APIM Routes

| Route | Upstream API | APIM backend ID |
|---|---|---|
| `/{apiPathPrefix}/gemini/v1beta/models/{model}:generateContent` | Gemini Developer API | `ai-hub-gemini` |
| `/{apiPathPrefix}/anthropic/v1/messages` | Anthropic Messages API | `ai-hub-anthropic` |
| `/{apiPathPrefix}/bedrock/model/{modelId}/converse` | Amazon Bedrock Runtime | `ai-hub-bedrock` |
| `/{apiPathPrefix}/vertex/v1/projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent` | Vertex AI through a private broker | `ai-hub-vertex-broker` |
| `/{apiPathPrefix}/mcp` | Streamable HTTP MCP backend | `ai-hub-mcp` |
| `/.well-known/oauth-protected-resource/{apiPathPrefix}/mcp` | MCP Protected Resource Metadata | none |

### Policy Fragments

- `ai-hub-client-auth`: validates caller JWT using the Entra v2 OpenID
  configuration, audience, and `scp` claim.
- `ai-hub-rate-limit`: limits requests by the validated JWT `oid` claim.
- `ai-hub-pii-inbound`: preserves the body, rejects bodies over the configured
  safe inline limit, calls Azure Language PII, and returns `400` if PII is
  found or `503` if inspection is unavailable.

## Task 1: Establish Offline Artifact Tests and Directory Skeleton

**Files:**
- Create: `apim/third-party-model-gateway/tests/test_gateway_artifacts.py`
- Create: `apim/third-party-model-gateway/scripts/validate.sh`
- Create: `apim/third-party-model-gateway/.gitignore`

**Interfaces:**
- Consumes: Repository root and the artifact paths specified above.
- Produces: `python3 -m unittest` validation with no cloud credentials and a
  single validation entry point for later tasks.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gateway_artifacts.py` with the following initial test shape:

```python
from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_FILES = (
    "gemini.json",
    "anthropic.json",
    "bedrock.json",
    "vertex.json",
    "mcp.json",
    "mcp-metadata.json",
)
POLICY_FILES = (
    "common-client-auth.xml",
    "common-rate-limit.xml",
    "common-pii-inbound.xml",
    "gemini.xml",
    "anthropic.xml",
    "bedrock.xml",
    "vertex.xml",
    "mcp-resource-server.xml",
    "mcp-metadata.xml",
)


class GatewayArtifactTests(unittest.TestCase):
    def test_expected_artifacts_exist(self) -> None:
        self.assertTrue((ROOT / "infra" / "main.bicep").is_file())
        for name in OPENAPI_FILES:
            self.assertTrue((ROOT / "openapi" / name).is_file(), name)
        for name in POLICY_FILES:
            self.assertTrue((ROOT / "policies" / name).is_file(), name)

    def test_openapi_documents_parse(self) -> None:
        for name in OPENAPI_FILES:
            with (ROOT / "openapi" / name).open(encoding="utf-8") as source:
                document = json.load(source)
            self.assertEqual("3.0.3", document["openapi"], name)
            self.assertTrue(document["paths"], name)

    def test_policy_documents_parse(self) -> None:
        for name in POLICY_FILES:
            root = ET.parse(ROOT / "policies" / name).getroot()
            self.assertIn(root.tag, {"policies", "fragment"}, name)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python3 -m unittest apim/third-party-model-gateway/tests/test_gateway_artifacts.py -v
```

Expected: `test_expected_artifacts_exist` fails because the Bicep, OpenAPI, and
policy artifacts do not exist yet.

- [ ] **Step 3: Create the validation wrapper and secret ignore rules**

Create `scripts/validate.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

az bicep build --file "$root/infra/main.bicep" --stdout >/dev/null
python3 -m unittest "$root/tests/test_gateway_artifacts.py" -v
```

Create `.gitignore`:

```gitignore
*.parameters.json
*.secrets.json
.env
```

Mark the wrapper executable with:

```bash
chmod +x apim/third-party-model-gateway/scripts/validate.sh
```

- [ ] **Step 4: Expand the static test contracts**

Add tests that later artifacts must satisfy:

```python
    def test_bicep_loads_every_policy_and_openapi_asset(self) -> None:
        source = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
        for name in OPENAPI_FILES:
            self.assertIn(f'loadTextContent(\'../openapi/{name}\')', source)
        for name in POLICY_FILES:
            self.assertIn(f'loadTextContent(\'../policies/{name}\')', source)

    def test_provider_policies_use_fixed_backends(self) -> None:
        expected = {
            "gemini.xml": "ai-hub-gemini",
            "anthropic.xml": "ai-hub-anthropic",
            "bedrock.xml": "ai-hub-bedrock",
            "vertex.xml": "ai-hub-vertex-broker",
            "mcp-resource-server.xml": "ai-hub-mcp",
        }
        for name, backend_id in expected.items():
            source = (ROOT / "policies" / name).read_text(encoding="utf-8")
            self.assertIn(f'<set-backend-service backend-id="{backend_id}"', source)

    def test_provider_policies_include_common_security_fragments(self) -> None:
        for name in ("gemini.xml", "anthropic.xml", "bedrock.xml", "vertex.xml"):
            source = (ROOT / "policies" / name).read_text(encoding="utf-8")
            self.assertIn('fragment-id="ai-hub-client-auth"', source)
            self.assertIn('fragment-id="ai-hub-rate-limit"', source)
            self.assertIn('fragment-id="ai-hub-pii-inbound"', source)
```

- [ ] **Step 5: Run the test again**

Run the command from Step 2.

Expected: it still fails because the implementation files have not yet been
added; the failure names now define the required artifacts.

- [ ] **Step 6: Commit the test skeleton**

```bash
git add apim/third-party-model-gateway/tests/test_gateway_artifacts.py \
  apim/third-party-model-gateway/scripts/validate.sh \
  apim/third-party-model-gateway/.gitignore
git commit -m "test(apim): define gateway artifact contracts"
```

## Task 2: Implement Bicep, Fixed Backends, and Native OpenAPI Contracts

**Files:**
- Create: `apim/third-party-model-gateway/infra/main.bicep`
- Create: `apim/third-party-model-gateway/infra/main.bicepparam`
- Create: `apim/third-party-model-gateway/openapi/gemini.json`
- Create: `apim/third-party-model-gateway/openapi/anthropic.json`
- Create: `apim/third-party-model-gateway/openapi/bedrock.json`
- Create: `apim/third-party-model-gateway/openapi/vertex.json`
- Create: `apim/third-party-model-gateway/openapi/mcp.json`
- Create: `apim/third-party-model-gateway/openapi/mcp-metadata.json`
- Modify: `apim/third-party-model-gateway/tests/test_gateway_artifacts.py`

**Interfaces:**
- Consumes: The Bicep parameter interface declared in this plan.
- Produces: Six APIM APIs, five fixed backends, six Key Vault-backed or
  nonsecret named values, and Bicep policy-fragment/API-policy references.

- [ ] **Step 1: Add Bicep security assertions to the failing test**

Add tests that ensure `main.bicep` declares the existing APIM parent, all fixed
backend names, Key Vault named values, and no direct Vertex AI public backend:

```python
    def test_bicep_declares_fixed_backends_and_key_vault_references(self) -> None:
        source = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
        self.assertIn("resource apim 'Microsoft.ApiManagement/service@2024-05-01' existing", source)
        for backend_id in (
            "ai-hub-gemini",
            "ai-hub-anthropic",
            "ai-hub-bedrock",
            "ai-hub-vertex-broker",
            "ai-hub-mcp",
        ):
            self.assertIn(f"name: '{backend_id}'", source)
        self.assertIn("secretIdentifier: geminiApiKeySecretIdentifier", source)
        self.assertIn("secretIdentifier: anthropicApiKeySecretIdentifier", source)
        self.assertIn("secretIdentifier: bedrockAccessKeySecretIdentifier", source)
        self.assertNotIn("aiplatform.googleapis.com", source)
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
python3 apim/third-party-model-gateway/tests/test_gateway_artifacts.py \
  GatewayArtifactTests.test_bicep_declares_fixed_backends_and_key_vault_references \
  -v
```

Expected: fail because `infra/main.bicep` does not exist.

- [ ] **Step 3: Add minimal native OpenAPI documents**

Implement each document with `openapi: "3.0.3"`, an `info` object, one POST
operation, a required path parameter where applicable, and a generic JSON
request/response schema.

Use these exact paths:

```text
gemini.json:    /v1beta/models/{model}:generateContent
anthropic.json: /v1/messages
bedrock.json:   /model/{modelId}/converse
vertex.json:    /v1/projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent
mcp.json:       / (mounted by the API at ${apiPathPrefix}/mcp, so the public
                  endpoint is {apiPathPrefix}/mcp, not {apiPathPrefix}/mcp/mcp)
```

For each LLM API, define:

```json
{
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": { "type": "object", "additionalProperties": true }
      }
    }
  },
  "responses": {
    "200": {
      "description": "Provider response",
      "content": {
        "application/json": {
          "schema": { "type": "object", "additionalProperties": true }
        }
      }
    }
  }
}
```

Keep the contract minimal. The passthrough schema must not imply that APIM
transforms one provider's request into another provider's format.

- [ ] **Step 4: Implement `infra/main.bicep`**

Declare the existing APIM service:

```bicep
targetScope = 'resourceGroup'

param apiManagementServiceName string
param apiPathPrefix string = 'ai'
param gatewayBaseUrl string
param entraTenantId string
param entraAudience string
param requiredScope string = 'ai.invoke'
param rateLimitCalls int = 60
param rateLimitRenewalPeriod int = 60
param maxInlinePiiCharacters int = 4096
param piiLanguage string = 'ko'
param languageEndpoint string
param geminiApiKeySecretIdentifier string
param anthropicApiKeySecretIdentifier string
param bedrockAccessKeySecretIdentifier string
param bedrockSecretKeySecretIdentifier string
param languageApiKeySecretIdentifier string
param bedrockRegion string
param vertexBrokerUrl string
param vertexBrokerResourceAudience string
param mcpAuthorizationServerOpenIdConfigurationUrl string
param mcpAuthorizationServerIssuer string
param mcpBackendUrl string
param mcpBackendResourceAudience string

resource apim 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apiManagementServiceName
}
```

Create Key Vault-backed named values named `ai-hub-gemini-api-key`,
`ai-hub-anthropic-api-key`, `ai-hub-bedrock-access-key`,
`ai-hub-bedrock-secret-key`, and `ai-hub-language-api-key`. Their properties
must include `secret: true` and the matching `keyVault.secretIdentifier`
parameter.

Create nonsecret named values named `ai-hub-entra-tenant-id`,
`ai-hub-entra-audience`, `ai-hub-required-scope`,
`ai-hub-rate-limit-calls`, `ai-hub-rate-limit-renewal-period`,
`ai-hub-max-inline-pii-characters`, `ai-hub-pii-language`,
`ai-hub-language-endpoint`, `ai-hub-bedrock-region`,
`ai-hub-vertex-broker-resource-audience`,
`ai-hub-mcp-openid-config`, `ai-hub-mcp-authorization-server-issuer`,
`ai-hub-mcp-resource-audience`, `ai-hub-mcp-resource-metadata-url`, and
`ai-hub-mcp-backend-resource-audience`.

Create fixed backend resources using `protocol: 'http'`, TLS validation, and
these URLs:

```bicep
url: 'https://generativelanguage.googleapis.com'
url: 'https://api.anthropic.com'
url: 'https://bedrock-runtime.${bedrockRegion}.amazonaws.com'
url: validatedVertexBrokerUrl
url: mcpBackendUrl
```

For each OpenAPI file, create an
`Microsoft.ApiManagement/service/apis@2024-05-01` resource with:

```bicep
properties: {
  displayName: 'AI Hub Gemini'
  path: '${validatedApiPathPrefix}/gemini'
  protocols: [
    'https'
  ]
  subscriptionRequired: false
  format: 'openapi+json'
  value: loadTextContent('../openapi/gemini.json')
}
```

Use names and paths `ai-hub-gemini`, `ai-hub-anthropic`, `ai-hub-bedrock`,
`ai-hub-vertex`, and `ai-hub-mcp`. Add a sixth API named
`ai-hub-mcp-metadata` with `path: '.well-known'`; import its document with:

```bicep
value: replace(
  loadTextContent('../openapi/mcp-metadata.json'),
  '__API_PATH_PREFIX__',
  validatedApiPathPrefix
)
```

Attach all policy fragments and provider
policies as child resources using `format: 'rawxml'` and
`loadTextContent('../policies/<name>.xml')`.

- [ ] **Step 5: Add a nonsecret parameter template**

Create `main.bicepparam` with source-controlled placeholder values only:

```bicep
using './main.bicep'

param apiManagementServiceName = '<existing-apim-name>'
param apiPathPrefix = 'ai'
param gatewayBaseUrl = 'https://<gateway-host>'
param entraTenantId = '<entra-tenant-id>'
param entraAudience = 'api://<ai-hub-api-app-id>'
param requiredScope = 'ai.invoke'
param rateLimitCalls = 60
param rateLimitRenewalPeriod = 60
param maxInlinePiiCharacters = 4096
param piiLanguage = 'ko'
param languageEndpoint = 'https://<language-resource>.cognitiveservices.azure.com'
param geminiApiKeySecretIdentifier = 'https://<key-vault-name>.vault.azure.net/secrets/<gemini-api-key-secret-name>'
param anthropicApiKeySecretIdentifier = 'https://<key-vault-name>.vault.azure.net/secrets/<anthropic-api-key-secret-name>'
param bedrockAccessKeySecretIdentifier = 'https://<key-vault-name>.vault.azure.net/secrets/<bedrock-access-key-secret-name>'
param bedrockSecretKeySecretIdentifier = 'https://<key-vault-name>.vault.azure.net/secrets/<bedrock-secret-key-secret-name>'
param languageApiKeySecretIdentifier = 'https://<key-vault-name>.vault.azure.net/secrets/<language-api-key-secret-name>'
param bedrockRegion = 'us-east-1'
param vertexBrokerUrl = 'https://<private-vertex-broker-host>'
param vertexBrokerResourceAudience = 'api://<private-vertex-broker-app-id>'
param mcpAuthorizationServerOpenIdConfigurationUrl = 'https://<mcp-authorization-server>/.well-known/openid-configuration'
param mcpAuthorizationServerIssuer = 'https://<mcp-authorization-server>'
param mcpBackendUrl = 'https://<private-mcp-server-host>'
param mcpBackendResourceAudience = 'api://<private-mcp-server-app-id>'
```

Do not place a secret **value** in this template. Key Vault secret identifier
URI placeholders are required so the committed parameter template compiles;
replace them only in a secure pipeline parameter file or command-line
deployment parameters.

- [ ] **Step 6: Run Bicep and static tests**

Run:

```bash
az bicep build --file apim/third-party-model-gateway/infra/main.bicep --stdout >/dev/null
az bicep build-params --file apim/third-party-model-gateway/infra/main.bicepparam --stdout >/dev/null
python3 -m unittest apim/third-party-model-gateway/tests/test_gateway_artifacts.py -v
```

Expected: Bicep compilation succeeds once policy placeholder files are added in
Task 3; until then the build is expected to report missing `loadTextContent`
files.

- [ ] **Step 7: Commit native contracts and Bicep**

```bash
git add apim/third-party-model-gateway/infra \
  apim/third-party-model-gateway/openapi \
  apim/third-party-model-gateway/tests/test_gateway_artifacts.py
git commit -m "feat(apim): add third-party model gateway infrastructure"
```

## Task 3: Implement Common Security, Provider, and MCP Policies

**Files:**
- Create: `apim/third-party-model-gateway/policies/common-client-auth.xml`
- Create: `apim/third-party-model-gateway/policies/common-rate-limit.xml`
- Create: `apim/third-party-model-gateway/policies/common-pii-inbound.xml`
- Create: `apim/third-party-model-gateway/policies/gemini.xml`
- Create: `apim/third-party-model-gateway/policies/anthropic.xml`
- Create: `apim/third-party-model-gateway/policies/bedrock.xml`
- Create: `apim/third-party-model-gateway/policies/vertex.xml`
- Create: `apim/third-party-model-gateway/policies/mcp-resource-server.xml`
- Create: `apim/third-party-model-gateway/policies/mcp-metadata.xml`
- Modify: `apim/third-party-model-gateway/tests/test_gateway_artifacts.py`

**Interfaces:**
- Consumes: named values and backend IDs created by `infra/main.bicep`.
- Produces: APIM policy fragments and provider policies with no dynamic
  caller-selected backend URL.

- [ ] **Step 1: Add failing policy-behavior assertions**

Add the following tests:

```python
    def test_common_auth_requires_entra_issuer_audience_and_scope(self) -> None:
        source = (ROOT / "policies" / "common-client-auth.xml").read_text(encoding="utf-8")
        self.assertIn('<validate-jwt header-name="Authorization"', source)
        self.assertIn('https://login.microsoftonline.com/{{ai-hub-entra-tenant-id}}/v2.0/.well-known/openid-configuration', source)
        self.assertIn('<audience>{{ai-hub-entra-audience}}</audience>', source)
        self.assertIn('<claim name="scp" match="any" separator=" "', source)
        self.assertIn('<value>{{ai-hub-required-scope}}</value>', source)

    def test_pii_policy_fails_closed_and_does_not_redact_provider_json(self) -> None:
        source = (ROOT / "policies" / "common-pii-inbound.xml").read_text(encoding="utf-8")
        self.assertIn('response-variable-name="ai-hub-pii-response"', source)
        self.assertIn('ignore-error="true"', source)
        self.assertIn('PII inspection unavailable', source)
        self.assertIn('Sensitive input detected', source)
        self.assertNotIn('redactedText', source)

    def test_mcp_policy_uses_generic_oidc_not_entra_direct_auth(self) -> None:
        source = (ROOT / "policies" / "mcp-resource-server.xml").read_text(encoding="utf-8")
        self.assertIn('<validate-jwt header-name="Authorization"', source)
        self.assertIn('{{ai-hub-mcp-openid-config}}', source)
        self.assertIn('{{ai-hub-mcp-resource-audience}}', source)
        self.assertIn('{{ai-hub-mcp-resource-metadata-url}}', source)
        self.assertNotIn('login.microsoftonline.com', source)

    def test_mcp_metadata_policy_advertises_the_compatible_authorization_server(self) -> None:
        source = (ROOT / "policies" / "mcp-metadata.xml").read_text(encoding="utf-8")
        self.assertIn('{{ai-hub-mcp-resource-audience}}', source)
        self.assertIn('{{ai-hub-mcp-authorization-server-issuer}}', source)
        self.assertIn('authorization_servers', source)
        self.assertIn('scopes_supported', source)
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
python3 -m unittest apim/third-party-model-gateway/tests/test_gateway_artifacts.py -v
```

Expected: failures because policy files do not exist.

- [ ] **Step 3: Implement caller authentication and rate-limit fragments**

Create `common-client-auth.xml`:

```xml
<fragment>
  <validate-jwt header-name="Authorization"
                failed-validation-httpcode="401"
                failed-validation-error-message="Unauthorized"
                output-token-variable-name="ai-hub-jwt">
    <openid-config url="https://login.microsoftonline.com/{{ai-hub-entra-tenant-id}}/v2.0/.well-known/openid-configuration" />
    <audiences>
      <audience>{{ai-hub-entra-audience}}</audience>
    </audiences>
    <required-claims>
      <claim name="scp" match="any" separator=" ">
        <value>{{ai-hub-required-scope}}</value>
      </claim>
    </required-claims>
  </validate-jwt>
</fragment>
```

Create `common-rate-limit.xml`:

```xml
<fragment>
  <rate-limit-by-key calls="{{ai-hub-rate-limit-calls}}"
                     renewal-period="{{ai-hub-rate-limit-renewal-period}}"
                     counter-key="@(((Jwt)context.Variables[&quot;ai-hub-jwt&quot;]).Claims.GetValueOrDefault(&quot;oid&quot;, &quot;unknown&quot;))" />
</fragment>
```

- [ ] **Step 4: Implement fail-closed inbound PII fragment**

Create `common-pii-inbound.xml` with this processing order:

```xml
<fragment>
  <set-variable name="ai-hub-request-body"
                value="@(context.Request.Body.As&lt;string&gt;(preserveContent: true))" />
  <choose>
    <when condition="@(((string)context.Variables[&quot;ai-hub-request-body&quot;]).Length &gt; int.Parse(&quot;{{ai-hub-max-inline-pii-characters}}&quot;))">
      <return-response>
        <set-status code="413" reason="Input exceeds inline PII inspection limit" />
      </return-response>
    </when>
  </choose>
  <send-request mode="new"
                response-variable-name="ai-hub-pii-response"
                timeout="10"
                ignore-error="true">
    <set-url>{{ai-hub-language-endpoint}}/language/:analyze-text?api-version=2024-11-01</set-url>
    <set-method>POST</set-method>
    <set-header name="Content-Type" exists-action="override">
      <value>application/json</value>
    </set-header>
    <set-header name="Ocp-Apim-Subscription-Key" exists-action="override">
      <value>{{ai-hub-language-api-key}}</value>
    </set-header>
    <set-body>@{
      var requestBody = (string)context.Variables["ai-hub-request-body"];
      return new JObject(
        new JProperty("kind", "PiiEntityRecognition"),
        new JProperty("analysisInput", new JObject(
          new JProperty("documents", new JArray(new JObject(
            new JProperty("id", "request"),
            new JProperty("language", "{{ai-hub-pii-language}}"),
            new JProperty("text", requestBody)
          )))
        )),
        new JProperty("parameters", new JObject(
          new JProperty("modelVersion", "latest")
        ))
      ).ToString();
    }</set-body>
  </send-request>
</fragment>
```

Append these two `choose` conditions after `send-request`:

```xml
<choose>
  <when condition="@{
    var response = context.Variables.ContainsKey(&quot;ai-hub-pii-response&quot;)
      ? (IResponse)context.Variables[&quot;ai-hub-pii-response&quot;]
      : null;
    return response == null || response.StatusCode != 200;
  }">
    <return-response>
      <set-status code="503" reason="PII inspection unavailable" />
    </return-response>
  </when>
</choose>
<choose>
  <when condition="@{
    var response = (IResponse)context.Variables[&quot;ai-hub-pii-response&quot;];
    var result = response.Body.As&lt;JObject&gt;();
    var documents = result[&quot;results&quot;]?[&quot;documents&quot;] as JArray;
    return documents != null &amp;&amp; documents.Any(document =>
      document[&quot;entities&quot;] is JArray entities &amp;&amp; entities.Count > 0);
  }">
    <return-response>
      <set-status code="400" reason="Sensitive input detected" />
    </return-response>
  </when>
</choose>
```

The policy must not set the provider request body from `redactedText`.

- [ ] **Step 5: Implement provider routing policies**

Every native provider policy must start with:

```xml
<policies>
  <inbound>
    <base />
    <include-fragment fragment-id="ai-hub-client-auth" />
    <include-fragment fragment-id="ai-hub-rate-limit" />
    <include-fragment fragment-id="ai-hub-pii-inbound" />
```

Finish Gemini with:

```xml
    <set-header name="x-goog-api-key" exists-action="override">
      <value>{{ai-hub-gemini-api-key}}</value>
    </set-header>
    <set-backend-service backend-id="ai-hub-gemini" />
```

Finish Anthropic with:

```xml
    <set-header name="x-api-key" exists-action="override">
      <value>{{ai-hub-anthropic-api-key}}</value>
    </set-header>
    <set-header name="anthropic-version" exists-action="skip">
      <value>2023-06-01</value>
    </set-header>
    <set-backend-service backend-id="ai-hub-anthropic" />
```

Finish Vertex with:

```xml
    <set-backend-service backend-id="ai-hub-vertex-broker" />
```

Include standard `<backend>`, `<outbound>`, and `<on-error>` sections, each
with `<base />`. Do not add a public `aiplatform.googleapis.com` URL to the
policy.

For Bedrock, first add the same three common fragments and
`<set-backend-service backend-id="ai-hub-bedrock" />`, then add the
Microsoft-documented SigV4 signing algorithm. The policy must:

- source `{{ai-hub-bedrock-access-key}}` and
  `{{ai-hub-bedrock-secret-key}}`;
- set `X-Amz-Date` and `X-Amz-Content-Sha256`;
- canonicalize the HTTP method, URL path, sorted query string, `host`,
  `content-type`, and `x-amz-*` headers;
- derive a once-escaped Bedrock Runtime wire path and a canonical URI by
  escaping each wire-path segment one additional time for non-S3 SigV4;
- accept only slash-free foundation/inference-profile IDs on this path route
  and require a separately specified header/body operation or signing broker
  for ARN-style model IDs;
- derive the signing key using date, `{{ai-hub-bedrock-region}}`, service
  `bedrock`, and `aws4_request`;
- set an `AWS4-HMAC-SHA256` `Authorization` header;
- avoid request-body logging and source no literal credential.

Validate the final policy with an authorized colon-bearing model ID in staging
before production, confirming that Bedrock does not return
`SignatureDoesNotMatch`.

- [ ] **Step 6: Implement MCP resource-server and metadata policies**

Create `mcp-resource-server.xml` for the `/mcp` operation. First return the
RFC 9728 discovery challenge when no bearer token is supplied:

```xml
<choose>
  <when condition="@(!context.Request.Headers.ContainsKey(&quot;Authorization&quot;))">
    <return-response>
      <set-status code="401" reason="Unauthorized" />
      <set-header name="WWW-Authenticate" exists-action="override">
        <value>@(&quot;Bearer resource_metadata=\&quot;{{ai-hub-mcp-resource-metadata-url}}\&quot;, scope=\&quot;mcp.invoke\&quot;&quot;)</value>
      </set-header>
    </return-response>
  </when>
</choose>
```

Then validate a token from an external compatible authorization server:

```xml
<policies>
  <inbound>
    <base />
    <!-- Include the no-token choose block before validate-jwt. -->
    <validate-jwt header-name="Authorization"
                  failed-validation-httpcode="401"
                  failed-validation-error-message="Unauthorized">
      <openid-config url="{{ai-hub-mcp-openid-config}}" />
      <audiences>
        <audience>{{ai-hub-mcp-resource-audience}}</audience>
      </audiences>
      <required-claims>
        <claim name="scope" match="any" separator=" ">
          <value>mcp.invoke</value>
        </claim>
      </required-claims>
    </validate-jwt>
    <set-backend-service backend-id="ai-hub-mcp" />
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>
```

**Hardening update:** The preceding initial policy sketch is superseded by the
final artifact requirements below. Use it only to understand policy placement,
not as a copy/paste configuration:

- Validate issuer/audience with `validate-jwt`, then inspect both standard
  `scope` and Entra `scp` after validation. APIM returns comma-separated
  multiple claim values, so split on whitespace and commas before checking
  `mcp.invoke`.
- Put a `validate-jwt`-only `on-error` branch before `<base />`; return 401
  with a `WWW-Authenticate` `invalid_token` challenge containing
  `resource_metadata` and `scope="mcp.invoke"`. Return a matching
  `insufficient_scope` challenge with explicit 403 responses.
- Do not transit the client bearer token to the private backend. Overwrite
  validated issuer/subject headers, delete `Authorization`, and use
  `authentication-managed-identity` with
  `{{ai-hub-mcp-backend-resource-audience}}`. The backend must validate the
  APIM managed-identity token before it trusts these identity assertions.

Create `mcp-metadata.json`:

```json
{
  "openapi": "3.0.3",
  "info": {
    "title": "AI Hub MCP Protected Resource Metadata",
    "version": "1.0.0"
  },
  "paths": {
    "/oauth-protected-resource/__API_PATH_PREFIX__/mcp": {
      "get": {
        "operationId": "getProtectedResourceMetadata",
        "responses": {
          "200": {
            "description": "OAuth protected resource metadata",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "additionalProperties": true
                }
              }
            }
          }
        }
      }
    }
  }
}
```

Create `mcp-metadata.xml`:

```xml
<policies>
  <inbound>
    <base />
    <return-response>
      <set-status code="200" reason="OK" />
      <set-header name="Content-Type" exists-action="override">
        <value>application/json</value>
      </set-header>
      <set-body>{
        "resource": "{{ai-hub-mcp-resource-audience}}",
        "authorization_servers": ["{{ai-hub-mcp-authorization-server-issuer}}"],
        "scopes_supported": ["mcp.invoke"],
        "bearer_methods_supported": ["header"]
      }</set-body>
    </return-response>
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>
```

The Bicep template derives the MCP resource
`${gatewayBaseUrl}/{apiPathPrefix}/mcp` and RFC 9728 metadata URL
`${gatewayBaseUrl}/.well-known/oauth-protected-resource/{apiPathPrefix}/mcp`
from one canonical HTTPS-origin `gatewayBaseUrl` and the validated
`apiPathPrefix`; do not add independent URL parameters.
Do not make an Entra v2 authorization URL appear in either MCP policy.

- [ ] **Step 7: Run static tests and Bicep validation**

Run:

```bash
bash -n apim/third-party-model-gateway/scripts/validate.sh
apim/third-party-model-gateway/scripts/validate.sh
```

Expected: Bicep compiles, all XML and OpenAPI files parse, fixed-backend,
common-security, and no-plaintext-secret tests pass.

- [ ] **Step 8: Commit policies**

```bash
git add apim/third-party-model-gateway/policies \
  apim/third-party-model-gateway/infra/main.bicep \
  apim/third-party-model-gateway/tests/test_gateway_artifacts.py
git commit -m "feat(apim): secure third-party provider policies"
```

## Task 4: Document Provider Implementation, GCP WIF Prerequisites, and MCP Limitations

**Files:**
- Create: `apim/third-party-model-gateway/README.md`
- Create: `apim/third-party-model-gateway/third-party-model-integration.md`
- Create: `apim/third-party-model-gateway/scripts/configure-gcp-wif.sh`
- Modify: `aifoundry/ai-hub-llm-gateway-scaling-review.md`
- Modify: `apim/third-party-model-gateway/tests/test_gateway_artifacts.py`

**Interfaces:**
- Consumes: final artifact directory, Bicep parameter names, APIM route names,
  and policy security boundaries from Tasks 1–3.
- Produces: a directly deployable runbook, a source-backed third-party model
  guide, and a GCP setup script that contains no credentials.

- [ ] **Step 1: Add failing documentation and WIF-script tests**

Add:

```python
    def test_documentation_links_to_all_provider_policies(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for name in (
            "gemini.xml",
            "anthropic.xml",
            "bedrock.xml",
            "vertex.xml",
            "mcp-resource-server.xml",
            "mcp-metadata.xml",
        ):
            self.assertIn(name, readme)
        self.assertIn("Unified Model API", readme)
        self.assertIn("preview", readme.lower())

    def test_gcp_wif_script_uses_broker_identity_inputs_without_secrets(self) -> None:
        source = (ROOT / "scripts" / "configure-gcp-wif.sh").read_text(encoding="utf-8")
        self.assertIn("gcloud iam workload-identity-pools create", source)
        self.assertIn("gcloud iam workload-identity-pools providers create-oidc", source)
        self.assertIn("google.subject=assertion.sub", source)
        self.assertIn("roles/aiplatform.user", source)
        self.assertNotIn("private_key", source)
        self.assertNotIn("service-account-key", source)
```

- [ ] **Step 2: Run the documentation tests to verify they fail**

Run:

```bash
python3 -m unittest apim/third-party-model-gateway/tests/test_gateway_artifacts.py -v
```

Expected: failures because the README, guide, and WIF script do not exist.

- [ ] **Step 3: Write the deployment README**

Document all of the following:

- APIM system-assigned identity prerequisite and Key Vault `Secrets User`
  permission.
- Parameter-file template use and secure supply of Key Vault secret
  identifiers.
- Required fixed routes and native request schemas.
- The Bicep deployment command:

```bash
az deployment group create \
  --resource-group "<resource-group>" \
  --template-file infra/main.bicep \
  --parameters @secure.parameters.json
```

- Test command `./scripts/validate.sh`.
- Required GCP HA VPN/BGP/PSC/private DNS and AWS PrivateLink/Route 53 hybrid
  DNS prerequisites.
- Inbound-only PII policy limitation, streaming-output limitation, and
  production guardrail-service recommendation.
- Bedrock static-key limitation and recommendation to use short-lived AWS
  credentials for production.
- Direct Entra v2 versus current MCP RFC 8707 incompatibility.

- [ ] **Step 4: Write the source-backed integration guide**

Organize `third-party-model-integration.md` into:

1. Provider-native passthrough versus Unified Model API preview decision.
2. Gemini Developer API configuration and Key Vault API-key handling.
3. Anthropic Messages API configuration and `anthropic-version` header.
4. Amazon Bedrock passthrough API, APIM SigV4, PrivateLink, and hybrid DNS.
5. Vertex AI private broker, WIF rationale, HA VPN/BGP/PSC/private DNS.
6. Common Entra caller authentication and rate limiting.
7. PII policy behavior and limitations.
8. MCP compatibility and authorization-server boundary.
9. Official Microsoft, Google Cloud, AWS, Anthropic, and Azure Samples links.

Mark statements as either **Documented fact** or **Design recommendation** where
the source does not prescribe the exact architecture.

- [ ] **Step 5: Create the explicit GCP WIF prerequisite script**

Use only named positional/environment inputs and exit before side effects when
an input is absent:

```bash
#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
: "${GCP_PROJECT_NUMBER:?Set GCP_PROJECT_NUMBER}"
: "${GCP_WIF_POOL_ID:?Set GCP_WIF_POOL_ID}"
: "${GCP_WIF_PROVIDER_ID:?Set GCP_WIF_PROVIDER_ID}"
: "${ENTRA_TENANT_ID:?Set ENTRA_TENANT_ID}"
: "${ENTRA_APPLICATION_ID_URI:?Set ENTRA_APPLICATION_ID_URI}"
: "${VERTEX_BROKER_PRINCIPAL_OBJECT_ID:?Set VERTEX_BROKER_PRINCIPAL_OBJECT_ID}"

gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  cloudresourcemanager.googleapis.com \
  sts.googleapis.com \
  aiplatform.googleapis.com \
  --project "$GCP_PROJECT_ID"

gcloud iam workload-identity-pools create "$GCP_WIF_POOL_ID" \
  --project "$GCP_PROJECT_ID" \
  --location global \
  --display-name "Azure Vertex broker"

gcloud iam workload-identity-pools providers create-oidc "$GCP_WIF_PROVIDER_ID" \
  --project "$GCP_PROJECT_ID" \
  --location global \
  --workload-identity-pool "$GCP_WIF_POOL_ID" \
  --issuer-uri "https://sts.windows.net/$ENTRA_TENANT_ID" \
  --allowed-audiences "$ENTRA_APPLICATION_ID_URI" \
  --attribute-mapping "google.subject=assertion.sub"

gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member "principal://iam.googleapis.com/projects/$GCP_PROJECT_NUMBER/locations/global/workloadIdentityPools/$GCP_WIF_POOL_ID/subject/$VERTEX_BROKER_PRINCIPAL_OBJECT_ID" \
  --role roles/aiplatform.user
```

Document that the command is intended for first-time setup and must be made
idempotent or managed through the organization's GCP IaC for repeated
deployments.

- [ ] **Step 6: Link the architecture review to the reference implementation**

Add a link near the Executive Summary of
`aifoundry/ai-hub-llm-gateway-scaling-review.md`:

```markdown
실제 Bicep·APIM policy 예제는
[APIM 타사 모델 Gateway 참조 구현](../apim/third-party-model-gateway/README.md)을 참고한다.
```

- [ ] **Step 7: Run documentation, shell, Bicep, and static tests**

Run:

```bash
bash -n apim/third-party-model-gateway/scripts/configure-gcp-wif.sh
apim/third-party-model-gateway/scripts/validate.sh
git diff --check
```

Expected: no shell syntax errors, successful Bicep compilation, successful
unit tests, and no whitespace errors.

- [ ] **Step 8: Commit guide and operational assets**

```bash
git add apim/third-party-model-gateway \
  aifoundry/ai-hub-llm-gateway-scaling-review.md
git commit -m "docs(apim): add third-party model integration guide"
```

## Task 5: Verify References, Review the Complete Change, and Create the PR

**Files:**
- Verify: `apim/third-party-model-gateway/**`
- Verify: `aifoundry/ai-hub-llm-gateway-scaling-review.md`
- Verify: `docs/superpowers/specs/2026-09-04-apim-third-party-model-gateway-design.md`

**Interfaces:**
- Consumes: all committed reference artifacts.
- Produces: verified commits and an open pull request.

- [ ] **Step 1: Add a test that prevents plaintext credential literals**

Extend the validator to scan source-controlled Bicep, XML, JSON, Markdown, and
shell files. Fail if a line assigns `api_key`, `access_key`, `secret_key`, or
`private_key` to a non-placeholder string. Allow only APIM `{{named-value}}`,
environment-variable expansion, `<...>` documentation placeholders, and
`secretIdentifier` parameter names.

- [ ] **Step 2: Run the test to verify it passes on the complete artifact set**

Run:

```bash
python3 -m unittest apim/third-party-model-gateway/tests/test_gateway_artifacts.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Validate Bicep and shell syntax**

Run:

```bash
apim/third-party-model-gateway/scripts/validate.sh
bash -n apim/third-party-model-gateway/scripts/configure-gcp-wif.sh
git diff --check
```

Expected: each command exits with status `0`.

- [ ] **Step 4: Check external references**

Extract and check the official HTTP links in
`third-party-model-integration.md`:

```bash
rg -o '\]\(https://[^)]+' apim/third-party-model-gateway/third-party-model-integration.md \
  | cut -c3- \
  | sort -u \
  | while IFS= read -r url; do
      curl -L -sS -o /dev/null -w '%{http_code} %{url_effective}\n' "$url"
    done
```

Expected: all official documentation links return HTTP 2xx or 3xx.

- [ ] **Step 5: Request independent review**

Ask a reviewer to inspect the diff for:

- APIM resource/property correctness;
- secret exposure;
- invalid policy XML;
- accidental unsupported direct Vertex WIF claims;
- incorrect assertion that Entra v2 is fully MCP RFC 8707 compliant;
- missing Bedrock hybrid DNS caveat.

Address any high-confidence findings before proceeding.

- [ ] **Step 6: Commit final verification changes**

```bash
git add apim/third-party-model-gateway \
  aifoundry/ai-hub-llm-gateway-scaling-review.md
git commit -m "test(apim): verify gateway reference artifacts"
```

Only create this commit if Step 1 changes tracked files after Task 4.

- [ ] **Step 7: Create a pull request**

Use a concise PR title:

```text
docs(apim): add third-party model gateway reference
```

The PR body must include:

- provider-native APIM routes for Gemini, Anthropic, Bedrock, Vertex broker,
  and optional MCP;
- Key Vault secret handling;
- stated Bedrock, Vertex, PII, and MCP limitations;
- exact validation commands and successful results;
- no live cloud deployment performed because credentials and target resources
  were intentionally unavailable.
