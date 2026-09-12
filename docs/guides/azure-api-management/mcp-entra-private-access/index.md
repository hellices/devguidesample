---
title: Entra ID로 내부망 MCP 보호하기 — 사용자 OBO와 백엔드 인증 분리
description: 로컬 개발 클라이언트의 MCP access token, 중간 서버의 OBO, APIM 인증 정책과 private DNS를 서로 다른 검증 단계로 구성합니다.
document_type: guide
services: [azure-api-management, azure-container-apps, microsoft-entra-id]
technologies: [mcp, azure-cli, bicep, python]
tags: [ai-agents, authentication, authorization, networking, security]
status: current
verification_status: verified
sources_checked_at: 2026-09-12
official_sources:
  - title: Microsoft identity platform and OAuth 2.0 On-Behalf-Of flow
    url: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow
  - title: Microsoft identity platform and OAuth 2.0 authorization code flow
    url: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-auth-code-flow
  - title: Secure applications and APIs by validating claims
    url: https://learn.microsoft.com/entra/identity-platform/claims-validation
  - title: Secure a Model Context Protocol (MCP) server with Microsoft Entra ID
    url: https://learn.microsoft.com/entra/agent-id/secure-mcp-server-with-entra-id
  - title: preAuthorizedApplication resource type
    url: https://learn.microsoft.com/graph/api/resources/preauthorizedapplication?view=graph-rest-1.0
  - title: Validate Microsoft Entra token
    url: https://learn.microsoft.com/azure/api-management/validate-azure-ad-token-policy
  - title: Secure access to MCP servers in API Management
    url: https://learn.microsoft.com/azure/api-management/secure-mcp-servers
  - title: Authenticate with managed identity
    url: https://learn.microsoft.com/azure/api-management/authentication-managed-identity-policy
  - title: Configure credential manager - user-delegated access to backend API
    url: https://learn.microsoft.com/azure/api-management/credentials-how-to-user-delegated
  - title: Deploy Azure MCP Server with on-behalf-of authentication
    url: https://learn.microsoft.com/azure/developer/azure-mcp-server/how-to/deploy-remote-mcp-server-on-behalf-of
  - title: Networking in an Azure Container Apps environment
    url: https://learn.microsoft.com/azure/container-apps/networking
  - title: Enable authentication and authorization in Azure Container Apps with Microsoft Entra ID
    url: https://learn.microsoft.com/azure/container-apps/authentication-entra
  - title: Microsoft.App containerApps/authConfigs
    url: https://learn.microsoft.com/azure/templates/microsoft.app/2025-01-01/containerapps/authconfigs
  - title: Configure built-in MCP server authorization (Preview)
    url: https://learn.microsoft.com/azure/app-service/configure-authentication-mcp
last_verified: 2026-09-12
review_cycle_days: 90
applies_to:
  - Azure public cloud
  - Azure MCP Server 2.0.5
  - MCP Python SDK 2.2.0
  - APIM Developer internal lab
related_cases:
  - ../../../cases/azure-api-management/mcp-entra-validation/index.md
---

# Entra ID로 내부망 MCP 보호하기 — 사용자 OBO와 백엔드 인증 분리

## 목표와 적용 범위

개발자의 로컬 클라이언트가 내부 MCP에 접근하고, **그 사용자의 Azure 권한으로** 읽기 도구를 실행하도록 구성합니다. APIM을 통과했다는 사실이나 관리 ID를 붙였다는 사실만으로 사용자 위임이 성립하지는 않습니다.

이 가이드는 인증·네트워크 경계를 설명합니다. [실습 소스](https://github.com/hellices/devguidesample/tree/main/samples/azure-api-management/mcp-entra-lab), [배포 절차](../../../labs/azure-api-management/mcp-rest-and-upstream/index.md), [관측값](../../../cases/azure-api-management/mcp-entra-validation/index.md)은 별도로 유지합니다. APIM preview 관리 API의 타입 차이는 해당 실습·사례의 확인일과 코드를 따르세요.

## 세 경계를 먼저 적는다

| 경계 | 질문 | 별도로 확인할 증거 |
|---|---|---|
| 네트워크 | 개발 PC가 MCP의 private 주소에 도달할 수 있는가? | Route, private DNS, TLS hostname |
| MCP API | 이 token이 이 API에 발급되었고 호출 scope가 있는가? | Signature, issuer, tenant, audience, 시간, scope, client |
| Downstream | 이 사용자가 이 Azure/GitHub/Kubernetes 작업을 할 수 있는가? | 리소스별 token과 실제 권한 검사 |

아키텍처 SVG와 다른 호스팅 선택지는 [비교·분석](../../../research/azure-api-management/mcp-authentication-options/index.md)에 있습니다.

### 내부 주소와 사용자 인증은 독립적이다

회사 LAN과 Azure VNet 사이에는 VPN/ExpressRoute 또는 승인된 별도 경로가 필요합니다. 같은 사내 계정을 쓴다고 private route가 생기지 않습니다.

- ACA 환경을 internal로 만들고 해당 환경의 private DNS를 연결합니다.
- APIM은 선택 SKU의 실제 모델을 확인합니다. Developer internal injection과 Standard v2의 inbound private endpoint·outbound integration은 같은 설정이 아닙니다.
- TLS hostname을 유지합니다. 인증서를 무시하거나 IP 주소로 URL을 바꾸어 연결 성공을 만들지 않습니다.
- 관리 터널을 사용한 실습 결과는 회사 VPN의 동작 결과로 일반화하지 않습니다.

[ACA networking](https://learn.microsoft.com/azure/container-apps/networking)에서 환경 접근성과 앱 ingress를 구분합니다. 내부 환경의 앱 ingress `external: true`를 곧바로 인터넷 공개로 해석하지 마세요.

## Entra 앱 등록: API와 클라이언트를 구분한다

### 보호할 API

예제에서는 목적이 다른 두 API identity를 분리합니다.

| API | 요구하는 JWT `scp` | 예제 목적 |
|---|---|---|
| Custom MCP / APIM lab API | `Mcp.Access` | Python MCP와 APIM 실습의 논리 API |
| 공식 Azure MCP API | `Mcp.Tools.ReadWrite` | Azure MCP 2.0.5의 인증 계약 |

API의 `api.requestedAccessTokenVersion`을 `2`로 설정합니다. **v2 access token의 audience는 API client GUID**입니다. scope URI, 클라이언트 앱 GUID, ARM URI와 혼동하지 않습니다.

### 로컬 public client

대화형 클라이언트는 사전 등록한 public client와 authorization code + PKCE를 사용합니다. public client에 confidential-client secret을 배포하지 않습니다.

Entra를 사용할 때 DCR이 자동으로 제공된다고 가정하지 않습니다. 실제 클라이언트 ID, redirect URI, 동의와 허용 client 정책을 준비합니다. [authorization code flow](https://learn.microsoft.com/entra/identity-platform/v2-oauth2-auth-code-flow)와 [MCP authorization 설정](https://learn.microsoft.com/azure/app-service/configure-authentication-mcp)을 함께 확인하세요.

사전 승인은 현재 Graph 계약의 다음 필드를 사용합니다.

```json
{
  "api": {
    "requestedAccessTokenVersion": 2,
    "preAuthorizedApplications": [
      {
        "appId": "<public-client-id>",
        "delegatedPermissionIds": ["<enabled-scope-id>"]
      }
    ]
  }
}
```

`delegatedPermissionIds`에는 scope의 **GUID**를 넣습니다. 문자열 `Mcp.Access`나 다른 예제의 `permissionIds`를 그대로 넣지 않습니다. [Graph resource contract](https://learn.microsoft.com/graph/api/resources/preauthorizedapplication?view=graph-rest-1.0)가 기준입니다.

Azure CLI 사전 승인은 지정한 API scope에만 적용됩니다. 이것만으로 middle tier의 ARM 권한·사용자 동의·Conditional Access 문제가 모두 해결되지는 않습니다.

**`preAuthorizedApplications`는 caller ACL이 아닙니다.** 동의 경험과 런타임의 client 허용 정책을 구분합니다. 샘플의 Python API는 비어 있지 않은 client allowlist를 필수로 요구합니다. 공식 Azure MCP 컨테이너 앞에는 Container Apps authentication의 `defaultAuthorizationPolicy.allowedApplications`를 별도로 적용합니다. Tenant·audience·scope가 맞더라도 허용하지 않은 client의 token은 이 경계에서 거부해야 합니다.

## MCP 서버의 inbound token 검증

검증은 도구 실행과 OBO 교환 **이전**에 수행합니다.

| 항목 | 예제의 검사 |
|---|---|
| 서명·알고리즘 | 고정 tenant의 JWKS, 허용 알고리즘 |
| `iss`, `tid` | 의도한 tenant와 issuer |
| `aud` | 보호 중인 API의 client ID |
| `exp`, `nbf` | 유효 시간 |
| `scp` | 해당 도구 API의 delegated scope |
| `azp` | 구성한 허용 client 목록 |
| 사용자 식별 | 유효 token의 subject와 위임 컨텍스트 |

**`oid`가 있다고 사용자 토큰인 것은 아닙니다.** App-only token도 서비스 주체의 `oid`를 가질 수 있습니다. API가 요구한 delegated scope와 인가 조건을 함께 검사해야 합니다.

서명 검증 전의 decode, 전달된 `X-MS-CLIENT-PRINCIPAL` 같은 헤더, 같은 tenant라는 사실만으로 사용자를 인증하지 않습니다. [claims 검증 문서](https://learn.microsoft.com/entra/identity-platform/claims-validation)의 audience·subject·actor 구분을 적용합니다.

### APIM 정책의 역할

APIM에서는 [validate-azure-ad-token](https://learn.microsoft.com/azure/api-management/validate-azure-ad-token-policy)에 audience와 scope를 명시합니다.

```xml
<validate-azure-ad-token
    tenant-id="{{tenant-id}}"
    header-name="Authorization"
    failed-validation-httpcode="401">
  <client-application-ids>
    <application-id>{{allowed-client-id}}</application-id>
  </client-application-ids>
  <audiences>
    <audience>{{mcp-api-client-id}}</audience>
  </audiences>
  <required-claims>
    <claim name="scp" match="all" separator=" ">
      <value>Mcp.Access</value>
    </claim>
  </required-claims>
</validate-azure-ad-token>
```

위 named value 표기는 설명용입니다. 실행 샘플은 비공개 배포 parameter로 실제 값을 주입합니다. 정책을 먼저 설치하고, initialize·도구 목록·도구 호출을 각각 무인증으로 검사합니다. `tools/call` 하나만 보호되는 상태는 충분하지 않습니다.

## OBO: token A와 token B를 분리한다

```text
개발자 → MCP API
  token A: aud = MCP API

MCP API → Entra token endpoint
  confidential-client 인증 + token A를 user assertion으로 사용

MCP API → ARM
  token B: ARM에 사용할 별도 token, 사용자의 권한 유지
```

1. Middle tier의 app에 필요한 **delegated downstream permission**을 설정합니다.
2. 사용자 또는 관리자의 필요한 동의를 준비합니다. 실습은 현재 운영자에 대한 `Principal` 동의를 사용합니다.
3. confidential client가 자신을 인증하고 OBO를 수행합니다.
4. 결과 token으로 고정된 테스트 리소스를 호출해 확인합니다.

ARM token을 MCP API에 넣거나, 원래 MCP token을 ARM에 그대로 보내는 것은 이 흐름이 아닙니다. 다른 API에 발급된 token을 자신의 assertion처럼 처리하지 않습니다. [OBO 문서](https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow)를 기준으로 하세요.

### 관리 ID를 사용하는 두 방식

| 방식 | 실제 의미 |
|---|---|
| MI/FIC로 confidential client 인증 후 OBO | 관리 ID는 서버 증명 수단, downstream 권한은 사용자 위임 |
| APIM `authentication-managed-identity` 또는 호스팅 자격 증명 | downstream에서 관리 ID 자체의 권한을 사용 |

두 번째 방식을 OBO 성공으로 기록하지 않습니다. 공식 Azure MCP 실습은 첫 번째 방식과 `UseOnBehalfOf`를 사용합니다. Python 예제의 짧은 수명 secret은 lab용 대조 예제이며, 개발 PC에 배포할 public-client secret이 아닙니다.

## Backend별 outbound 인증을 결정한다

| Backend | 처리 |
|---|---|
| ARM | 별도 OBO token과 Azure RBAC |
| Kubernetes | 별도 Kubernetes audience·인증·RBAC; AKS MCP v0.0.20은 로컬 실행 |
| GitHub | 사용자별 GitHub OAuth/PAT 또는 승인된 credential manager 연결 |
| Learn | 익명 호출; incoming Entra bearer 제거 |
| 가상 REST inventory | 실습용 비민감 fixture; 실제 업무 API는 자체 인증을 추가 |

실습의 REST fixture는 Authorization header가 도착하면 값을 반사하지 않고 400으로 거부합니다. 성공 응답의 `authorization_present: false`와 APIM 정책 read-back을 함께 검사하여, 도구 호출 성공만으로 token 제거를 추정하지 않습니다.

APIM [credential manager의 사용자 위임 연결](https://learn.microsoft.com/azure/api-management/credentials-how-to-user-delegated)은 외부 서비스의 별도 OAuth 연결입니다. Entra OBO가 임의 GitHub token으로 변환되는 기능으로 설명하지 않습니다.

기존 MCP 프록시와 REST-to-MCP 모두 outbound header를 확인합니다. APIM의 자동 header forwarding을 전제로 방치하지 마세요. [MCP 보안 문서](https://learn.microsoft.com/azure/api-management/secure-mcp-servers)를 참고합니다.

## OAuth discovery와 수동 bearer 검증을 구분한다

- PRM의 `resource`는 MCP 리소스를, `authorization_servers`는 인증 서버를 설명합니다.
- `WWW-Authenticate`의 `resource_metadata`가 있으면 그 URI를 따릅니다. URL을 항상 root well-known 경로로 추측하지 않습니다.
- 실제 광고된 scope가 의도한 API에 속하는지 확인하고, 그 scope로 token을 발급받아 audience·서명을 검사합니다.
- 수동 CLI token으로 MCP 호출이 성공한 결과와, IDE가 discovery → PKCE → consent → token 갱신까지 수행한 결과는 다릅니다.

실습은 광고된 scope를 실제 token 발급으로 검증합니다. 확인한 Azure MCP 버전의 `<CLIENT_ID>/Mcp.Tools.ReadWrite`와 custom API의 `api://<CLIENT_ID>/Mcp.Access`처럼 표기가 다를 수 있으므로 문자열 접두사를 임의로 덧붙이지 않습니다. 해당 관측은 [사례](../../../cases/azure-api-management/mcp-entra-validation/index.md)에 기록합니다.

## 실패를 분류한다

| 관측 | 먼저 확인할 것 |
|---|---|
| DNS 실패·연결 timeout | private route·DNS·gateway 상태 |
| 401 | token 존재, 서명·issuer·audience·시간·client 제한 |
| 403 | scope와 실제 인가 정책; app-only token 여부 |
| OBO 오류 / AADSTS 코드 | middle-tier 인증, downstream delegated permission·동의 |
| 도구 목록은 있으나 호출 실패 | backend 인증·권한·실제 operation 매핑 |
| HTTP 200인데 `isError=true` | MCP tool 실패; 성공으로 집계하지 않음 |
| 최신 SDK인데 이전 protocol 협상 | server revision과 호환 경로를 확인 |

Conditional Access가 추가 claims를 요구하면 클라이언트의 재인증 처리가 필요합니다. 같은 실패 token을 계속 재사용하거나 MI로 바꾸어 통과시키지 않습니다. 샘플은 안전한 오류 코드를 표면화하지만, 모든 CA 정책의 claims 재인증 UI를 구현한 제품은 아닙니다.

## 운영·정리

- 허용 도구·client·scope·실제 RBAC를 함께 검토합니다. read-only hint나 도구 필터만을 권한 경계로 쓰지 않습니다.
- 토큰·원본 사용자 로그·실제 환경 식별자는 공개 캡처와 PR에서 제외합니다.
- backend 연결 실패와 인증 실패를 모두 401로 덮어쓰지 않습니다.
- ARM 자원과 Entra 앱·서비스 주체·동의를 별도로 정리합니다.
- 배포일·검증한 revision·미실행 시나리오를 남기고 다시 검증합니다.

재현 순서와 비용·정리는 [실습](../../../labs/azure-api-management/mcp-rest-and-upstream/index.md), 과거의 오류와 실제 응답은 [관측 기록](../../../cases/azure-api-management/mcp-entra-validation/index.md)을 사용하세요.
