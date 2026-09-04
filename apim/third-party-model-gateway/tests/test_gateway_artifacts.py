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


if __name__ == "__main__":
    unittest.main()
