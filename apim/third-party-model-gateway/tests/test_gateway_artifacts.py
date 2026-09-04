from __future__ import annotations

import json
import re
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
    def _resource_block(self, source: str, resource_symbol: str) -> str:
        pattern = re.compile(
            rf"resource {re.escape(resource_symbol)} [^\n]+ = \{{.*?^\}}",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(source)
        self.assertIsNotNone(match, resource_symbol)
        return match.group(0)

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

    def test_bicep_loads_every_policy_and_openapi_asset(self) -> None:
        source = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
        for name in OPENAPI_FILES:
            self.assertIn(f"loadTextContent('../openapi/{name}')", source)
        for name in POLICY_FILES:
            self.assertIn(f"loadTextContent('../policies/{name}')", source)

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
        self.assertIn("secretIdentifier: bedrockSecretKeySecretIdentifier", source)
        self.assertIn("secretIdentifier: languageApiKeySecretIdentifier", source)
        self.assertNotIn("aiplatform.googleapis.com", source)

    def test_bicep_explicitly_orders_policy_fragments_and_api_policies(self) -> None:
        source = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")

        expected_dependencies = {
            "clientAuthPolicyFragment": (
                "entraTenantIdNamedValue",
                "entraAudienceNamedValue",
                "requiredScopeNamedValue",
            ),
            "rateLimitPolicyFragment": (
                "rateLimitCallsNamedValue",
                "rateLimitRenewalPeriodNamedValue",
            ),
            "piiInboundPolicyFragment": (
                "maxInlinePiiCharactersNamedValue",
                "piiLanguageNamedValue",
                "languageEndpointNamedValue",
                "languageApiKeyNamedValue",
            ),
            "geminiApiPolicy": (
                "clientAuthPolicyFragment",
                "rateLimitPolicyFragment",
                "piiInboundPolicyFragment",
                "geminiBackend",
                "geminiApiKeyNamedValue",
            ),
            "anthropicApiPolicy": (
                "clientAuthPolicyFragment",
                "rateLimitPolicyFragment",
                "piiInboundPolicyFragment",
                "anthropicBackend",
                "anthropicApiKeyNamedValue",
            ),
            "bedrockApiPolicy": (
                "clientAuthPolicyFragment",
                "rateLimitPolicyFragment",
                "piiInboundPolicyFragment",
                "bedrockBackend",
                "bedrockAccessKeyNamedValue",
                "bedrockSecretKeyNamedValue",
                "bedrockRegionNamedValue",
            ),
            "vertexApiPolicy": (
                "clientAuthPolicyFragment",
                "rateLimitPolicyFragment",
                "piiInboundPolicyFragment",
                "vertexBrokerBackend",
            ),
            "mcpApiPolicy": (
                "mcpBackend",
                "mcpOpenIdConfigNamedValue",
                "mcpAuthorizationServerIssuerNamedValue",
                "mcpResourceAudienceNamedValue",
                "mcpResourceMetadataUrlNamedValue",
            ),
            "mcpMetadataApiPolicy": (
                "mcpOpenIdConfigNamedValue",
                "mcpAuthorizationServerIssuerNamedValue",
                "mcpResourceAudienceNamedValue",
                "mcpResourceMetadataUrlNamedValue",
            ),
        }

        for resource_symbol, dependencies in expected_dependencies.items():
            block = self._resource_block(source, resource_symbol)
            self.assertIn("dependsOn: [", block, resource_symbol)
            for dependency in dependencies:
                self.assertIn(f"    {dependency}", block, f"{resource_symbol} -> {dependency}")

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

    def test_bedrock_policy_signs_the_bedrock_runtime_model_path(self) -> None:
        # The public APIM operation path is "/ai/bedrock/model/{modelId}/converse",
        # but the Bedrock Runtime backend only ever sees "/model/{modelId}/converse".
        # SigV4 requires the canonical request path to match what the backend
        # receives, so the policy must derive/escape that path from the
        # "modelId" matched (template) parameter rather than signing
        # context.Request.Url.Path (the public, prefixed path), which would
        # produce SignatureDoesNotMatch on every request.
        source = (ROOT / "policies" / "bedrock.xml").read_text(encoding="utf-8")

        self.assertIn('context.Request.MatchedParameters["modelId"]', source)
        self.assertIn(
            'System.Uri.EscapeDataString(', source,
        )
        self.assertRegex(
            source,
            r'(?i)"/model/"\s*\+\s*[^\n;]*modelid[^\n;]*\+\s*"/converse"',
        )
        self.assertNotIn("var path = context.Request.Url.Path;", source)

    def test_bedrock_policy_canonicalizes_every_query_parameter_value(self) -> None:
        # AWS SigV4 canonical query string construction requires every value of a
        # repeated query parameter to be individually URI-encoded and included as
        # its own "key=value" pair, with all encoded pairs then ordinal-sorted.
        # Reading only kvp.Value.FirstOrDefault() silently drops repeated values
        # from the signed request, producing a canonical request that no longer
        # matches what the backend actually receives.
        source = (ROOT / "policies" / "bedrock.xml").read_text(encoding="utf-8")

        self.assertNotIn("kvp.Value.FirstOrDefault()", source)
        self.assertRegex(
            source,
            r"foreach\s*\(\s*var\s+\w+\s+in\s+kvp\.Value\s*\)",
        )

    def test_bedrock_policy_preserves_content_type_header_case(self) -> None:
        # SigV4 canonical headers require lowercase header *names* but the
        # header *values* must be preserved as sent (only trimmed), not
        # case-folded. Lower-casing the Content-Type value before signing
        # produces a canonical request that does not match the actual
        # forwarded header, causing SignatureDoesNotMatch whenever the
        # backend sends a mixed-case Content-Type (e.g. "application/JSON").
        source = (ROOT / "policies" / "bedrock.xml").read_text(encoding="utf-8")

        self.assertNotIn(
            'headers.GetValueOrDefault("Content-Type", "").ToLowerInvariant()',
            source,
        )

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


if __name__ == "__main__":
    unittest.main()
