# MCP HTTP 인증 단계별 확인

[Walkthrough](walkthrough.md)의 환경 변수, private 접속 경로와 token 준비를 마친 뒤 실행합니다. 이 절차는 **사전 발급한 token으로 MCP를 호출하는 것**과 **MCP client가 discovery부터 OAuth 로그인을 완료하는 것**을 구분합니다.

배포나 앱 등록을 변경하지 않고 현재 상태를 확인합니다. Raw 응답에는 환경 주소·식별자가 포함될 수 있으므로 `.private/`에만 저장합니다.

```bash
umask 077
export AUTH_CHECK="$PRIVATE/auth-recheck"
mkdir -p "$AUTH_CHECK"
```

## 1. APIM의 401 challenge와 PRM

```bash
curl --silent --show-error --max-time 90 \
  --config "$PRIVATE/transport.conf" \
  --header 'Content-Type: application/json' \
  --header 'Accept: application/json, text/event-stream' \
  --data-binary @requests/initialize.json \
  --suppress-connect-headers \
  --dump-header "$AUTH_CHECK/apim-401.headers" \
  --output "$AUTH_CHECK/apim-401.body" "$REST_MCP_URL"
```

Header에서 `401`과 `WWW-Authenticate`의 `resource_metadata` 값을 확인합니다. 그 URL을 그대로 입력해 인증 없이 metadata를 조회합니다.

```bash
read -r -p "resource_metadata URL from the challenge: " PRM_URL
curl --silent --show-error --fail --max-time 90 \
  --config "$PRIVATE/transport.conf" \
  --output "$AUTH_CHECK/apim-prm.json" "$PRM_URL"
jq '{resource,authorization_servers,scopes_supported,bearer_methods_supported}' \
  "$AUTH_CHECK/apim-prm.json"
```

확인할 값은 `resource`, `authorization_servers`, 필요한 scope와 header 기반 token 전달 방식입니다. **PRM 200만으로 OAuth 로그인까지 성공한 것은 아닙니다.**

## 2. Native Azure MCP의 well-known fallback

401 challenge에 `resource_metadata`가 없으면 well-known 경로도 확인합니다.

```bash
curl --silent --show-error --max-time 90 \
  --config "$PRIVATE/transport.conf" \
  --output "$AUTH_CHECK/native-prm.json" \
  --write-out 'HTTP %{http_code}\n' \
  "${AZURE_MCP_URL%/mcp}/.well-known/oauth-protected-resource"
```

이번 환경은 root 경로에서 200을 반환했고, `/.well-known/oauth-protected-resource/mcp`는 401이었습니다. 반환된 `resource`는 `/mcp`가 없는 server origin이므로 transport URL과 같은 문자열이라고 가정하지 않습니다.

## 3. Entra discovery와 PKCE 지원 선언

```bash
curl --silent --show-error --fail --max-time 30 \
  --output "$AUTH_CHECK/entra-oidc.json" \
  "https://login.microsoftonline.com/$TENANT_ID/v2.0/.well-known/openid-configuration"
jq '{
  authorization_endpoint_present:has("authorization_endpoint"),
  token_endpoint_present:has("token_endpoint"),
  pkce_metadata_present:has("code_challenge_methods_supported"),
  pkce_methods:.code_challenge_methods_supported,
  dcr_endpoint_present:has("registration_endpoint"),
  cimd_advertised:.client_id_metadata_document_supported
}' "$AUTH_CHECK/entra-oidc.json"
```

Entra는 [authorization code flow에서 S256을 지원](https://learn.microsoft.com/entra/identity-platform/v2-oauth2-auth-code-flow#request-an-authorization-code)합니다. 그러나 이번 tenant의 OIDC 응답에는 `code_challenge_methods_supported`가 없었습니다.

[MCP `2026-07-28` 보안 요구사항](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations#authorization-code-protection)은 client가 이 선언을 확인하고, 없으면 authorization을 진행하지 않도록 요구합니다. 이는 **PKCE 기능 자체가 없다는 실측이 아니라, metadata 기반 확인 조건이 충족되지 않았다는 결과**입니다. 검증을 우회하거나 metadata를 임의로 보충해 성공으로 처리하지 않습니다.

## 4. Canonical resource와 앱 등록 비교

```bash
az ad app show --id "$CUSTOM_ID" \
  --query '{identifierUris:identifierUris,tokenVersion:api.requestedAccessTokenVersion}' \
  --output json > "$AUTH_CHECK/custom-registration.json"
jq . "$AUTH_CHECK/custom-registration.json"
```

[Entra MCP 구성 문서](https://learn.microsoft.com/entra/agent-id/secure-mcp-server-with-entra-id)는 PRM의 `resource`, client의 대상 resource와 앱의 Application ID URI를 맞추도록 안내합니다.

현재 실습 앱에는 `api://<api-client-id>`가 있고 MCP의 HTTPS resource URI는 없습니다. 다음 요청으로 canonical URL을 token 대상으로 사용하는 경로를 별도로 확인할 수 있습니다.

```bash
RESOURCE="$(jq -r .resource "$AUTH_CHECK/apim-prm.json")"
az account get-access-token --tenant "$TENANT_ID" --resource "$RESOURCE" \
  --output json > "$AUTH_CHECK/resource-token.json" \
  2> "$AUTH_CHECK/resource-token-error.txt"
```

이번 결과는 `AADSTS500011`입니다. 기존 `api://.../Mcp.Access` scope를 사용한 token 발급은 성공했습니다. **이 CLI 요청은 target-resource 확인이며, `resource`와 scope를 포함한 브라우저 PKCE 교환 전체를 재현한 것은 아닙니다.**

## 5. Token 검증과 OBO는 별도로 확인

| 확인 | 실행 위치 | 이번 결과 |
|---|---|---|
| 정상 API token | [Walkthrough 5](walkthrough.md#5-rest-api를-apim-mcp-tool로-호출) | APIM initialize 200, RPC error 없음 |
| 다른 audience token | [Walkthrough 8](walkthrough.md#8-401과-403-확인) | APIM·Python MCP에서 401 |
| 사용자 OBO | [Walkthrough 6](walkthrough.md#6-azure-mcp에서-obo로-azure-조회) | Python MCP `read_lab_resource_group`에서 ARM 조회, `isError: false` |

이 결과는 **사전 token 발급·MCP API 검증·downstream OBO**의 증거입니다. 자동 OAuth 로그인, token refresh나 Toolbox의 consumer 인증까지 확인한 결과는 아닙니다.

## 결과와 후속 확인

- [비식별화한 결과](assets/captures/2026-09-13-auth-stages.json)
- [실행 사례](../../validation/index.md#oauth)
- 자동 OAuth 연결은 resource URI 정렬, authorization-server metadata와 실제 MCP client의 로그인 흐름을 추가로 확인해야 합니다.
- 이번 RG에는 Foundry project/Toolbox가 없어서 그 endpoint는 실측하지 않았습니다. 새 Foundry 리소스나 model은 배포하지 않았습니다.
- 확인용 token 파일은 사용 후 삭제하고, 사용한 port-forward 프로세스를 종료합니다. 기존 Azure 리소스의 삭제 절차는 변경하지 않습니다.
