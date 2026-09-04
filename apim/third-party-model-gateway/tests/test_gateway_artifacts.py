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

    def test_provider_policies_delete_caller_authorization_before_backend_routing(self) -> None:
        # Gemini and Anthropic authenticate to their providers with named-value
        # API keys, and the private Vertex broker uses its own workload
        # identity. None of them may forward the caller's Entra bearer token
        # to the upstream provider, so each policy must explicitly delete the
        # inbound Authorization header after the common client-auth/rate-limit/
        # PII fragments run (they still need to see it) but before the
        # provider-specific credential is applied and the backend is selected.
        for name in ("gemini.xml", "anthropic.xml", "vertex.xml"):
            source = (ROOT / "policies" / name).read_text(encoding="utf-8")

            pii_fragment_pos = source.find('fragment-id="ai-hub-pii-inbound"')
            self.assertNotEqual(-1, pii_fragment_pos, name)

            delete_auth_match = re.search(
                r'<set-header\s+name="Authorization"\s+exists-action="delete"\s*/>',
                source,
            )
            self.assertIsNotNone(
                delete_auth_match,
                f"{name} must delete the inbound Authorization header",
            )
            delete_auth_pos = delete_auth_match.start()

            backend_select_match = re.search(r"<set-backend-service\b", source)
            self.assertIsNotNone(backend_select_match, name)
            backend_select_pos = backend_select_match.start()

            self.assertLess(
                pii_fragment_pos, delete_auth_pos,
                f"{name}: Authorization must be deleted after common fragments",
            )
            self.assertLess(
                delete_auth_pos, backend_select_pos,
                f"{name}: Authorization must be deleted before backend selection",
            )

    def test_provider_policies_delete_authorization_before_backend_credentials(self) -> None:
        # Gemini/Anthropic set their own outbound provider credential headers
        # (x-goog-api-key / x-api-key) from named values; deleting the caller's
        # Authorization header must happen before those are applied so that a
        # stray Authorization header never reaches the backend even if a
        # provider credential header is skipped/overridden differently later.
        credential_headers = {
            "gemini.xml": "x-goog-api-key",
            "anthropic.xml": "x-api-key",
        }
        for name, header in credential_headers.items():
            source = (ROOT / "policies" / name).read_text(encoding="utf-8")
            delete_auth_match = re.search(
                r'<set-header\s+name="Authorization"\s+exists-action="delete"\s*/>',
                source,
            )
            self.assertIsNotNone(delete_auth_match, name)
            credential_match = re.search(
                rf'<set-header\s+name="{re.escape(header)}"',
                source,
            )
            self.assertIsNotNone(credential_match, name)
            self.assertLess(
                delete_auth_match.start(), credential_match.start(),
                f"{name}: Authorization must be deleted before setting {header}",
            )

    def test_mcp_and_bedrock_policies_do_not_delete_caller_authorization(self) -> None:
        # mcp-resource-server.xml IS the protected resource that validates the
        # caller's own Authorization header, and bedrock.xml overrides
        # Authorization with a computed SigV4 value rather than deleting it.
        # Neither should gain the caller-isolation delete-header line.
        for name in ("mcp-resource-server.xml", "bedrock.xml"):
            source = (ROOT / "policies" / name).read_text(encoding="utf-8")
            self.assertNotRegex(
                source,
                r'<set-header\s+name="Authorization"\s+exists-action="delete"\s*/>',
                name,
            )

    def test_pii_policy_treats_200_response_errors_or_missing_result_as_unavailable(self) -> None:
        # The Azure AI Language PII Analyze Text 200 response contains
        # "kind", "results.documents" and "results.errors". A 200 response
        # whose "errors" array is missing/non-empty, whose "kind" isn't the
        # expected PII recognition result kind, or that has no matching
        # "request" document with an "entities" array is NOT a clean/available
        # result -- it must fail closed (503), not fall through as if PII
        # inspection succeeded and found nothing.
        source = (ROOT / "policies" / "common-pii-inbound.xml").read_text(encoding="utf-8")

        unavailable_match = re.search(
            r'set-status code="503" reason="PII inspection unavailable"',
            source,
        )
        self.assertIsNotNone(unavailable_match, "must retain the 503 unavailable response")

        entities_match = re.search(
            r'set-status code="400" reason="Sensitive input detected"',
            source,
        )
        self.assertIsNotNone(entities_match, "must retain a distinct 400 PII-detected response")

        # There must be two *distinct* <choose> conditions guarding these two
        # responses (not one condition reused for both), and the 503 guard
        # must inspect results/errors/kind/document-id, not only StatusCode.
        choose_blocks = re.findall(r"<choose>.*?</choose>", source, re.DOTALL)
        self.assertGreaterEqual(len(choose_blocks), 2, "expected separate 503 and 400 choose blocks")

        unavailable_block = next(
            (block for block in choose_blocks if "PII inspection unavailable" in block),
            None,
        )
        self.assertIsNotNone(unavailable_block)

        entities_block = next(
            (block for block in choose_blocks if "Sensitive input detected" in block),
            None,
        )
        self.assertIsNotNone(entities_block)
        self.assertNotEqual(
            unavailable_block, entities_block,
            "503-unavailable and 400-detected must be separate choose conditions",
        )

        # The 503 guard must fail closed on: non-200/missing response (already
        # covered), unexpected/missing "kind", missing/non-empty
        # "results"/"errors", a missing "request" document, or that document
        # lacking an "entities" array -- i.e. it must reference all of these,
        # not just StatusCode.
        import html

        decoded_unavailable_block = html.unescape(unavailable_block)
        self.assertIn("StatusCode", decoded_unavailable_block)
        self.assertIn('"kind"', decoded_unavailable_block)
        self.assertIn('"errors"', decoded_unavailable_block)
        self.assertIn('"documents"', decoded_unavailable_block)
        self.assertIn('"entities"', decoded_unavailable_block)
        self.assertIn('"request"', decoded_unavailable_block)

    def test_mcp_metadata_policy_advertises_the_compatible_authorization_server(self) -> None:
        source = (ROOT / "policies" / "mcp-metadata.xml").read_text(encoding="utf-8")
        self.assertIn('{{ai-hub-mcp-resource-audience}}', source)
        self.assertIn('{{ai-hub-mcp-authorization-server-issuer}}', source)
        self.assertIn('authorization_servers', source)
        self.assertIn('scopes_supported', source)


if __name__ == "__main__":
    unittest.main()
