from __future__ import annotations

import html
import json
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent.parent

# A deliverable outside this project's own tree that documents/links this
# gateway and must therefore be held to the same no-plaintext-credential
# standard. Referenced by relative path from REPO_ROOT so the scan stays
# scoped to a single, explicitly named file rather than growing to cover
# unrelated repository content.
LINKED_DELIVERABLE_RELATIVE_PATH = "aifoundry/ai-hub-llm-gateway-scaling-review.md"
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

# Extensions scanned for plaintext credential literals. Only source-controlled
# (git-tracked) files with these suffixes are scanned; ignored/session
# artifacts (e.g. `.superpowers/`, `*.secrets.json`) are never considered
# because the file list comes from `git ls-files`, not filesystem globbing.
CREDENTIAL_SCAN_EXTENSIONS = (".bicep", ".bicepparam", ".xml", ".json", ".md", ".sh")

# APIM header names (case-insensitive) that carry a third-party provider
# credential when set from a policy `<value>`. Any literal (non-named-value,
# non-policy-expression) content found there is a plaintext credential leak.
CREDENTIAL_HEADER_NAMES = frozenset(
    {"x-goog-api-key", "x-api-key", "ocp-apim-subscription-key"}
)

# The credential-shaped identifier token (api key, access key, access key ID,
# secret key, private key) in snake_case, kebab-case, camelCase, or
# SCREAMING_SNAKE_CASE, optionally prefixed by a provider name joined with
# `_`/`-` (e.g. `GEMINI_API_KEY`, `AWS_ACCESS_KEY_ID`). Deliberately requires
# a real `key`/`Key` token immediately after `api`/`access`/`secret`/`private`
# so it does not match `secretIdentifier` parameter names (no "key" substring
# follows "secret").
_CREDENTIAL_KEY_TOKEN = r"(?:api|access|secret|private)[_-]?key(?:[_-]?id)?"

# Matches an assignment of a credential-shaped identifier to a literal value,
# quoted or unquoted (shell `KEY=value`, YAML `KEY: value`, JSON
# `"KEY": "value"`, Bicep `key: 'value'`, ...).
#
# The leading `(?<![A-Za-z0-9])` allows the key token to be preceded by `_`
# or `-` (so prefixed variants like `GEMINI_API_KEY` or `x-goog-api-key`
# still match) while refusing to start mid-identifier when immediately
# preceded by another letter/digit (so `geminiApiKeySecretIdentifier` is not
# treated as starting a fresh match at `ApiKey`).
#
# No trailing word-boundary assertion is needed after the key token: the
# very next thing required is an (optional) closing quote followed by `:` or
# `=`. That structural requirement alone is what excludes header-name labels
# such as `name="x-goog-api-key"` (the next attribute is `exists-action=...`,
# not immediately `:`/`=` after the closing quote) and `secretIdentifier`
# parameter declarations/references such as `geminiApiKeySecretIdentifier`
# (more identifier letters follow "Key" directly, not `:`/`=`), without
# needing a separate lookahead.
#
# The value itself is either a quoted string (group 1 = quote char, group 2 =
# contents) or an unquoted run of non-whitespace characters (group 3), which
# covers shell/YAML/JSON-style plaintext assignments the quote-only pattern
# used to miss.
CREDENTIAL_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9]){_CREDENTIAL_KEY_TOKEN}[\"']?\s*[:=]\s*"
    r"(?:([\"'])((?:(?!\1).)*)\1|(\S+))"
)

# AWS access-key IDs are not necessarily assigned to a conventional credential
# variable name, so scan their documented prefixes directly as a second layer.
AWS_ACCESS_KEY_ID_RE = re.compile(
    r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])"
)

SECRET_IDENTIFIER_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])[A-Za-z_][A-Za-z0-9_]*SecretIdentifier\s*=\s*"
    r"(?:([\"'])((?:(?!\1).)*)\1|(\S+))"
)

_KEY_VAULT_HOST_RE = re.compile(
    r"(?i)^(?:[a-z0-9-]+|<[a-z0-9-]+>)\.vault\."
    r"(?:azure\.net|usgovcloudapi\.net|azure\.cn)$"
)

_APIM_CONTEXT_VARIABLE_EXPRESSION_RE = re.compile(
    r"""^@\(\s*context\.Variables(?:
        \.GetValueOrDefault(?:<[^>]+>)?\(\s*(?:'|")[A-Za-z_][A-Za-z0-9_.-]*(?:'|")\s*\)
        |\[\s*(?:'|")[A-Za-z_][A-Za-z0-9_.-]*(?:'|")\s*\]
    )\s*\)$""",
    re.VERBOSE,
)


def _is_placeholder_credential_value(value: str) -> bool:
    """Returns True when a matched literal is an allowed placeholder shape.

    Allowed: empty strings, APIM `{{named-value}}` references, a complete
    APIM `context.Variables` lookup expression, `<...>` documentation
    placeholders, and shell/`.env`-style environment-variable expansion
    (`$VAR`, `${VAR}`, `%VAR%`).
    """
    stripped = value.strip()
    if stripped == "":
        return True
    if stripped.startswith("{{") and stripped.endswith("}}"):
        return True
    if stripped.startswith("<") and stripped.endswith(">"):
        return True
    if _APIM_CONTEXT_VARIABLE_EXPRESSION_RE.fullmatch(stripped):
        return True
    if re.fullmatch(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", stripped):
        return True
    if re.fullmatch(r"%[A-Za-z_][A-Za-z0-9_]*%", stripped):
        return True
    return False


def _strip_unquoted_trailing_punctuation(value: str) -> str:
    """Strips trailing statement punctuation from an unquoted match (e.g.
    the `,`/`;`/`)` that ends a shell/YAML statement) so it isn't mistaken
    for part of the credential literal itself. Deliberately excludes `}`/`]`
    so an APIM named-value placeholder (`{{...}}`) is left intact.
    """
    return value.rstrip(",;)")


def _is_key_vault_secret_identifier(value: str) -> bool:
    """Returns True for a Key Vault secret URI, including template segments."""
    parsed = urlparse(value.strip())
    path_parts = parsed.path.split("/")
    return (
        parsed.scheme == "https"
        and _KEY_VAULT_HOST_RE.fullmatch(parsed.netloc) is not None
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and len(path_parts) in {3, 4}
        and path_parts[0] == ""
        and path_parts[1] == "secrets"
        and all(path_parts[index] for index in range(2, len(path_parts)))
    )


def _iter_assignment_violations(label: str, text: str) -> list[str]:
    """Finds plaintext credential-shaped assignments, line by line.

    `label` is used only for violation reporting (typically a path).
    """
    violations: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in CREDENTIAL_ASSIGNMENT_RE.finditer(line):
            if match.group(2) is not None:
                literal_value = match.group(2)
            else:
                literal_value = _strip_unquoted_trailing_punctuation(match.group(3))
            if not _is_placeholder_credential_value(literal_value):
                violations.append(f"{label}:{line_number}: {line.strip()}")
    return violations


def _iter_aws_access_key_id_violations(label: str, text: str) -> list[str]:
    """Finds AWS access-key IDs regardless of the variable that contains them."""
    violations: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if AWS_ACCESS_KEY_ID_RE.search(line):
            violations.append(f"{label}:{line_number}: {line.strip()}")
    return violations


def _iter_bicep_secret_identifier_violations(
    label: str, suffix: str, text: str
) -> list[str]:
    """Ensures committed Bicep parameter templates use Key Vault URI values."""
    if suffix != ".bicepparam":
        return []

    violations: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in SECRET_IDENTIFIER_ASSIGNMENT_RE.finditer(line):
            if match.group(2) is not None:
                value = match.group(2)
            else:
                value = _strip_unquoted_trailing_punctuation(match.group(3))
            if not _is_key_vault_secret_identifier(value):
                violations.append(
                    f"{label}:{line_number}: *SecretIdentifier must be a Key Vault "
                    f"secret URI: {line.strip()}"
                )
    return violations


def _iter_xml_header_violations(label: str, suffix: str, text: str) -> list[str]:
    """Parses APIM policy XML and flags plaintext content set on a known
    credential-bearing header (`x-goog-api-key`, `x-api-key`,
    `Ocp-Apim-Subscription-Key`) via `<set-header>...<value>...</value>`.

    APIM named values (`{{...}}`) and strict `context.Variables` lookup
    expressions are permitted; arbitrary inline policy expressions and other
    literal `<value>` content are plaintext credential leaks. Malformed XML
    raises (error-loud) rather than being silently skipped. `label` is used
    only for violation reporting.
    """
    if suffix != ".xml":
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(
            f"{label}: could not parse XML while scanning for credential "
            f"headers: {exc}"
        ) from exc

    violations: list[str] = []
    for header in root.iter("set-header"):
        name = header.get("name", "")
        if name.lower() not in CREDENTIAL_HEADER_NAMES:
            continue
        value_element = header.find("value")
        if value_element is None or value_element.text is None:
            continue
        value = value_element.text
        if _is_placeholder_credential_value(value):
            continue
        needle = f"<value>{value}</value>"
        offset = text.find(needle)
        line_number = text.count("\n", 0, offset) + 1 if offset != -1 else 0
        violations.append(
            f'{label}:{line_number}: <set-header name="{name}">'
            f"<value>{value}</value></set-header>"
        )
    return violations


def _scan_paths_for_credential_violations(
    paths: Iterable[Path], *, display_root: Path | None = None
) -> list[str]:
    """Scans the given files for plaintext credential literals.

    Deliberately does not catch/skip per-file errors: an unreadable file or
    (for `.xml` files) invalid XML in scope is a scan failure, not a silent
    pass, so `path.read_text` / `ET.fromstring` errors propagate.

    When `display_root` is given, violation messages report paths relative
    to it (falling back to the path as-is when it is not a descendant, e.g.
    a fixture living outside the repository).
    """
    violations: list[str] = []
    for path in paths:
        if display_root is not None:
            try:
                label = str(path.relative_to(display_root))
            except ValueError:
                label = str(path)
        else:
            label = str(path)
        text = path.read_text(encoding="utf-8")
        violations.extend(_iter_assignment_violations(label, text))
        violations.extend(_iter_aws_access_key_id_violations(label, text))
        violations.extend(
            _iter_bicep_secret_identifier_violations(label, path.suffix, text)
        )
        violations.extend(_iter_xml_header_violations(label, path.suffix, text))
    return violations


def _git_tracked_scan_targets(root: Path, extensions: tuple[str, ...]) -> list[Path]:
    """Lists git-tracked files under `root` with one of `extensions`.

    Running `git ls-files` with `cwd=root` (no pathspec) scopes the listing
    to files reachable from `root`, so unrelated repository paths are never
    included, and files declared in `.gitignore` (untracked) are never
    considered since the listing only ever contains tracked paths.
    """
    listing = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        root / relative_path
        for relative_path in listing.stdout.splitlines()
        if Path(relative_path).suffix in extensions
    ]


def _require_tracked_file(repo_root: Path, relative_path: str) -> Path:
    """Resolves `relative_path` from `repo_root`, raising loudly if it is not
    a git-tracked file, instead of silently omitting it from the scan.
    """
    listing = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative_path],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if listing.returncode != 0 or not listing.stdout.strip():
        raise AssertionError(
            f"expected {relative_path!r} to be a git-tracked file under "
            f"{repo_root}, but `git ls-files --error-unmatch` failed "
            f"(rc={listing.returncode}): {listing.stderr.strip()}"
        )
    return repo_root / relative_path


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

    def test_mcp_public_endpoint_matches_the_resource_audience_and_metadata_contract(
        self,
    ) -> None:
        # RFC 9728 requires the protected-resource metadata to be derived
        # deterministically from the actual protected resource URL. The MCP
        # API is mounted in main.bicep at '${validatedApiPathPrefix}/mcp', so the
        # OpenAPI document backing it must expose its operation at the API's
        # own root ('/'), not a nested '/mcp' path -- otherwise the public
        # endpoint becomes '<prefix>/mcp/mcp', which no longer matches the
        # configured resource audience or the metadata URL below.
        bicep_source = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
        mcp_api_block = self._resource_block(bicep_source, "mcpApi")
        self.assertIn("path: '${validatedApiPathPrefix}/mcp'", mcp_api_block)
        self.assertIn("loadTextContent('../openapi/mcp.json')", mcp_api_block)

        with (ROOT / "openapi" / "mcp.json").open(encoding="utf-8") as source:
            mcp_document = json.load(source)
        self.assertIn("/", mcp_document["paths"], "mcp.json must expose its operation at the API root")
        self.assertIn("post", mcp_document["paths"]["/"])
        self.assertNotIn(
            "/mcp",
            mcp_document["paths"],
            "mcp.json must not nest a '/mcp' operation under an API already mounted at '.../mcp'",
        )

        # The protected-resource metadata API is mounted at '.well-known' and
        # its OpenAPI contract substitutes the live apiPathPrefix into
        # '/oauth-protected-resource/__API_PATH_PREFIX__/mcp', so the two
        # combine to the RFC 9728 well-known path for the *same* resource
        # mounted above ('${validatedApiPathPrefix}/mcp'), with no extra '/mcp' segment.
        metadata_api_block = self._resource_block(bicep_source, "mcpMetadataApi")
        self.assertIn("path: '.well-known'", metadata_api_block)
        self.assertIn("validatedApiPathPrefix", metadata_api_block)

        with (ROOT / "openapi" / "mcp-metadata.json").open(encoding="utf-8") as source:
            metadata_document = json.load(source)
        metadata_paths = list(metadata_document["paths"])
        self.assertEqual(len(metadata_paths), 1)
        self.assertEqual(
            metadata_paths[0],
            "/oauth-protected-resource/__API_PATH_PREFIX__/mcp",
        )

    def test_mcp_resource_urls_are_derived_from_gateway_base_url(self) -> None:
        source = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
        self.assertIn("param gatewayBaseUrl string", source)
        self.assertNotIn("param mcpResourceAudience string", source)
        self.assertNotIn("param mcpResourceMetadataUrl string", source)
        self.assertIn("var validatedGatewayBaseUrl =", source)
        self.assertIn(
            "var gatewayBaseUrlParts = split(normalizedGatewayBaseUrl, '/')",
            source,
        )
        self.assertNotIn("var gatewayBaseUrlAuthority = replace(", source)
        self.assertIn("length(gatewayBaseUrlParts) == 3", source)
        self.assertIn("var gatewayBaseUrlScheme =", source)
        self.assertIn("var gatewayBaseUrlSeparator =", source)
        self.assertIn("var gatewayBaseUrlAuthority =", source)
        self.assertIn("gatewayBaseUrlScheme == 'https:'", source)
        self.assertIn("empty(gatewayBaseUrlSeparator)", source)
        self.assertIn("length(gatewayBaseUrlAuthority) > 0", source)
        self.assertIn(
            "fail('gatewayBaseUrl must be a canonical HTTPS origin without a path, query, fragment, or trailing slash.')",
            source,
        )
        self.assertIn("var validatedApiPathPrefix =", source)
        self.assertIn(
            "fail('apiPathPrefix must be nonempty and must not start or end with a slash.')",
            source,
        )
        self.assertIn(
            "var mcpResourceAudience = '${validatedGatewayBaseUrl}/${validatedApiPathPrefix}/mcp'",
            source,
        )
        self.assertIn(
            "var mcpResourceMetadataUrl = '${validatedGatewayBaseUrl}/.well-known/oauth-protected-resource/${validatedApiPathPrefix}/mcp'",
            source,
        )

        audience_named_value = self._resource_block(
            source,
            "mcpResourceAudienceNamedValue",
        )
        metadata_named_value = self._resource_block(
            source,
            "mcpResourceMetadataUrlNamedValue",
        )
        self.assertIn("value: mcpResourceAudience", audience_named_value)
        self.assertIn("value: mcpResourceMetadataUrl", metadata_named_value)

        parameter_template = (
            ROOT / "infra" / "main.bicepparam"
        ).read_text(encoding="utf-8")
        self.assertIn("param gatewayBaseUrl = 'https://<gateway-host>'", parameter_template)
        self.assertNotIn("param mcpResourceAudience =", parameter_template)
        self.assertNotIn("param mcpResourceMetadataUrl =", parameter_template)

    def test_mcp_docs_use_one_gateway_base_url_input(self) -> None:
        documents = (
            ROOT / "README.md",
            ROOT / "third-party-model-integration.md",
            ROOT.parents[1]
            / "docs"
            / "superpowers"
            / "specs"
            / "2026-09-04-apim-third-party-model-gateway-design.md",
            ROOT.parents[1]
            / "docs"
            / "superpowers"
            / "plans"
            / "2026-09-04-apim-third-party-model-gateway.md",
        )
        for path in documents:
            source = path.read_text(encoding="utf-8")
            self.assertIn("gatewayBaseUrl", source, path.name)
            self.assertNotIn("mcpResourceAudience", source, path.name)
            self.assertNotIn("mcpResourceMetadataUrl", source, path.name)

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

    def test_vertex_broker_backend_uses_the_validated_private_url(self) -> None:
        source = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
        self.assertIn(
            "var forbiddenVertexPublicHost = 'aiplatform.googleapis.com'",
            source,
        )
        self.assertIn(
            "var validatedVertexBrokerUrl = !contains(toLower(vertexBrokerUrl), forbiddenVertexPublicHost)",
            source,
        )
        self.assertIn(
            "fail('vertexBrokerUrl must target the private broker, not the public Vertex AI host.')",
            source,
        )
        backend = self._resource_block(source, "vertexBrokerBackend")
        self.assertIn("url: validatedVertexBrokerUrl", backend)
        self.assertNotIn("url: vertexBrokerUrl", backend)

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
                "vertexBrokerResourceAudienceNamedValue",
            ),
            "mcpApiPolicy": (
                "mcpBackend",
                "mcpOpenIdConfigNamedValue",
                "mcpAuthorizationServerIssuerNamedValue",
                "mcpResourceAudienceNamedValue",
                "mcpResourceMetadataUrlNamedValue",
                "mcpBackendResourceAudienceNamedValue",
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

    def test_common_rate_limit_uses_validated_oid_claim_with_stable_fallback(self) -> None:
        root = ET.parse(ROOT / "policies" / "common-rate-limit.xml").getroot()
        rate_limit = root.find("rate-limit-by-key")
        self.assertIsNotNone(rate_limit)
        counter_key = rate_limit.attrib["counter-key"]
        self.assertIn('((Jwt)context.Variables["ai-hub-jwt"])', counter_key)
        self.assertIn('.Claims.GetValueOrDefault("oid", "unknown")', counter_key)
        self.assertNotIn("sub", counter_key)

    def test_bedrock_policy_signs_the_bedrock_runtime_model_path(self) -> None:
        # The public APIM operation path is "/ai/bedrock/model/{modelId}/converse",
        # but the Bedrock Runtime backend only ever sees "/model/{modelId}/converse".
        # The forwarded path must URI-encode the model ID once, while non-S3
        # SigV4 applies one additional URI-encoding pass to that forwarded
        # path for CanonicalURI. Both paths must be derived from the matched
        # "modelId" rather than the public APIM request path.
        source = (ROOT / "policies" / "bedrock.xml").read_text(encoding="utf-8")

        self.assertIn('name="ai-hub-bedrock-wire-path"', source)
        self.assertIn('name="ai-hub-bedrock-canonical-path"', source)
        self.assertIn('context.Request.MatchedParameters[&quot;modelId&quot;]', source)
        self.assertNotIn("System.Uri.UnescapeDataString", source)
        self.assertRegex(
            source,
            r'(?i)&quot;/model/&quot;\s*\+\s*[^\n;]*modelid[^\n;]*\+\s*&quot;/converse&quot;',
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

    def test_bedrock_policy_derives_canonical_path_from_forwarded_wire_path(self) -> None:
        # AWS non-S3 SigV4 signs one URI-encoding pass over the already
        # encoded wire path. For example, a colon is %3A on the wire and
        # %253A in CanonicalURI. Deriving canonicalPath from wirePath prevents
        # the two representations from drifting while preserving that
        # intentional one-level difference.
        source = (ROOT / "policies" / "bedrock.xml").read_text(encoding="utf-8")

        model_id = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        wire_model_id = quote(model_id, safe="-_.~")
        canonical_model_id = quote(wire_model_id, safe="-_.~")
        self.assertEqual("anthropic.claude-3-5-sonnet-20241022-v2%3A0", wire_model_id)
        self.assertEqual(
            "anthropic.claude-3-5-sonnet-20241022-v2%253A0",
            canonical_model_id,
        )

        slash_model_id = "arn:aws:bedrock:us-east-1:123456789012:inference-profile/model:0"
        self.assertIn("%2F", quote(slash_model_id, safe="-_.~"))
        self.assertIn("%252F", quote(quote(slash_model_id, safe="-_.~"), safe="-_.~"))

        wire_path_match = re.search(
            r'<set-variable name="ai-hub-bedrock-wire-path" value="(?P<body>@\{.*?)" />',
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(wire_path_match)

        canonical_path_match = re.search(
            r'<set-variable name="ai-hub-bedrock-canonical-path" value="(?P<body>@\{.*?)" />',
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(canonical_path_match)
        canonical_path_body = canonical_path_match.group("body")
        self.assertIn(
            'context.Variables[&quot;ai-hub-bedrock-wire-path&quot;]',
            canonical_path_body,
        )
        self.assertIn("System.Uri.EscapeDataString(segment)", canonical_path_body)

        rewrite_match = re.search(
            r'<rewrite-uri\s+template="(?P<body>@[\{\(].*?)"\s+copy-unmatched-params="false"\s*/>',
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(
            rewrite_match,
            'bedrock.xml must declare a whole-expression <rewrite-uri> with copy-unmatched-params="false"',
        )
        rewrite_body = rewrite_match.group("body")

        variable_keys = set(re.findall(r'context\.Variables\[&quot;([\w-]+)&quot;\]', rewrite_body))
        self.assertEqual(
            {
                "ai-hub-bedrock-wire-path",
                "ai-hub-bedrock-canonical-query",
            },
            variable_keys,
        )

        auth_header_match = re.search(
            r'<set-header name="Authorization" exists-action="override">\s*<value>(?P<body>.*?)</value>\s*</set-header>',
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(auth_header_match, "bedrock.xml must still set the Authorization header")
        auth_body = auth_header_match.group("body")

        self.assertIn(
            'context.Variables["ai-hub-bedrock-canonical-path"]',
            auth_body,
        )
        self.assertIn(
            'context.Variables["ai-hub-bedrock-canonical-query"]',
            auth_body,
        )
        self.assertNotIn(
            'context.Variables["ai-hub-bedrock-wire-path"]',
            auth_body,
        )

    def test_bedrock_route_rejects_slash_model_ids_and_documents_the_alternative(self) -> None:
        source = (ROOT / "policies" / "bedrock.xml").read_text(encoding="utf-8")
        self.assertIn("System.Text.RegularExpressions.Regex.IsMatch", source)
        self.assertIn('&quot;^[A-Za-z0-9._:-]{1,256}$&quot;', source)
        self.assertIn('set-status code="400" reason="Unsupported Bedrock model ID"', source)

        with (ROOT / "openapi" / "bedrock.json").open(encoding="utf-8") as handle:
            bedrock_openapi = json.load(handle)
        model_parameter = bedrock_openapi["paths"]["/model/{modelId}/converse"]["post"][
            "parameters"
        ][0]
        self.assertIn("description", model_parameter)
        self.assertIn("ARN", model_parameter["description"])
        self.assertIn("/", model_parameter["description"])

        for path in (
            ROOT / "README.md",
            ROOT / "third-party-model-integration.md",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertIn("ARN", source, path.name)
            self.assertIn("modelId", source, path.name)

    def test_bedrock_policy_orders_canonical_query_by_encoded_key_then_value(self) -> None:
        # AWS SigV4 canonical query construction sorts by encoded name, then by
        # encoded value (for repeated names) -- both compared independently.
        # Pre-joining "key=value" and then sorting that combined string is not
        # equivalent (e.g. it collapses the delimiter into the comparison and
        # cannot correctly place multiple encoded values for the same key), so
        # the ordering must be expressed as ThenBy(...) over discrete
        # key/value selectors.
        source = (ROOT / "policies" / "bedrock.xml").read_text(encoding="utf-8")

        self.assertNotRegex(
            source,
            r'encodedParams\.Add\(encodedKey \+ "=" \+ encodedValue\)',
            "query pairs must not be pre-joined into a single string before sorting",
        )
        # "=>" appears inside an XML *attribute* value here (set-variable has
        # no <value> child element), so the lambda arrow must be written as
        # the "&gt;" entity, not a literal ">".
        self.assertRegex(
            source,
            r'\.OrderBy\(\s*\w+\s*=&gt;\s*\w+\.Key\b[\s\S]*?\)\s*\n?\s*\.ThenBy\(\s*\w+\s*=&gt;\s*\w+\.Value\b',
        )

    def test_bedrock_policy_normalizes_and_combines_repeated_amz_header_values(self) -> None:
        # SigV4 canonical header values must have internal whitespace runs
        # collapsed to a single space (leading/trailing trimmed), and every
        # value of a repeated header must be combined into one comma-joined
        # canonical value -- reading only the first value silently drops
        # signed data that the backend still receives.
        source = (ROOT / "policies" / "bedrock.xml").read_text(encoding="utf-8")

        self.assertRegex(
            source,
            r'Regex\.Replace\([^,]+,\s*@"\\s\+"\s*,\s*" "\)',
            "signed header values must collapse internal whitespace via Regex.Replace(..., @\"\\s+\", \" \")",
        )
        self.assertNotIn(
            'header.Value.FirstOrDefault()',
            source,
            "every repeated x-amz-* header value must be combined, not just the first",
        )
        self.assertRegex(
            source,
            r'string\.Join\(\s*","\s*,\s*\w+\s*\)',
            "repeated x-amz-* header values must be comma-joined into one canonical value",
        )

    def test_bedrock_policy_derives_the_payload_hash_once_from_raw_body_bytes(self) -> None:
        # X-Amz-Content-Sha256 and the Authorization signature must hash the
        # exact same raw request bytes, computed once from
        # context.Request.Body.As<byte[]>(preserveContent: true) -- not by
        # re-encoding a string variable, which can diverge from the raw bytes
        # actually forwarded to the backend (e.g. via encoding normalization).
        source = (ROOT / "policies" / "bedrock.xml").read_text(encoding="utf-8")

        body_as_bytes_matches = re.findall(
            r'context\.Request\.Body\.As&lt;byte\[\]&gt;\(preserveContent:\s*true\)',
            source,
        )
        self.assertEqual(
            1, len(body_as_bytes_matches),
            "the raw request body bytes must be read exactly once and reused for both the header and the signature",
        )

        hash_variable_match = re.search(
            r'<set-variable name="([\w-]+)" value="@\{[^"]*?context\.Request\.Body\.As&lt;byte\[\]&gt;',
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(
            hash_variable_match,
            "the payload hash must be computed into its own context variable before signing",
        )
        hash_variable_name = hash_variable_match.group(1)

        content_sha_header_match = re.search(
            r'<set-header name="X-Amz-Content-Sha256" exists-action="override">\s*<value>(?P<body>.*?)</value>\s*</set-header>',
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(content_sha_header_match)
        self.assertIn(
            f'context.Variables["{hash_variable_name}"]',
            content_sha_header_match.group("body"),
            "X-Amz-Content-Sha256 must reuse the shared payload-hash variable",
        )

        auth_header_match = re.search(
            r'<set-header name="Authorization" exists-action="override">\s*<value>(?P<body>.*?)</value>\s*</set-header>',
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(auth_header_match)
        auth_body = auth_header_match.group("body")
        self.assertIn(
            f'context.Variables["{hash_variable_name}"]',
            auth_body,
            "the Authorization signature must reuse the shared payload-hash variable",
        )
        self.assertNotIn(
            'System.Text.Encoding.UTF8.GetBytes(body)',
            auth_body,
            "the signature must not re-encode a string body instead of hashing the raw bytes",
        )

    def test_bedrock_policy_uses_documented_sigv4_service_and_algorithm(self) -> None:
        root = ET.parse(ROOT / "policies" / "bedrock.xml").getroot()
        auth_header = root.find("./inbound/set-header[@name='Authorization']/value")
        self.assertIsNotNone(auth_header)
        auth_body = auth_header.text or ""
        self.assertIn('var service = "bedrock";', auth_body)
        self.assertIn('var credentialScope = dateStamp + "/" + region + "/" + service + "/aws4_request";', auth_body)
        self.assertIn('var stringToSign = "AWS4-HMAC-SHA256\\n" + amzDate + "\\n" + credentialScope + "\\n" + hashedCanonicalRequest;', auth_body)
        self.assertIn('kService = h3.ComputeHash(System.Text.Encoding.UTF8.GetBytes(service));', auth_body)
        self.assertIn('return "AWS4-HMAC-SHA256 Credential=" + accessKey + "/" + credentialScope', auth_body)
        self.assertNotIn('bedrock-runtime', auth_body)

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

    def test_mcp_policy_accepts_standard_scope_or_entra_scp_after_jwt_validation(
        self,
    ) -> None:
        root = ET.parse(ROOT / "policies" / "mcp-resource-server.xml").getroot()
        inbound_children = list(root.find("inbound"))
        validate_jwt = inbound_children[2]
        self.assertEqual("validate-jwt", validate_jwt.tag)
        self.assertEqual(
            "ai-hub-mcp-jwt",
            validate_jwt.attrib.get("output-token-variable-name"),
        )
        self.assertIsNone(
            validate_jwt.find("required-claims"),
            "scope authorization must accept either standard scope or Entra scp after JWT validation",
        )
        self.assertGreaterEqual(
            len(inbound_children),
            4,
            "MCP policy must evaluate scope/scp authorization after validate-jwt",
        )

        authorization_choose = inbound_children[3]
        self.assertEqual("choose", authorization_choose.tag)
        authorization_when = authorization_choose.find("when")
        self.assertIsNotNone(authorization_when)
        condition = html.unescape(authorization_when.attrib.get("condition", ""))
        self.assertIn('context.Variables["ai-hub-mcp-jwt"]', condition)
        self.assertIn('GetValueOrDefault("scope", "")', condition)
        self.assertIn('GetValueOrDefault("scp", "")', condition)
        self.assertIn("Regex.Split", condition)
        self.assertIn('@"[\\s,]+"', condition)
        self.assertIn('"mcp.invoke"', condition)

        status = authorization_when.find("return-response/set-status")
        self.assertIsNotNone(status)
        self.assertEqual("403", status.attrib["code"])

    def test_mcp_docs_explain_scope_and_entra_scp_compatibility(self) -> None:
        expected_claim_wording = "`scope` 또는 Entra `scp` claim"
        guide = (ROOT / "third-party-model-integration.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(expected_claim_wording, guide)
        self.assertIn(expected_claim_wording, readme)
        for source in (guide, readme):
            self.assertIn("WWW-Authenticate", source)
            self.assertIn("invalid_token", source)
            self.assertIn("insufficient_scope", source)

    def test_mcp_docs_define_the_managed_identity_backend_trust_boundary(self) -> None:
        for path in (
            ROOT / "README.md",
            ROOT / "third-party-model-integration.md",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertIn("system-assigned managed identity", source, path.name)
            self.assertIn("x-ai-hub-mcp-caller-subject", source, path.name)
            self.assertIn("전달하지 않는다", source, path.name)

    def test_mcp_resource_server_emits_metadata_challenge_before_jwt_validation(self) -> None:
        root = ET.parse(ROOT / "policies" / "mcp-resource-server.xml").getroot()
        inbound_children = list(root.find("inbound"))
        child_tags = [child.tag for child in inbound_children]
        self.assertEqual("base", child_tags[0])
        self.assertEqual("choose", child_tags[1])
        self.assertEqual("validate-jwt", child_tags[2])

        choose = inbound_children[1]
        no_token_when = next(
            (
                when
                for when in choose.findall("when")
                if html.unescape(when.attrib.get("condition", ""))
                == '@(!context.Request.Headers.ContainsKey("Authorization"))'
            ),
            None,
        )
        self.assertIsNotNone(no_token_when)
        return_response = no_token_when.find("return-response")
        self.assertIsNotNone(return_response)
        status = return_response.find("set-status")
        self.assertEqual("401", status.attrib["code"])
        self.assertEqual("Unauthorized", status.attrib["reason"])
        auth_header = return_response.find('set-header[@name="WWW-Authenticate"]/value')
        self.assertIsNotNone(auth_header)
        challenge = html.unescape(auth_header.text or "")
        self.assertIn("ai-hub-mcp-resource-metadata-url", challenge)
        self.assertIn("mcp.invoke", challenge)
        self.assertTrue(challenge.startswith('@("'))

    def test_mcp_policy_challenges_invalid_tokens_and_insufficient_scope(self) -> None:
        root = ET.parse(ROOT / "policies" / "mcp-resource-server.xml").getroot()

        scope_when = list(root.find("inbound"))[3].find("when")
        self.assertIsNotNone(scope_when)
        forbidden_response = scope_when.find("return-response")
        self.assertIsNotNone(forbidden_response)
        forbidden_header = forbidden_response.find(
            'set-header[@name="WWW-Authenticate"]/value'
        )
        self.assertIsNotNone(forbidden_header)
        insufficient_scope_challenge = html.unescape(forbidden_header.text or "")
        self.assertIn('error=\\"insufficient_scope\\"', insufficient_scope_challenge)
        self.assertIn("ai-hub-mcp-resource-metadata-url", insufficient_scope_challenge)
        self.assertIn('scope=\\"mcp.invoke\\"', insufficient_scope_challenge)

        on_error = root.find("on-error")
        self.assertIsNotNone(on_error)
        on_error_children = list(on_error)
        self.assertEqual("choose", on_error_children[0].tag)
        self.assertEqual("base", on_error_children[1].tag)
        jwt_error_when = on_error_children[0].find("when")
        self.assertIsNotNone(jwt_error_when)
        self.assertEqual(
            '@(context.LastError.Source == "validate-jwt")',
            html.unescape(jwt_error_when.attrib.get("condition", "")),
        )
        invalid_token_response = jwt_error_when.find("return-response")
        self.assertIsNotNone(invalid_token_response)
        invalid_token_status = invalid_token_response.find("set-status")
        self.assertIsNotNone(invalid_token_status)
        self.assertEqual("401", invalid_token_status.attrib["code"])
        invalid_token_header = invalid_token_response.find(
            'set-header[@name="WWW-Authenticate"]/value'
        )
        self.assertIsNotNone(invalid_token_header)
        invalid_token_challenge = html.unescape(invalid_token_header.text or "")
        self.assertIn('error=\\"invalid_token\\"', invalid_token_challenge)
        self.assertIn("ai-hub-mcp-resource-metadata-url", invalid_token_challenge)
        self.assertIn('scope=\\"mcp.invoke\\"', invalid_token_challenge)

    def test_mcp_policy_replaces_resource_token_with_managed_identity_backend_auth(
        self,
    ) -> None:
        root = ET.parse(ROOT / "policies" / "mcp-resource-server.xml").getroot()
        inbound = root.find("inbound")
        self.assertIsNotNone(inbound)

        caller_subject = inbound.find('set-variable[@name="ai-hub-mcp-caller-subject"]')
        self.assertIsNotNone(caller_subject)
        self.assertEqual(
            '@(((Jwt)context.Variables["ai-hub-mcp-jwt"]).Subject ?? "")',
            caller_subject.attrib["value"],
        )
        caller_issuer = inbound.find('set-variable[@name="ai-hub-mcp-caller-issuer"]')
        self.assertIsNotNone(caller_issuer)
        self.assertEqual(
            '@(((Jwt)context.Variables["ai-hub-mcp-jwt"]).Issuer ?? "")',
            caller_issuer.attrib["value"],
        )

        delete_authorization = inbound.find(
            'set-header[@name="Authorization"][@exists-action="delete"]'
        )
        self.assertIsNotNone(delete_authorization)
        subject_header = inbound.find(
            'set-header[@name="x-ai-hub-mcp-caller-subject"][@exists-action="override"]'
        )
        issuer_header = inbound.find(
            'set-header[@name="x-ai-hub-mcp-caller-issuer"][@exists-action="override"]'
        )
        self.assertIsNotNone(subject_header)
        self.assertIsNotNone(issuer_header)
        self.assertIn(
            'ai-hub-mcp-caller-subject',
            subject_header.findtext("value", default=""),
        )
        self.assertIn(
            'ai-hub-mcp-caller-issuer',
            issuer_header.findtext("value", default=""),
        )

        managed_identity = inbound.find("authentication-managed-identity")
        self.assertIsNotNone(managed_identity)
        self.assertEqual(
            "{{ai-hub-mcp-backend-resource-audience}}",
            managed_identity.attrib["resource"],
        )
        children = list(inbound)
        self.assertLess(children.index(delete_authorization), children.index(managed_identity))
        self.assertLess(children.index(subject_header), children.index(managed_identity))
        self.assertLess(children.index(issuer_header), children.index(managed_identity))
        self.assertLess(
            children.index(managed_identity),
            children.index(inbound.find('set-backend-service[@backend-id="ai-hub-mcp"]')),
        )

        bicep_source = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
        self.assertIn("param mcpBackendResourceAudience string", bicep_source)
        named_value = self._resource_block(
            bicep_source,
            "mcpBackendResourceAudienceNamedValue",
        )
        self.assertIn("value: mcpBackendResourceAudience", named_value)

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

    def test_vertex_policy_authenticates_the_broker_and_forwards_validated_caller_identity(
        self,
    ) -> None:
        source = (ROOT / "policies" / "vertex.xml").read_text(encoding="utf-8")
        root = ET.fromstring(source)
        inbound = root.find("inbound")
        self.assertIsNotNone(inbound)

        caller_oid = inbound.find('set-variable[@name="ai-hub-vertex-caller-oid"]')
        self.assertIsNotNone(caller_oid)
        self.assertEqual(
            '@(((Jwt)context.Variables["ai-hub-jwt"]).Claims.GetValueOrDefault("oid", ""))',
            caller_oid.attrib["value"],
        )

        missing_oid_response = next(
            (
                when
                for when in inbound.findall("choose/when")
                if when.find('return-response/set-status[@code="403"]') is not None
            ),
            None,
        )
        self.assertIsNotNone(
            missing_oid_response,
            "Vertex must reject a valid caller token that lacks an immutable oid claim",
        )

        caller_oid_header = inbound.find('set-header[@name="x-ai-hub-caller-oid"]')
        self.assertIsNotNone(caller_oid_header)
        self.assertEqual("override", caller_oid_header.attrib["exists-action"])
        self.assertIn("ai-hub-vertex-caller-oid", caller_oid_header.findtext("value", ""))

        broker_identity = inbound.find("authentication-managed-identity")
        self.assertIsNotNone(broker_identity)
        self.assertEqual(
            "{{ai-hub-vertex-broker-resource-audience}}",
            broker_identity.attrib["resource"],
        )

        delete_auth_pos = source.index(
            '<set-header name="Authorization" exists-action="delete" />'
        )
        broker_identity_pos = source.index("<authentication-managed-identity")
        backend_pos = source.index("<set-backend-service")
        self.assertLess(delete_auth_pos, broker_identity_pos)
        self.assertLess(broker_identity_pos, backend_pos)

    def test_vertex_broker_identity_configuration_is_wired_and_documented(self) -> None:
        bicep = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
        params = (ROOT / "infra" / "main.bicepparam").read_text(encoding="utf-8")
        self.assertIn("param vertexBrokerResourceAudience string", bicep)
        self.assertIn("name: 'ai-hub-vertex-broker-resource-audience'", bicep)
        self.assertIn("value: vertexBrokerResourceAudience", bicep)
        self.assertIn(
            "param vertexBrokerResourceAudience = 'api://<private-vertex-broker-app-id>'",
            params,
        )

        for path in (
            ROOT / "README.md",
            ROOT / "third-party-model-integration.md",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertIn("vertexBrokerResourceAudience", source, path.name)
            self.assertIn("authentication-managed-identity", source, path.name)
            self.assertIn("x-ai-hub-caller-oid", source, path.name)

    def test_parameter_template_assigns_all_secure_key_vault_identifiers(self) -> None:
        params = (ROOT / "infra" / "main.bicepparam").read_text(encoding="utf-8")
        expected_identifiers = {
            "geminiApiKeySecretIdentifier": "gemini-api-key-secret-name",
            "anthropicApiKeySecretIdentifier": "anthropic-api-key-secret-name",
            "bedrockAccessKeySecretIdentifier": "bedrock-access-key-secret-name",
            "bedrockSecretKeySecretIdentifier": "bedrock-secret-key-secret-name",
            "languageApiKeySecretIdentifier": "language-api-key-secret-name",
        }
        for parameter, secret_name in expected_identifiers.items():
            self.assertIn(
                f"param {parameter} = "
                f"'https://<key-vault-name>.vault.azure.net/secrets/<{secret_name}>'",
                params,
            )

        validate_script = (ROOT / "scripts" / "validate.sh").read_text(encoding="utf-8")
        self.assertIn(
            "az bicep build-params --file infra/main.bicepparam --stdout >/dev/null",
            validate_script,
        )

    def test_validation_script_changes_to_its_own_root_before_running_python(self) -> None:
        source = (ROOT / "scripts" / "validate.sh").read_text(encoding="utf-8")
        self.assertIn('cd "$root"', source)
        self.assertIn(
            "az bicep build --file infra/main.bicep --stdout >/dev/null",
            source,
        )
        self.assertIn(
            "az bicep build-params --file infra/main.bicepparam --stdout >/dev/null",
            source,
        )
        self.assertIn(
            "python3 -m unittest tests/test_gateway_artifacts.py -v",
            source,
        )
        self.assertNotIn('"$root/tests/test_gateway_artifacts.py"', source)

    def test_bedrock_policy_overrides_caller_authorization_without_delete(self) -> None:
        # Bedrock replaces the caller bearer with its computed SigV4 header;
        # MCP separately validates, deletes, and replaces it with a
        # managed-identity token (covered by its dedicated policy test).
        source = (ROOT / "policies" / "bedrock.xml").read_text(encoding="utf-8")
        self.assertNotRegex(
            source,
            r'<set-header\s+name="Authorization"\s+exists-action="delete"\s*/>',
        )
        self.assertIn(
            '<set-header name="Authorization" exists-action="override">',
            source,
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
        self.assertEqual(
            2,
            source.count("response.Body.As&lt;JObject&gt;(preserveContent: true)"),
            "both PII response inspections must preserve the bounded response body",
        )
        self.assertNotIn(
            "response.Body.As&lt;JObject&gt;()",
            source,
            "no PII response inspection may consume the body stream",
        )

    def test_mcp_metadata_policy_advertises_the_compatible_authorization_server(self) -> None:
        source = (ROOT / "policies" / "mcp-metadata.xml").read_text(encoding="utf-8")
        self.assertIn('{{ai-hub-mcp-resource-audience}}', source)
        self.assertIn('{{ai-hub-mcp-authorization-server-issuer}}', source)
        self.assertIn('authorization_servers', source)
        self.assertIn('scopes_supported', source)

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

    def test_readme_correctly_scopes_common_fragment_bypass_to_mcp_only(self) -> None:
        # policies/bedrock.xml DOES include the three common fragments (see
        # test_provider_policies_include_common_security_fragments); only the
        # MCP policies skip them in favor of their own generic OIDC handling.
        # The README must not claim Bedrock bypasses the common fragment.
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        common_fragment_section = readme[readme.index("공통 policy fragment") :]
        common_fragment_section = common_fragment_section[
            : common_fragment_section.index("## 3")
            if "## 3" in common_fragment_section
            else len(common_fragment_section)
        ]
        self.assertNotRegex(
            common_fragment_section,
            r"MCP\s*(?:와|과|,)\s*Bedrock\s*(?:정책은|는)?\s*이\s*\n?\s*fragment\s*대신",
            "README must not say Bedrock bypasses the common fragment",
        )
        self.assertIn("MCP", common_fragment_section)
        self.assertIn("일반 OIDC", common_fragment_section)

    def test_route53_inbound_endpoint_url_used_not_outbound(self) -> None:
        inbound_url = (
            "https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/"
            "resolver-forwarding-inbound-queries.html"
        )
        outbound_url = (
            "https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/"
            "resolver-forwarding-outbound-queries.html"
        )
        for path in (
            ROOT / "README.md",
            ROOT / "third-party-model-integration.md",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertIn(inbound_url, source, f"{path.name} must cite the inbound endpoint doc")
            self.assertNotIn(
                outbound_url, source, f"{path.name} must not cite the outbound endpoint doc"
            )

    def test_guide_cites_gemini_generatecontent_rest_reference(self) -> None:
        guide = (ROOT / "third-party-model-integration.md").read_text(encoding="utf-8")
        gemini_url = "https://ai.google.dev/api/generate-content#v1beta.models.generateContent"
        self.assertIn(gemini_url, guide, "guide body must cite the official Gemini REST reference")
        source_list = guide[guide.index("## 9. 공식 참고 자료") :]
        self.assertIn(
            gemini_url,
            source_list,
            "formal source list must include the Gemini generateContent reference",
        )
        self.assertRegex(source_list, r"###\s*Google AI\b|###\s*Gemini\b")

    def test_guide_cites_distinct_gemini_api_key_header_reference(self) -> None:
        # The generateContent reference documents endpoint behavior but does
        # not document the x-goog-api-key header itself; a distinct, official
        # Google citation must support that specific claim, both inline
        # (next to where the header is introduced) and in the formal source
        # list.
        guide = (ROOT / "third-party-model-integration.md").read_text(encoding="utf-8")
        generatecontent_url = (
            "https://ai.google.dev/api/generate-content#v1beta.models.generateContent"
        )
        api_key_url = "https://ai.google.dev/gemini-api/docs/api-key"

        self.assertNotEqual(generatecontent_url, api_key_url)
        self.assertIn(
            generatecontent_url, guide, "guide must retain the generateContent reference"
        )
        self.assertIn(
            api_key_url, guide, "guide must cite the distinct Gemini API-key documentation"
        )

        # The API-key citation must sit near the first x-goog-api-key mention
        # in the body, so it visibly supports that specific header claim
        # rather than only appearing disconnected in the reference list.
        header_claim_index = guide.index("x-goog-api-key")
        nearby_window = guide[
            max(0, header_claim_index - 500) : header_claim_index + 500
        ]
        self.assertIn(
            api_key_url,
            nearby_window,
            "API-key citation must appear near the x-goog-api-key header claim",
        )

        source_list = guide[guide.index("## 9. 공식 참고 자료") :]
        self.assertIn(
            generatecontent_url,
            source_list,
            "formal source list must retain the generateContent reference",
        )
        self.assertIn(
            api_key_url,
            source_list,
            "formal source list must include the distinct API-key reference",
        )

    def test_guide_cites_mcp_authorization_and_rfc8707_alongside_rfc9728(self) -> None:
        guide = (ROOT / "third-party-model-integration.md").read_text(encoding="utf-8")
        mcp_auth_url = "https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization"
        rfc8707_url = "https://www.rfc-editor.org/rfc/rfc8707.html"
        rfc9728_url = "https://www.rfc-editor.org/rfc/rfc9728.html"

        section8 = guide[
            guide.index("## 8. MCP 호환성과 authorization-server 경계") : guide.index(
                "## 9. 공식 참고 자료"
            )
        ]
        self.assertIn(mcp_auth_url, section8, "§8 must cite the MCP authorization specification")
        self.assertIn(rfc8707_url, section8, "§8 must cite RFC 8707 for the resource parameter")
        self.assertIn(rfc9728_url, section8, "§8 must retain RFC 9728 for protected-resource metadata")

        source_list = guide[guide.index("## 9. 공식 참고 자료") :]
        for url in (mcp_auth_url, rfc8707_url, rfc9728_url):
            self.assertIn(url, source_list, f"formal source list must include {url}")

    def test_guide_identifies_vertex_policy_as_bicep_referenced_policy_file(self) -> None:
        guide = (ROOT / "third-party-model-integration.md").read_text(encoding="utf-8")
        self.assertNotIn("`infra/main.bicep`의 `vertex.xml`", guide)
        self.assertRegex(
            guide,
            r"`policies/vertex\.xml`.{0,40}(?:정책은|은|는)",
        )
        self.assertIn("`infra/main.bicep`", guide)

    def test_gcp_wif_script_uses_broker_identity_inputs_without_secrets(self) -> None:
        source = (ROOT / "scripts" / "configure-gcp-wif.sh").read_text(encoding="utf-8")
        self.assertIn("gcloud iam workload-identity-pools create", source)
        self.assertIn("gcloud iam workload-identity-pools providers create-oidc", source)
        self.assertIn("google.subject=assertion.sub", source)
        self.assertIn("roles/aiplatform.user", source)
        self.assertNotIn("private_key", source)
        self.assertNotIn("service-account-key", source)

    def test_gcp_wif_script_enables_resource_manager_before_project_iam_binding(self) -> None:
        source = (ROOT / "scripts" / "configure-gcp-wif.sh").read_text(encoding="utf-8")
        self.assertIn("cloudresourcemanager.googleapis.com", source)
        self.assertIn("gcloud projects add-iam-policy-binding", source)
        enable_pos = source.index("cloudresourcemanager.googleapis.com")
        binding_pos = source.index("gcloud projects add-iam-policy-binding")
        self.assertLess(enable_pos, binding_pos)

    def test_no_plaintext_credential_literals_in_source_controlled_gateway_files(
        self,
    ) -> None:
        # Scope the scan to git-tracked files only, so ignored/session
        # artifacts (`.superpowers/`, `*.secrets.json`, `.env`, ...) declared
        # in .gitignore are never scanned, and only real committed reference
        # material is checked. `git ls-files` run with cwd=ROOT is already
        # scoped to this project's own tree (unrelated repository paths are
        # never listed), plus the linked deliverable that documents this
        # gateway from outside the project tree is added explicitly by its
        # exact path (not a broad glob), and must itself be git-tracked or
        # the scan fails loudly rather than silently omitting it.
        tracked_files = _git_tracked_scan_targets(ROOT, CREDENTIAL_SCAN_EXTENSIONS)
        tracked_files.append(
            _require_tracked_file(REPO_ROOT, LINKED_DELIVERABLE_RELATIVE_PATH)
        )
        self.assertTrue(tracked_files, "expected at least one file to scan")

        violations = _scan_paths_for_credential_violations(
            tracked_files, display_root=REPO_ROOT
        )

        self.assertEqual(
            [],
            violations,
            "found plaintext credential literal(s); use a Key Vault-backed "
            "{{named-value}}, environment-variable expansion, or a "
            "documented <...> placeholder instead:\n" + "\n".join(violations),
        )

    def test_credential_scan_targets_stay_within_gateway_project_and_linked_deliverable(
        self,
    ) -> None:
        # Guards the scan's scope itself: every scanned path must live
        # either inside the gateway project directory or be exactly the one
        # linked deliverable -- never some other, unrelated repository path.
        tracked_files = _git_tracked_scan_targets(ROOT, CREDENTIAL_SCAN_EXTENSIONS)
        for path in tracked_files:
            self.assertTrue(path.is_relative_to(ROOT), path)

        linked = _require_tracked_file(REPO_ROOT, LINKED_DELIVERABLE_RELATIVE_PATH)
        self.assertEqual(
            REPO_ROOT / LINKED_DELIVERABLE_RELATIVE_PATH,
            linked,
        )
        self.assertTrue(linked.is_file())

    def test_credential_scanner_detects_unquoted_and_prefixed_key_assignments(
        self,
    ) -> None:
        # RED before the scanner fix: the old regex required a quoted value
        # and a strict `\b` before the key token, so it missed these
        # practical, unquoted, provider-prefixed forms entirely.
        cases = {
            "shell-export.sh": 'export GEMINI_API_KEY=not-a-real-secret\n',
            "env-style.sh": 'AWS_SECRET_ACCESS_KEY=not-a-real-secret\n',
            "access-key-id.sh": 'AWS_ACCESS_KEY_ID=not-a-real-secret\n',
            "yaml-style.md": 'ANTHROPIC_API_KEY: not-a-real-secret\n',
            "json-style.json": '{"GEMINI_API_KEY": "not-a-real-secret"}\n',
            "access-key-id.json": '{"AWS_ACCESS_KEY_ID": "not-a-real-secret"}\n',
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            fixture_paths = []
            for name, content in cases.items():
                fixture_path = tmp_root / name
                fixture_path.write_text(content, encoding="utf-8")
                fixture_paths.append(fixture_path)

            violations = _scan_paths_for_credential_violations(fixture_paths)

        self.assertEqual(
            len(cases),
            len(violations),
            "expected one violation per fixture:\n" + "\n".join(violations),
        )
        for name in cases:
            self.assertTrue(
                any(name in violation for violation in violations),
                f"expected a violation for {name}:\n" + "\n".join(violations),
            )

    def test_credential_scanner_detects_plaintext_apim_credential_header_value(
        self,
    ) -> None:
        # RED before the scanner fix: the old scanner was purely line-based
        # text matching and never inspected APIM XML `<value>` content, so a
        # real credential typed straight into a `set-header`'s `<value>`
        # (bypassing the Key Vault-backed named value) went undetected.
        fixture_xml = (
            "<policies><inbound>"
            '<set-header name="x-goog-api-key" exists-action="override">'
            "<value>not-a-real-secret</value>"
            "</set-header>"
            "</inbound></policies>"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture_path = Path(tmp_dir) / "leaky-policy.xml"
            fixture_path.write_text(fixture_xml, encoding="utf-8")
            violations = _scan_paths_for_credential_violations([fixture_path])

        self.assertEqual(1, len(violations), violations)
        self.assertIn("x-goog-api-key", violations[0])
        self.assertIn("not-a-real-secret", violations[0])

    def test_credential_scanner_detects_literal_wrapped_in_apim_policy_expression(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture_paths = []
            for index, expression in enumerate(
                (
                    '@("not-a-real-secret")',
                    '@(context.Variables.GetValueOrDefault&lt;string&gt;("computed-key") + "not-a-real-secret")',
                )
            ):
                fixture_xml = (
                    "<policies><inbound>"
                    '<set-header name="x-goog-api-key" exists-action="override">'
                    f"<value>{expression}</value>"
                    "</set-header>"
                    "</inbound></policies>"
                )
                fixture_path = Path(tmp_dir) / f"expression-wrapped-secret-{index}.xml"
                fixture_path.write_text(fixture_xml, encoding="utf-8")
                fixture_paths.append(fixture_path)
            violations = _scan_paths_for_credential_violations(fixture_paths)

        self.assertEqual(2, len(violations), violations)
        for violation in violations:
            self.assertIn("not-a-real-secret", violation)

    def test_credential_scanner_detects_plaintext_for_all_known_credential_headers(
        self,
    ) -> None:
        header_names = ("x-goog-api-key", "x-api-key", "Ocp-Apim-Subscription-Key")
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture_paths = []
            for index, header_name in enumerate(header_names):
                fixture_xml = (
                    "<policies><inbound>"
                    f'<set-header name="{header_name}" exists-action="override">'
                    "<value>not-a-real-secret</value>"
                    "</set-header>"
                    "</inbound></policies>"
                )
                fixture_path = Path(tmp_dir) / f"leaky-policy-{index}.xml"
                fixture_path.write_text(fixture_xml, encoding="utf-8")
                fixture_paths.append(fixture_path)

            violations = _scan_paths_for_credential_violations(fixture_paths)

        self.assertEqual(len(header_names), len(violations), violations)

    def test_credential_scanner_detects_aws_access_key_id_shapes(self) -> None:
        # Construct fixture-only values at runtime so a credential-shaped
        # sample never appears as one contiguous literal in source control.
        access_key_ids = (
            "AKIA" + "0123456789ABCDEF",
            "ASIA" + "0123456789ABCDEF",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture_path = Path(tmp_dir) / "aws-access-key-id.md"
            fixture_path.write_text(
                "\n".join(f"example = {access_key_id}" for access_key_id in access_key_ids),
                encoding="utf-8",
            )
            violations = _scan_paths_for_credential_violations([fixture_path])

        self.assertEqual(2, len(violations), violations)
        for access_key_id in access_key_ids:
            self.assertTrue(
                any(access_key_id in violation for violation in violations),
                access_key_id,
            )

    def test_credential_scanner_requires_key_vault_uris_for_bicep_secret_identifiers(
        self,
    ) -> None:
        safe_parameter_text = "\n".join(
            (
                "using './main.bicep'",
                "param geminiApiKeySecretIdentifier = 'https://gateway-kv.vault.azure.net/secrets/gemini-api-key'",
                "param languageApiKeySecretIdentifier = 'https://<key-vault-name>.vault.azure.net/secrets/<language-api-key-secret-name>'",
            )
        )
        unsafe_parameter_text = "\n".join(
            (
                "using './main.bicep'",
                "param bedrockSecretKeySecretIdentifier = 'not-a-key-vault-uri'",
            )
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            safe_path = tmp_root / "safe.bicepparam"
            unsafe_path = tmp_root / "unsafe.bicepparam"
            safe_path.write_text(safe_parameter_text, encoding="utf-8")
            unsafe_path.write_text(unsafe_parameter_text, encoding="utf-8")
            safe_violations = _scan_paths_for_credential_violations([safe_path])
            unsafe_violations = _scan_paths_for_credential_violations([unsafe_path])

        self.assertEqual([], safe_violations)
        self.assertEqual(1, len(unsafe_violations), unsafe_violations)
        self.assertIn("bedrockSecretKeySecretIdentifier", unsafe_violations[0])

    def test_credential_scanner_permits_named_values_expansions_placeholders_and_prose(
        self,
    ) -> None:
        # All of the below must NOT be flagged: a Key Vault-backed named
        # value, shell/`.env` environment-variable expansion in both `$VAR`
        # and `${VAR}` forms, a documented `<...>` placeholder, an empty
        # value, an APIM policy expression in a credential header, the
        # `secretIdentifier` declaration/reference pattern used throughout
        # `main.bicep`, a header-name label with no assignment following it,
        # and ordinary prose that merely mentions "API key".
        allowed_lines = "\n".join(
            [
                "GEMINI_API_KEY={{ai-hub-gemini-api-key}}",
                "AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY",
                "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY_ENV}",
                "GEMINI_API_KEY=<YOUR_API_KEY_HERE>",
                'GEMINI_API_KEY=""',
                "GEMINI_API_KEY:",
                "param geminiApiKeySecretIdentifier string",
                "secretIdentifier: geminiApiKeySecretIdentifier",
                "Store the API key in Key Vault and reference it via secretIdentifier.",
            ]
        )
        allowed_xml = (
            "<policies><inbound>"
            '<set-header name="x-goog-api-key" exists-action="override">'
            "<value>{{ai-hub-gemini-api-key}}</value>"
            "</set-header>"
            '<set-header name="x-api-key" exists-action="override">'
            "<value>@(context.Variables.GetValueOrDefault"
            "&lt;string&gt;(&quot;computed-key&quot;))</value>"
            "</set-header>"
            '<set-header name="Authorization" exists-action="delete" />'
            "</inbound></policies>"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            allowed_md = tmp_root / "allowed.md"
            allowed_md.write_text(allowed_lines, encoding="utf-8")
            allowed_policy = tmp_root / "allowed-policy.xml"
            allowed_policy.write_text(allowed_xml, encoding="utf-8")

            violations = _scan_paths_for_credential_violations(
                [allowed_md, allowed_policy]
            )

        self.assertEqual([], violations)

    def test_credential_scanner_is_error_loud_on_malformed_xml_in_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture_path = Path(tmp_dir) / "malformed.xml"
            fixture_path.write_text("<policies><inbound>", encoding="utf-8")
            with self.assertRaises(ValueError):
                _scan_paths_for_credential_violations([fixture_path])


if __name__ == "__main__":
    unittest.main()
