# Design: APIM Third-Party Model Gateway Reference Implementation

**Date:** 2026-09-04  
**Status:** Approved for implementation under unattended execution  
**Decision:** Build a deployable reference implementation that configures an
existing Azure API Management instance. Do not provision or modify live Azure,
Google Cloud, or AWS resources during this work.

## 1. Context

The AI Hub review identifies a requirement to govern non-Foundry models through
Azure API Management (APIM). The desired operating model is:

```text
Client
  → Application Gateway / UTM
  → APIM
      → Google Gemini API
      → Private Vertex AI WIF broker → Google Vertex AI
      → Anthropic Messages API
      → Amazon Bedrock Runtime API
```

The repository contains general Azure guides and a written architecture review,
but no reusable APIM deployment configuration. The reference implementation
must turn the review into deployable infrastructure artifacts without embedding
cloud credentials or assuming access to a particular tenant.

## 2. Official-Documentation Basis

The design relies on the following documented facts.

- APIM AI Gateway supports OpenAI Chat Completions/Responses APIs, Anthropic
  Messages API in v2 tiers, Google Vertex AI API, and models hosted by
  non-Microsoft providers such as Amazon Bedrock.
- APIM Unified Model API is preview and currently translates OpenAI Chat
  Completions and Anthropic Messages formats. It is not the production default
  for provider-native Gemini, Vertex AI, and Bedrock integration.
- Microsoft documents Amazon Bedrock as an APIM passthrough API, including
  SigV4 request signing and secret named values.
- APIM named values can reference Azure Key Vault secrets, and APIM's managed
  identity can be granted access to those secrets.
- Google Workload Identity Federation can exchange an Azure workload identity
  token for short-lived Google Cloud credentials without a service-account key.
- APIM backends and `set-backend-service` policies support routing an API
  operation to a configured backend.
- The current MCP HTTP authorization specification requires OAuth resource
  metadata and RFC 8707 `resource`; Entra v2 uses `scope` and rejects a
  `resource` parameter.

## 3. Goals

1. Add a source-backed guide for integrating non-Foundry models through APIM.
2. Add Bicep that configures an **existing** APIM service with provider-native
   Gemini, Anthropic, Amazon Bedrock, and Vertex AI APIs.
3. Store provider secrets only as Key Vault-backed APIM named values.
4. Use a private Vertex AI broker that performs Google Workload Identity
   Federation with an Azure managed identity; no Google service-account JSON
   key is deployed in APIM or source control.
5. Apply a common caller authentication, request-rate limit, request-size
   guard, and fail-closed inbound PII inspection policy.
6. Provide a generic HTTP MCP resource-server template that requires an
   RFC 8707-compatible authorization server, instead of incorrectly presenting
   Entra v2 as directly MCP-compliant.
7. Add static validation that runs without cloud credentials.

## 4. Non-Goals

- No live deployment to an Azure, Google Cloud, or AWS subscription/account.
- No creation of an Azure VPN Gateway, GCP HA VPN, Private Service Connect,
  AWS VPC endpoint, or Route 53 Resolver endpoint. The guide instead makes
  their required network dependencies explicit.
- No provider schema normalization. Each model remains reachable through its
  native API contract.
- No APIM Unified Model API deployment because it is preview.
- No outbound PII redaction for streaming completions. The inline policy blocks
  sensitive inbound requests; a dedicated guardrail service is required for
  reliable streaming/output PII enforcement.
- No implementation of an MCP authorization server. The reference policy is a
  resource-server template for a separately deployed compatible authorization
  server.

## 5. Alternatives Considered

### Option A: APIM Unified Model API

Use one OpenAI-compatible endpoint and configure provider aliases.

- **Advantages:** A stable client endpoint, built-in format translation for
  supported protocols, centralized routing.
- **Disadvantages:** The feature is preview. Its documented format translation
  scope is OpenAI Chat Completions and Anthropic Messages, not generic native
  Gemini, Vertex AI, and Bedrock APIs.

This option is documented as a future/controlled-evaluation option only.

### Option B: Provider-Native Passthrough APIs (Selected)

Create one APIM API per provider and preserve that provider's schema.

- **Advantages:** Uses documented, stable APIM primitives; avoids unsafe
  format conversion; supports provider-specific authentication and streaming;
  allows a common policy baseline.
- **Disadvantages:** Client code chooses a provider-specific route and request
  format.

### Option C: Custom Normalization Broker

Build a bespoke service that translates all providers into one internal
contract before APIM.

- **Advantages:** Full control over format translation, fallback, and
  cross-provider behavior.
- **Disadvantages:** Adds a stateful service, broad provider test surface, and
  ongoing API-version maintenance. It duplicates functionality that APIM or a
  future GA unified API can partially provide.

## 6. Selected Architecture

```text
                         ┌───────────────────────────┐
Client ────── JWT ──────►│ Azure API Management       │
                         │ - Entra caller validation  │
                         │ - Request rate limiting    │
                         │ - Inbound PII blocking     │
                         │ - Provider routing/auth    │
                         └──────────┬───────┬────────┘
                                    │       │
              ┌─────────────────────┘       └──────────────────────┐
              ▼                                                      ▼
    Gemini / Anthropic API-key paths                    Vertex WIF / Bedrock SigV4
    Key Vault named values                              Broker token / Key Vault secrets
              │                                                      │
              ▼                                                      ▼
    Gemini Developer API / Anthropic                  Google Vertex AI / AWS Bedrock
```

### 6.1 Provider Routing

| APIM API path | Backend | Backend authentication | Contract |
|---|---|---|---|
| `/ai/gemini` | Gemini Developer API | `x-goog-api-key` from Key Vault named value | Gemini native |
| `/ai/anthropic` | Anthropic API | `x-api-key` from Key Vault named value | Anthropic Messages |
| `/ai/bedrock` | Amazon Bedrock Runtime | AWS SigV4; AWS keys from Key Vault named values | Bedrock native |
| `/ai/vertex` | Private Vertex AI WIF broker | Broker managed identity → Google STS WIF token exchange | Vertex AI native |

Every provider API uses a configured APIM backend (`set-backend-service`) rather
than a dynamic URL supplied by the client. This prevents an APIM policy editor
from inadvertently creating an open proxy.

### 6.2 Common Inbound Policy

The policy order is:

1. Validate the caller's Entra JWT issuer, audience, lifetime, and required
   scope.
2. Apply a caller-keyed request-rate limit.
3. Preserve the request body, enforce a conservative inline inspection size
   limit, and call Azure Language PII detection.
4. Fail closed if the PII service returns a non-success result or detects an
   entity.
5. Add provider-specific credentials and choose the fixed backend.

The PII policy intentionally blocks rather than mutates provider-native JSON.
This avoids corrupting a request body while still preventing detected PII from
leaving the gateway. It does not replace output filtering or streaming
inspection by a guardrail service.

### 6.3 Provider Credentials

- Gemini and Anthropic API keys are Key Vault secret references.
- Bedrock uses the Microsoft-documented APIM SigV4 policy pattern. The
  deployment accepts Key Vault references to a constrained IAM user's access
  key and secret. The guide labels this an APIM-compatible deployment pattern,
  not the preferred long-term identity model.
- Vertex uses a private broker's managed identity to request an Entra token for
  a registered Application ID URI, then exchanges it through Google Security
  Token Service. A Google Workload Identity Pool must trust that Azure identity
  and grant least-privilege Vertex AI permissions.

APIM-only exchange is intentionally excluded from the production path. APIM
policy primitives can acquire a managed-identity token, send an HTTP request,
and extract an STS response, but neither Microsoft nor Google documents their
complete composition as an APIM-to-Vertex implementation. It also requires
custom token caching and complicated failure handling in APIM policy XML.

For production Bedrock, replace long-lived IAM-user keys with a dedicated
SigV4 broker or workload federation that obtains short-lived AWS credentials.

### 6.4 MCP Boundary

The reference contains an optional generic MCP APIM resource-server policy:

- `/.well-known/oauth-protected-resource` returns Protected Resource Metadata.
- APIM validates a token issued by a compatible authorization server.
- APIM maps scope/role to an MCP API operation.
- The MCP backend must still enforce object-level authorization.

The reference explicitly does **not** use Entra v2 as the MCP authorization
server when full 2026-07-28 MCP compliance is required. An authorization
compatibility layer must bridge Entra sign-in and RFC 8707 resource-aware token
issuance. A scope-only Entra configuration is documented as a private,
non-full-standard compatibility profile.

## 7. Planned Artifacts

```text
apim/
  third-party-model-gateway/
    README.md
    third-party-model-integration.md
    infra/
      main.bicep
      main.bicepparam
    policies/
      gemini.xml
      anthropic.xml
      bedrock.xml
      vertex.xml
      mcp-resource-server.xml
    openapi/
      gemini.json
      anthropic.json
      bedrock.json
      vertex.json
      mcp.json
    scripts/
      configure-gcp-wif.sh
      validate.sh
    tests/
      test_gateway_artifacts.py
```

The existing AI Hub review will link to this implementation.

## 8. Configuration Interface

The Bicep deployment targets an existing APIM service and accepts:

- APIM service name and API path prefix
- Entra tenant ID, resource audience, and required scope
- Key Vault secret URIs for Gemini, Anthropic, Bedrock access key, Bedrock
  secret key, and Azure Language key; plus an Azure Language endpoint URL
- GCP project number, workload identity pool/provider IDs, Vertex region, and
  private Vertex broker URL
- AWS Bedrock region
- backend endpoint URLs only where a private/custom endpoint is required

Secrets are never default parameter values, source-controlled JSON values, or
workflow environment variables.

## 9. Validation Strategy

The PR must provide evidence independent of live cloud access:

1. Run `az bicep build` against the root Bicep file.
2. Run the Python standard-library validator to parse every policy and OpenAPI
   document, verify Bicep references, detect plaintext secret patterns, and
   check the required security controls.
3. Run `git diff --check`.
4. Verify every official documentation URL in the new guide returns HTTP 2xx
   or 3xx.

Live acceptance tests are documented separately because they require an Azure
subscription, Key Vault secrets, Google WIF configuration, and an AWS account.

## 10. Success Criteria

- Bicep compiles without diagnostics.
- Static tests pass without network credentials.
- Every provider route references a fixed APIM backend.
- No access keys, API keys, client secrets, or service-account JSON keys are
  committed.
- The Vertex route only targets a private broker; it does not attempt an
  undocumented APIM-only WIF token-exchange implementation.
- The guide clearly identifies private-network prerequisites for Vertex AI and
  Bedrock.
- The guide distinguishes the preview Unified Model API from the selected
  provider-native implementation.
- The MCP section does not claim direct Entra v2 compliance with the current
  MCP RFC 8707 requirement.
