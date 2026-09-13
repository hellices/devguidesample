---
title: Azure MCP 인증 상세 참고 — Entra 앱, scope와 OBO
description: Azure MCP 통합 가이드에서 사용하는 Entra app registration, client ACL, access token과 OBO 설정을 상세히 설명합니다.
document_type: guide
services: [azure-api-management, azure-container-apps, microsoft-entra-id]
technologies: [mcp, azure-cli, bicep, python]
tags: [ai-agents, authentication, authorization, networking, security]
status: current
verification_status: verified
sources_checked_at: 2026-09-13
official_sources:
  - title: Azure Developer CLI reference
    url: https://learn.microsoft.com/azure/developer/azure-developer-cli/reference
  - title: Remote builds support with Azure Container Registry
    url: https://learn.microsoft.com/azure/developer/azure-developer-cli/remote-builds
  - title: Azure Developer CLI schema reference
    url: https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-schema
  - title: Customize your Azure Developer CLI workflows using command and event hooks
    url: https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-extensibility
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
  - title: Use a virtual network to secure inbound or outbound traffic for Azure API Management
    url: https://learn.microsoft.com/azure/api-management/virtual-network-concepts
  - title: Enable authentication and authorization in Azure Container Apps with Microsoft Entra ID
    url: https://learn.microsoft.com/azure/container-apps/authentication-entra
  - title: Microsoft.App containerApps/authConfigs
    url: https://learn.microsoft.com/azure/templates/microsoft.app/2025-01-01/containerapps/authconfigs
  - title: Configure built-in MCP server authorization (Preview)
    url: https://learn.microsoft.com/azure/app-service/configure-authentication-mcp
last_verified: 2026-09-13
review_cycle_days: 90
applies_to:
  - Azure public cloud
  - Azure MCP Server 2.0.5
  - MCP Python SDK 2.2.0
  - APIM Developer internal 구성
related_cases:
  - ../../../cases/azure-api-management/mcp-entra-validation/index.md
---

# Azure MCP 인증 상세 참고 — Entra 앱, scope와 OBO

**처음 구성할 때는 [Azure MCP 통합 가이드](../../../labs/azure-api-management/mcp-rest-and-upstream/index.md)를 따르세요.** 아키텍처, azd 배포, 호출 명령과 결과 캡처가 한 페이지에 있습니다. 이 문서는 app registration·scope·client ACL·OBO 설정을 변경하거나 인증 문제를 조사할 때 사용하는 상세 참고 자료입니다.

## 구성 요소와 인증 흐름

| 구성 요소 | 역할 |
|---|---|
| 로컬 MCP 클라이언트 | 사용자 로그인 후 호출할 MCP API의 access token을 받음 |
| Microsoft Entra ID | 클라이언트와 API의 앱 등록, scope, consent, access token 발급 |
| API Management | Entra access token을 검사하고 REST inventory를 MCP tool로 제공하거나 Learn MCP를 프록시 |
| Python MCP | `Mcp.Access` scope를 검사하고 inventory 조회, resource group OBO 조회, Learn 도구 제공 |
| 공식 Azure MCP | `Mcp.Tools.ReadWrite` scope를 검사하고 OBO로 Azure 서비스 호출 |
| Azure Resource Manager(ARM) | OBO로 발급된 access token과 사용자의 Azure RBAC에 따라 리소스 접근 허용 |

Python MCP와 공식 Azure MCP는 internal Container Apps 환경에서 실행합니다. APIM의 REST-to-MCP와 기존 MCP 프록시는 서로 다른 API이며, Python MCP의 OBO 도구 호출과도 별도 경로입니다. 구성도와 호스팅 대안은 [MCP 인증·호스팅 비교](../../../research/azure-api-management/mcp-authentication-options/index.md)에 있습니다.

## 1. azd 배포와 권한 준비

[샘플 소스](https://github.com/hellices/devguidesample/tree/main/samples/azure-api-management/mcp-entra-lab)의 `azure.yaml`은 `mcp`를 Container Apps service로 선언합니다. `project: .`의 Python 앱을 `python-app` module로 배포하며, `infra/main.bicep`에서 공통 Azure 리소스를 구성합니다. `docker.remoteBuild: true`로 ACR에 container image build를 요청합니다.

배포 전 다음을 준비합니다.

- Azure 리소스 생성과 필요한 role assignment를 수행할 권한.
- Entra 앱 등록·서비스 주체·federated identity credential(FIC)을 구성할 권한. Azure RBAC 역할과 Entra 디렉터리 권한은 별도로 부여합니다.
- MCP API의 delegated scope와 ARM delegated permission에 필요한 사용자 또는 관리자 consent.
- 사용할 로컬 클라이언트의 client ID, redirect URI, 접속할 tenant와 API client ID.
- 개발 PC에서 Azure VNet으로 연결할 VPN/ExpressRoute와 DNS 구성, 또는 실습에서 안내하는 개발용 접속 방법.

로그인과 환경 변수 설정은 실습의 준비 절차를 따른 뒤, 샘플 디렉터리에서 Entra 앱을 준비하고 배포 변경 내용을 확인합니다.

```bash
python3 scripts/identity.py prepare
azd provision --preview
azd up
```

Preview에 필요한 API client ID 등을 준비하기 위해 `identity.py prepare`를 먼저 실행합니다. `azd up`의 `preup` hook도 같은 Entra 준비 작업을 수행하며, `postprovision` hook은 서버 앱의 FIC가 생성된 managed identity를 신뢰하도록 구성합니다. `azd`가 리소스 배포, image build, 앱 배포를 진행합니다. 설정 형식은 [azure.yaml reference](https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-schema), build 방식은 [ACR remote build](https://learn.microsoft.com/azure/developer/azure-developer-cli/remote-builds)를 참고할 수 있습니다.

## 2. 로컬 PC에서 private endpoint와 내부 MCP에 접속하기

private endpoint는 VNet의 private IP로 접속합니다. 개발 PC가 회사 네트워크에 있다면 **그 IP까지 연결되는 VPN/ExpressRoute 경로와 private DNS 이름 해석**이 필요합니다. Entra 로그인은 이 네트워크 연결을 만들지 않습니다. 네트워크 연결 후 MCP에 보낸 HTTP 요청은 별도로 access token 검사를 받습니다.

샘플의 APIM Developer와 Container Apps는 private endpoint 대신 **internal VNet 구성**을 사용합니다. 두 방식 모두 개발 PC에서 private IP로 연결할 수 있어야 합니다.

1. 개발 PC에서 Azure VNet까지의 경로를 준비합니다.
2. APIM과 Container Apps의 hostname이 해당 환경의 private IP로 해석되도록 DNS를 구성합니다.
3. 원래 HTTPS hostname으로 요청합니다. IP 주소를 URL에 넣거나 TLS 인증서 검사를 끄는 방법은 사용하지 않습니다.
4. 네트워크 연결 후 access token 없이 요청하면 인증 오류를, 올바른 token으로 요청하면 MCP 응답을 받는지 확인합니다.

Container Apps의 internal 환경에서 앱 ingress `external: true`는 **같은 Container Apps 환경 밖의 VNet에서도 앱에 접근할 수 있음**을 뜻합니다. 환경 자체에 public endpoint가 생기는 것은 아닙니다. APIM Standard v2를 선택한다면 inbound private endpoint와 outbound VNet integration을 각각 구성해야 합니다. 자세한 차이는 [Container Apps networking](https://learn.microsoft.com/azure/container-apps/networking)과 [APIM VNet 구성](https://learn.microsoft.com/azure/api-management/virtual-network-concepts)에 정리되어 있습니다.

## 3. MCP API와 로컬 클라이언트의 앱 등록

### API client ID와 scope

샘플은 두 API 앱 등록을 사용합니다.

| API | 요청할 scope | access token의 `scp` |
|---|---|---|
| Python MCP와 APIM | `api://<custom-api-client-id>/Mcp.Access` | `Mcp.Access` |
| 공식 Azure MCP 2.0.5 | 서버의 OAuth metadata에 표시된 `Mcp.Tools.ReadWrite` scope URI | `Mcp.Tools.ReadWrite` |

API 앱 등록의 `api.requestedAccessTokenVersion`은 `2`로 설정합니다. v2 access token의 **`aud`는 호출 대상 API의 client ID(GUID)**입니다. 로컬 클라이언트의 client ID나 scope URI와는 다른 값입니다.

Azure MCP의 `--read-only`는 제공할 도구를 제한하는 옵션입니다. 이를 사용해도 incoming scope는 `Mcp.Tools.ReadWrite`입니다. 실제 Azure 리소스 접근은 사용자의 RBAC에도 제한됩니다.

### 로컬 클라이언트와 consent

대화형 MCP 클라이언트는 사전에 등록한 public client와 authorization code + PKCE를 사용합니다. 등록한 redirect URI와 클라이언트 설정이 일치해야 합니다. public client에는 client secret을 저장하지 않습니다.

Entra ID의 dynamic client registration(DCR)을 전제로 설정하는 대신, 사용할 IDE나 MCP 클라이언트의 client ID를 준비합니다. 사용자 consent를 생략하도록 특정 클라이언트를 사전 승인할 때는 API 앱 등록에 다음을 설정합니다.

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

`delegatedPermissionIds`는 scope 이름이 아니라 **해당 scope의 GUID**입니다. 이 사전 승인은 지정한 API permission에만 적용되며, ARM OBO에 필요한 permission과 consent는 별도로 구성합니다. 필드 정의는 [Microsoft Graph의 preAuthorizedApplication](https://learn.microsoft.com/graph/api/resources/preauthorizedapplication?view=graph-rest-1.0)를 따릅니다.

### 허용할 클라이언트 제한

`preAuthorizedApplications`는 consent 설정이며, 등록되지 않은 클라이언트의 HTTP 요청을 차단하는 ACL이 아닙니다. 샘플은 다음 위치에서 허용 client ID를 검사합니다.

- **Python MCP:** API 코드에서 access token의 `azp`와 client allowlist 비교.
- **APIM:** `validate-azure-ad-token`의 `client-application-ids`.
- **공식 Azure MCP:** Container Apps `authConfigs`의 `identityProviders.azureActiveDirectory.validation.defaultAuthorizationPolicy.allowedApplications`.

공식 Azure MCP 앞의 Container Apps authentication과 Azure MCP 자체의 tenant·audience·scope 검사를 함께 적용합니다. tenant와 scope가 맞아도 허용하지 않은 클라이언트의 token은 거부하도록 구성합니다.

## 4. access token으로 MCP 호출

실습에서는 APIM의 REST-to-MCP에 `curl`로 HTTP 요청을 보냅니다. 공식 Azure MCP·Python MCP와 APIM을 통한 Learn MCP 연결에는 **MCP Inspector 2.5.0 CLI**를 사용합니다. Inspector는 도구 목록과 호출 결과를 터미널에 표시하는 MCP 클라이언트입니다. 샘플은 Node.js 22.19 이상을 사용합니다.

MCP API는 도구 실행이나 OBO 교환 전에 access token을 검사합니다.

| 검사 항목 | 기대 값 |
|---|---|
| 서명 | 신뢰하는 Entra issuer의 공개 키와 허용한 알고리즘 |
| `iss`, `tid` | 구성한 issuer와 tenant |
| `aud` | 호출 대상 MCP API의 client ID |
| `exp`, `nbf` | 현재 유효한 token |
| `scp` | API가 요구하는 delegated scope |
| `azp` | 허용한 로컬 클라이언트의 client ID |

App-only token에도 서비스 주체의 `oid`가 들어갈 수 있습니다. `oid`가 있다는 이유만으로 사용자 token으로 처리하지 않고 delegated scope와 사용자 권한을 확인합니다. JWT 내용을 decode하는 것만으로는 서명 검사가 수행되지 않습니다.

APIM에서는 다음과 같이 audience, client ID, scope를 지정할 수 있습니다. `{{...}}`는 환경에 맞게 구성할 APIM named value입니다.

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

실습에서는 access token 없이 접속한 경우와 정상 token으로 접속한 경우를 차례로 비교합니다. `tools/list`와 `tools/call` 모두 인증 정책의 적용 대상입니다. 이전 MCP revision의 `initialize` 요청을 사용하는 클라이언트도 같은 정책을 적용받습니다.

## 5. OBO로 사용자의 resource group 조회

Python MCP의 resource group 도구와 공식 Azure MCP는 사용자 token을 받아 ARM용 access token을 발급받습니다.

```text
로컬 MCP 클라이언트 → MCP API
  MCP용 access token: aud = 중간 MCP API의 client ID

MCP API → Entra token endpoint
  서버 앱의 자격 증명 + MCP용 access token을 user assertion으로 제출

MCP API → ARM
  OBO로 발급받은 ARM용 access token으로 요청
  ARM이 사용자의 Azure RBAC에 따라 리소스 접근 허용
```

1. 중간 MCP API 앱에 ARM의 delegated permission을 추가하고 필요한 consent를 받습니다.
2. 리소스를 조회할 사용자에게 대상 범위의 Azure RBAC 역할을 부여합니다.
3. MCP API를 대상으로 발급한 access token으로 resource group 도구를 호출합니다.
4. 도구 응답에서 요청한 resource group과 반환된 내용을 확인합니다.

OBO의 user assertion은 **OBO를 요청하는 중간 API를 audience로 가진 사용자 access token**이어야 합니다. ARM용 token을 MCP API에 보내거나 app-only token을 user assertion으로 넣는 방식은 사용할 수 없습니다. 자세한 조건은 [Entra OBO flow](https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow)에 있습니다.

### Managed identity와 FIC의 역할

공식 Azure MCP의 `UseOnBehalfOf` 구성에서는 managed identity와 FIC로 **서버 앱을 confidential client로 인증**합니다. ARM에 보낼 token은 이후 OBO로 발급되며, 사용자 권한을 사용합니다. managed identity의 Azure 역할을 사용해 ARM을 호출하는 방식과 다릅니다.

Python 예제는 서버 측 client secret으로 confidential client를 인증합니다. 이 secret은 서버에서만 사용하며 로컬 MCP 클라이언트에 전달하지 않습니다. APIM의 `authentication-managed-identity` 정책은 APIM의 managed identity 권한으로 backend에 접근하는 기능으로, 사용자 OBO를 대신하지 않습니다.

## 6. REST inventory와 Learn MCP 호출

APIM에서는 다음 두 경로를 따로 사용합니다.

| 경로 | 호출 흐름 | Backend 인증 |
|---|---|---|
| REST-to-MCP | MCP tool → 등록한 REST operation → inventory API | 샘플의 가상 inventory 데이터는 사용자 token 없이 조회 |
| 기존 MCP 프록시 | MCP 요청 → 기존 Learn MCP 서버 | Learn은 익명 호출이므로 Entra `Authorization` header 제거 |

실습에서 REST inventory를 직접 조회한 뒤 같은 데이터를 MCP tool로 조회합니다. Learn 경로에서는 도구 목록을 읽고 문서 검색 도구를 호출합니다. 업무용 REST API로 교체할 때는 그 API에 필요한 인증을 별도로 설정합니다.

GitHub MCP를 추가하는 경우에도 GitHub OAuth 또는 PAT가 필요합니다. APIM [credential manager](https://learn.microsoft.com/azure/api-management/credentials-how-to-user-delegated)는 GitHub 같은 외부 서비스의 OAuth 연결을 관리하는 기능이며, Entra access token을 GitHub token으로 바꾸는 OBO 기능은 아닙니다.

## IDE에서 OAuth 로그인이 이어지지 않을 때

HTTP 호출에 access token을 직접 넣는 방법과 IDE가 로그인부터 token 갱신까지 처리하는 방법은 설정이 다릅니다. IDE 연결은 다음 순서로 확인합니다.

1. 인증되지 않은 요청의 `WWW-Authenticate` header에서 `resource_metadata` URL을 확인합니다.
2. 해당 protected-resource metadata(PRM)의 `resource`, `authorization_servers`, scope를 확인합니다.
3. 등록한 client ID와 redirect URI로 로그인하고 필요한 consent를 진행합니다.
4. MCP에 다시 연결하여 도구를 호출합니다.

Scope URI는 서버가 안내하는 값을 사용합니다. Azure MCP 2.0.5의 `<CLIENT_ID>/Mcp.Tools.ReadWrite`와 Python MCP의 `api://<CLIENT_ID>/Mcp.Access`처럼 형식이 다를 수 있습니다. Conditional Access가 추가 claims를 요구하면 이를 처리하는 클라이언트에서 다시 로그인해야 합니다.

## 오류별 확인 항목

| 증상 | 확인할 설정 |
|---|---|
| DNS 실패·연결 timeout | VPN/ExpressRoute 경로, private DNS, gateway 연결 |
| HTTP 401 | access token 누락, 서명·issuer·audience·유효 시간 |
| HTTP 403 | client allowlist, scope, API 인가 정책 |
| OBO 오류·AADSTS 코드 | 서버 앱 자격 증명, ARM delegated permission, consent, Conditional Access |
| ARM에서 접근 거부 | OBO 사용자에게 부여한 Azure RBAC와 대상 리소스 범위 |
| 도구 목록은 나오지만 호출 실패 | REST operation 연결, backend 연결·인증, 요청 인자 |
| HTTP 200이고 `isError=true` | MCP 응답에 담긴 도구 실행 오류 |

실제 HTTP status는 APIM 정책과 앱 설정에 따라 달라질 수 있습니다. 오류 응답의 내용도 함께 확인합니다. 비용과 리소스·Entra 앱 정리는 [실습의 정리 절차](../../../labs/azure-api-management/mcp-rest-and-upstream/index.md), 버전별 동작과 응답 차이는 [사례 기록](../../../cases/azure-api-management/mcp-entra-validation/index.md)을 참고하세요.
