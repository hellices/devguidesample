# Task 2 Report: Implement Bicep, Fixed Backends, and Native OpenAPI Contracts

## Scope
Implemented only the Task 2 assets under `apim/third-party-model-gateway/infra/`, `apim/third-party-model-gateway/openapi/`, and the explicitly requested edits to `apim/third-party-model-gateway/tests/test_gateway_artifacts.py`.

## Changed Files
- `apim/third-party-model-gateway/infra/main.bicep`
- `apim/third-party-model-gateway/infra/main.bicepparam`
- `apim/third-party-model-gateway/openapi/gemini.json`
- `apim/third-party-model-gateway/openapi/anthropic.json`
- `apim/third-party-model-gateway/openapi/bedrock.json`
- `apim/third-party-model-gateway/openapi/vertex.json`
- `apim/third-party-model-gateway/openapi/mcp.json`
- `apim/third-party-model-gateway/openapi/mcp-metadata.json`
- `apim/third-party-model-gateway/tests/test_gateway_artifacts.py`

## TDD Evidence
### RED step
Command:
```bash
python3 apim/third-party-model-gateway/tests/test_gateway_artifacts.py \
  GatewayArtifactTests.test_bicep_declares_fixed_backends_and_key_vault_references \
  -v
```

Output:
```text
test_bicep_declares_fixed_backends_and_key_vault_references (__main__.GatewayArtifactTests) ... ERROR

======================================================================
ERROR: test_bicep_declares_fixed_backends_and_key_vault_references (__main__.GatewayArtifactTests)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/tests/test_gateway_artifacts.py", line 58, in test_bicep_declares_fixed_backends_and_key_vault_references
    source = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/pathlib.py", line 1256, in read_text
    with self.open(mode='r', encoding=encoding, errors=errors) as f:
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/pathlib.py", line 1242, in open
    return io.open(self, mode, buffering, encoding, errors, newline,
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/pathlib.py", line 1110, in _opener
    return self._accessor.open(self, flags, mode)
FileNotFoundError: [Errno 2] No such file or directory: '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/infra/main.bicep'

----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (errors=1)
```

Assessment: **expected RED failure** because `infra/main.bicep` did not exist yet.

### GREEN check for the added test
Command:
```bash
python3 apim/third-party-model-gateway/tests/test_gateway_artifacts.py \
  GatewayArtifactTests.test_bicep_declares_fixed_backends_and_key_vault_references \
  -v
```

Output:
```text
test_bicep_declares_fixed_backends_and_key_vault_references (__main__.GatewayArtifactTests) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

Assessment: **resolved** after implementing `main.bicep`.

## Bicep Command Result
Command:
```bash
az bicep build --file apim/third-party-model-gateway/infra/main.bicep --stdout >/dev/null
```

Result:
```text
ERROR: /Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/infra/main.bicep(382,28) : Error BCP091: An error occurred reading file. Could not find file '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/policies/common-client-auth.xml'. [https://aka.ms/bicep/core-diagnostics#BCP091]
/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/infra/main.bicep(392,28) : Error BCP091: An error occurred reading file. Could not find file '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/policies/common-rate-limit.xml'. [https://aka.ms/bicep/core-diagnostics#BCP091]
/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/infra/main.bicep(402,28) : Error BCP091: An error occurred reading file. Could not find file '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/policies/common-pii-inbound.xml'. [https://aka.ms/bicep/core-diagnostics#BCP091]
/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/infra/main.bicep(411,28) : Error BCP091: An error occurred reading file. Could not find file '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/policies/gemini.xml'. [https://aka.ms/bicep/core-diagnostics#BCP091]
/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/infra/main.bicep(420,28) : Error BCP091: An error occurred reading file. Could not find file '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/policies/anthropic.xml'. [https://aka.ms/bicep/core-diagnostics#BCP091]
/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/infra/main.bicep(429,28) : Error BCP091: An error occurred reading file. Could not find file '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/policies/bedrock.xml'. [https://aka.ms/bicep/core-diagnostics#BCP091]
/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/infra/main.bicep(438,28) : Error BCP091: An error occurred reading file. Could not find file '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/policies/vertex.xml'. [https://aka.ms/bicep/core-diagnostics#BCP091]
/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/infra/main.bicep(447,28) : Error BCP091: An error occurred reading file. Could not find file '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/policies/mcp-resource-server.xml'. [https://aka.ms/bicep/core-diagnostics#BCP091]
/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/infra/main.bicep(456,28) : Error BCP091: An error occurred reading file. Could not find file '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/policies/mcp-metadata.xml'. [https://aka.ms/bicep/core-diagnostics#BCP091]
```

Assessment: **expected failure** pending Task 3 policy files. No other Bicep compile defects remained after adding `@secure()` to secret-identifier parameters and a deployment-time guard that rejects public Vertex AI host usage.

## Complete Static-Test Result
Command:
```bash
python3 -m unittest apim/third-party-model-gateway/tests/test_gateway_artifacts.py -v
```

Result:
```text
test_bicep_declares_fixed_backends_and_key_vault_references (apim.third-party-model-gateway.tests.test_gateway_artifacts.GatewayArtifactTests) ... ok
test_bicep_loads_every_policy_and_openapi_asset (apim.third-party-model-gateway.tests.test_gateway_artifacts.GatewayArtifactTests) ... ok
test_expected_artifacts_exist (apim.third-party-model-gateway.tests.test_gateway_artifacts.GatewayArtifactTests) ... FAIL
test_openapi_documents_parse (apim.third-party-model-gateway.tests.test_gateway_artifacts.GatewayArtifactTests) ... ok
test_policy_documents_parse (apim.third-party-model-gateway.tests.test_gateway_artifacts.GatewayArtifactTests) ... ERROR
test_provider_policies_include_common_security_fragments (apim.third-party-model-gateway.tests.test_gateway_artifacts.GatewayArtifactTests) ... ERROR
test_provider_policies_use_fixed_backends (apim.third-party-model-gateway.tests.test_gateway_artifacts.GatewayArtifactTests) ... ERROR

======================================================================
ERROR: test_policy_documents_parse (apim.third-party-model-gateway.tests.test_gateway_artifacts.GatewayArtifactTests)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/tests/test_gateway_artifacts.py", line 47, in test_policy_documents_parse
    root = ET.parse(ROOT / "policies" / name).getroot()
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/xml/etree/ElementTree.py", line 1229, in parse
    tree.parse(source, parser)
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/xml/etree/ElementTree.py", line 569, in parse
    source = open(source, "rb")
FileNotFoundError: [Errno 2] No such file or directory: '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/policies/common-client-auth.xml'

======================================================================
ERROR: test_provider_policies_include_common_security_fragments (apim.third-party-model-gateway.tests.test_gateway_artifacts.GatewayArtifactTests)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/tests/test_gateway_artifacts.py", line 87, in test_provider_policies_include_common_security_fragments
    source = (ROOT / "policies" / name).read_text(encoding="utf-8")
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/pathlib.py", line 1256, in read_text
    with self.open(mode='r', encoding=encoding, errors=errors) as f:
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/pathlib.py", line 1242, in open
    return io.open(self, mode, buffering, encoding, errors, newline,
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/pathlib.py", line 1110, in _opener
    return self._accessor.open(self, flags, mode)
FileNotFoundError: [Errno 2] No such file or directory: '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/policies/gemini.xml'

======================================================================
ERROR: test_provider_policies_use_fixed_backends (apim.third-party-model-gateway.tests.test_gateway_artifacts.GatewayArtifactTests)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/tests/test_gateway_artifacts.py", line 82, in test_provider_policies_use_fixed_backends
    source = (ROOT / "policies" / name).read_text(encoding="utf-8")
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/pathlib.py", line 1256, in read_text
    with self.open(mode='r', encoding=encoding, errors=errors) as f:
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/pathlib.py", line 1242, in open
    return io.open(self, mode, buffering, encoding, errors, newline,
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/pathlib.py", line 1110, in _opener
    return self._accessor.open(self, flags, mode)
FileNotFoundError: [Errno 2] No such file or directory: '/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/policies/gemini.xml'

======================================================================
FAIL: test_expected_artifacts_exist (apim.third-party-model-gateway.tests.test_gateway_artifacts.GatewayArtifactTests)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/hwang-inhwan/workspace/devguidesample.worktrees/ai-hub-llm-gateway-scaling-review/apim/third-party-model-gateway/tests/test_gateway_artifacts.py", line 36, in test_expected_artifacts_exist
    self.assertTrue((ROOT / "policies" / name).is_file(), name)
AssertionError: False is not true : common-client-auth.xml

----------------------------------------------------------------------
Ran 7 tests in 0.002s

FAILED (failures=1, errors=3)
```

Assessment:
- `test_bicep_declares_fixed_backends_and_key_vault_references`: **resolved/passing**
- `test_bicep_loads_every_policy_and_openapi_asset`: **resolved/passing**
- `test_openapi_documents_parse`: **resolved/passing**
- `test_expected_artifacts_exist`: **expected failure** until Task 3 adds policy files
- `test_policy_documents_parse`: **expected failure** until Task 3 adds policy files
- `test_provider_policies_include_common_security_fragments`: **expected failure** until Task 3 adds policy files
- `test_provider_policies_use_fixed_backends`: **expected failure** until Task 3 adds policy files

## Implementation Notes
- Added the Task 2 Bicep security assertion test first and captured the expected missing-file failure.
- Implemented APIM child resources against an **existing** `Microsoft.ApiManagement/service@2024-05-01` parent only.
- Added five fixed backend resources with TLS validation and the required backend IDs.
- Preserved provider-native OpenAPI paths and generic passthrough request/response schemas.
- Kept Vertex on the fixed private broker backend and added a `fail()`-based Bicep guard so `vertexBrokerUrl` cannot target the public Vertex AI host.
- Treated Key Vault secret identifiers strictly as inputs; no secrets or credentials were committed.
- Added the nonsecret `.bicepparam` template without any secret-identifier values.

## Self-Review
- `git diff --check HEAD~1 HEAD`: **clean**
- Reviewed the final commit contents and confirmed only the allowed Task 2 files changed.
- Code-review pass findings:
  - Review flagged missing policy-file build errors. **Classified expected** because the task brief explicitly says Task 3 owns the policy files and Task 2 must reference them now.
  - Review flagged `vertexBrokerUrl` as too permissive. **Resolved** by adding a deployment-time `fail()` guard against the public Vertex AI host.

## Commit
- SHA: `a36dcb8d2f6b46b26fe60eb0d4d43033bcf079a2`
- Subject: `feat(apim): add third-party model gateway infrastructure`

## Remaining Concern
- Bicep build and four static-test failures are intentionally blocked on the Task 3 policy assets; no placeholder policy files were added in this task.


## Follow-up: Coverage Fix for Key Vault Secret Identifiers

### Changed File
- `apim/third-party-model-gateway/tests/test_gateway_artifacts.py`

### Commands and Output
Focused test:
```bash
python3 apim/third-party-model-gateway/tests/test_gateway_artifacts.py GatewayArtifactTests.test_bicep_declares_fixed_backends_and_key_vault_references -v
```
Output: `ok`

Complete static suite:
```bash
python3 -m unittest apim/third-party-model-gateway/tests/test_gateway_artifacts.py -v
```
Output: focused test `ok`; remaining failures were the pre-existing Task 3 policy-file gaps (`common-client-auth.xml`, `common-rate-limit.xml`, `common-pii-inbound.xml`, and provider policy files).

### Expected vs Resolved
- Resolved: added exact assertions for `bedrockSecretKeySecretIdentifier` and `languageApiKeySecretIdentifier`.
- Resolved: focused Bicep assertion test passes.
- Expected remaining failures: policy artifact tests that depend on Task 3 files.

### Self-Review
- Confirmed no unrelated files were edited.
- Confirmed the change only expands the existing Bicep key-vault coverage test.
- Confirmed Bicep/OpenAPI behavior was not modified.

### Commit
- SHA: `9d90b64fe22857eaa5a7429c9607234c25b7da53`
- Subject: `test(apim): cover all gateway key vault values`

## Follow-up: Explicit APIM Policy Dependency Ordering

### Scope
- Updated only `apim/third-party-model-gateway/infra/main.bicep` and `apim/third-party-model-gateway/tests/test_gateway_artifacts.py` for the Task 2 deployment-ordering finding.
- Did not edit policy XML, OpenAPI assets, docs, the plan/spec, or the pre-existing untracked architecture review.

### Changed Files
- `apim/third-party-model-gateway/infra/main.bicep`
- `apim/third-party-model-gateway/tests/test_gateway_artifacts.py`

### TDD Evidence
#### RED step
Command:
```bash
python3 apim/third-party-model-gateway/tests/test_gateway_artifacts.py \
  GatewayArtifactTests.test_bicep_explicitly_orders_policy_fragments_and_api_policies \
  -v
```
Result: `FAIL` because `clientAuthPolicyFragment` did not contain a `dependsOn` block.

#### GREEN step
Command:
```bash
python3 apim/third-party-model-gateway/tests/test_gateway_artifacts.py \
  GatewayArtifactTests.test_bicep_explicitly_orders_policy_fragments_and_api_policies \
  -v
```
Result: `OK` after adding explicit resource-symbol-based dependencies.

### Exact Validation Commands and Results
1. Focused dependency test:
```bash
python3 apim/third-party-model-gateway/tests/test_gateway_artifacts.py \
  GatewayArtifactTests.test_bicep_explicitly_orders_policy_fragments_and_api_policies \
  -v
```
Result: `OK`

2. Full Bicep build:
```bash
az bicep build --file apim/third-party-model-gateway/infra/main.bicep --stdout >/dev/null
```
Result: `BCP091` missing-file errors only for Task 3 policy XML files:
`common-client-auth.xml`, `common-rate-limit.xml`, `common-pii-inbound.xml`, `gemini.xml`, `anthropic.xml`, `bedrock.xml`, `vertex.xml`, `mcp-resource-server.xml`, and `mcp-metadata.xml`.

3. Full static suite:
```bash
python3 -m unittest apim/third-party-model-gateway/tests/test_gateway_artifacts.py -v
```
Result: dependency test plus existing OpenAPI/Bicep static tests passed; remaining failures were limited to the expected Task 3 policy-file gaps (`test_expected_artifacts_exist`, `test_policy_documents_parse`, `test_provider_policies_include_common_security_fragments`, `test_provider_policies_use_fixed_backends`).

### Expected vs Resolved Failures
- Resolved: APIM policy fragments now explicitly depend on the named values they require.
- Resolved: Provider API policies now explicitly depend on the shared fragments, their fixed backend resources, and provider-specific named values required by policy evaluation.
- Resolved: Added a focused offline regression test that inspects specific resource blocks and asserts the meaningful `dependsOn` symbols.
- Expected remaining blocker: Bicep build/static failures caused only by missing Task 3 policy XML files.

### Self-Review
- Confirmed the `loadTextContent()` policy/OpenAPI mappings were unchanged.
- Confirmed all Task 2 backend names, routes, and parameters remain unchanged.
- Confirmed dependencies use Bicep resource symbols instead of ordering-by-position assumptions.
- Ran `git diff --check` with no whitespace or patch-format issues.

### Implementation Commit
- SHA: `ebf0e30499b91ef988ec9c53472e8abeb9a691dd`
- Subject: `fix(apim): order gateway policy dependencies`
