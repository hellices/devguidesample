---
title: Azure MCP 인증 설계 비교 — 프로토콜 revision, Entra OBO, APIM의 두 MCP 모델
description: 현재 MCP 사양과 서버별 인증 경계를 비교하고, 내부망 개발 클라이언트에서 실제로 검증할 수 있는 Azure 호스팅 구성을 선택합니다.
document_type: research
services: [azure-api-management, azure-container-apps, azure-app-service, azure-functions, azure-kubernetes-service, microsoft-entra-id]
technologies: [mcp, azure-cli, bicep, python]
tags: [ai-agents, architecture, authentication, authorization, networking]
status: current
verification_status: needs-review
sources_checked_at: 2026-09-12
published_at: 2026-09-12
official_sources:
  - title: MCP specification — versioning
    url: https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning
  - title: MCP specification — authorization
    url: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
  - title: MCP Python SDK
    url: https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/README.md
  - title: About MCP servers in Azure API Management
    url: https://learn.microsoft.com/azure/api-management/mcp-server-overview
  - title: Expose REST API in API Management as an MCP server
    url: https://learn.microsoft.com/azure/api-management/export-rest-mcp-server
  - title: Manage MCP servers programmatically in API Management
    url: https://learn.microsoft.com/azure/api-management/manage-mcp-servers-rest-api
  - title: Feature-based comparison of the Azure API Management tiers
    url: https://learn.microsoft.com/azure/api-management/api-management-features
  - title: Microsoft identity platform and OAuth 2.0 On-Behalf-Of flow
    url: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow
  - title: Secure a Model Context Protocol (MCP) server with Microsoft Entra ID
    url: https://learn.microsoft.com/entra/agent-id/secure-mcp-server-with-entra-id
  - title: Deploy Azure MCP Server with on-behalf-of authentication
    url: https://learn.microsoft.com/azure/developer/azure-mcp-server/how-to/deploy-remote-mcp-server-on-behalf-of
  - title: GitHub MCP Server
    url: https://github.com/github/github-mcp-server
  - title: AKS MCP v0.0.20
    url: https://github.com/Azure/aks-mcp/releases/tag/v0.0.20
  - title: Connect your Azure Kubernetes Service (AKS) cluster to AI agents using the Model Context Protocol (MCP) server
    url: https://learn.microsoft.com/azure/aks/aks-model-context-protocol-server
  - title: Microsoft Learn MCP Server developer reference documentation
    url: https://learn.microsoft.com/training/support/mcp-developer-reference
  - title: Networking in an Azure Container Apps environment
    url: https://learn.microsoft.com/azure/container-apps/networking
  - title: Enable authentication and authorization in Azure Container Apps with Microsoft Entra ID
    url: https://learn.microsoft.com/azure/container-apps/authentication-entra
  - title: Microsoft.App containerApps/authConfigs
    url: https://learn.microsoft.com/azure/templates/microsoft.app/2025-01-01/containerapps/authconfigs
  - title: Virtual network configuration
    url: https://learn.microsoft.com/azure/container-apps/custom-virtual-networks
  - title: Use private endpoints for Azure App Service apps
    url: https://learn.microsoft.com/azure/app-service/overview-private-endpoint
  - title: Configure built-in MCP server authorization (Preview)
    url: https://learn.microsoft.com/azure/app-service/configure-authentication-mcp
  - title: Self-hosted remote MCP server on Azure Functions (public preview)
    url: https://learn.microsoft.com/azure/azure-functions/self-hosted-mcp-servers
  - title: Azure Functions networking options
    url: https://learn.microsoft.com/azure/azure-functions/functions-networking-options
---

# Azure MCP 인증 설계 비교 — 프로토콜 revision, Entra OBO, APIM의 두 MCP 모델

## 결론

내부망 개발자가 사용하는 MCP를 Azure에서 운영할 때는 **네트워크 진입, MCP API 인증, 도구의 downstream 권한**을 따로 설계해야 합니다. Entra 토큰을 받는 게이트웨이가 있다고 해서 GitHub·Azure·Kubernetes·Learn이 같은 토큰을 받아들이지는 않습니다.

이번 구성의 선택은 다음과 같습니다.

1. 공식 **Azure MCP는 내부 Container Apps에서 Entra OBO**로 실행합니다.
2. **APIM Developer internal**에서 REST operation을 MCP tool로 만드는 경로와 기존 Learn MCP를 프록시하는 경로를 각각 검증합니다.
3. **AKS MCP v0.0.20은 로컬 stdio**로 유지합니다. 원격으로 올리는 예제를 현재 지원 구성이라고 소개하지 않습니다.
4. GitHub는 자체 자격 증명, Learn은 익명 upstream으로 연결합니다.

배포와 실행 결과는 [실습](../../../labs/azure-api-management/mcp-rest-and-upstream/index.md) 및 [관측 기록](../../../cases/azure-api-management/mcp-entra-validation/index.md)으로 분리했습니다. 이 문서의 대안 전체를 모두 배포한 것은 아닙니다.

## 조사 범위와 방법

기준일은 **2026-09-13 KST / 2026-09-12 UTC**입니다. Microsoft Learn MCP의 실제 `tools/list`를 확인한 다음 공식 검색 도구로 자료를 찾고, 선택한 원문을 fetch하여 지원 범위·제약·구성 방법을 비교했습니다. MCP 자체 사양과 구현은 공식 프로젝트의 revision·release·source를 추가 확인했습니다.

확인일의 두 문서 충돌은 해결된 것처럼 지우지 않았습니다.

- AKS Learn 문서의 원격 배포 설명과 **AKS MCP v0.0.20의 원격 기능 제거**가 다릅니다.
- APIM 관리 문서·Bicep 타입의 endpoint 배열과 **실제 API·공식 AI-Gateway 샘플의 keyed object 및 `backendId`** 계약이 다릅니다.

따라서 자료 검토 상태는 `needs-review`로 유지합니다. 아래에서는 **공식 문서상 지원**, **고정 버전의 구현**, **실제 실행 관측**을 구분합니다.

## “MCP 2.0”에서 먼저 구분할 다섯 가지

| 구분 | 조사 시점의 예 | 의미 |
|---|---|---|
| MCP **프로토콜 revision** | `2026-07-28` | 날짜 기반의 wire contract |
| Python SDK | `mcp==2.2.0` | SDK v2의 패키지 버전 |
| 메시지 형식 | JSON-RPC `2.0` | MCP가 사용하는 RPC 메시지 형식 |
| 인증·인가 표준 | OAuth `2.0` / `2.1` | 인증 서버·리소스 서버·클라이언트의 역할과 보안 요구 |
| 제품 패키지 | Azure MCP `2.0.5` | 특정 MCP 서버 구현의 release |

“SDK v2를 쓴다”와 “모든 연결이 최신 MCP revision을 쓴다”는 다른 주장입니다.

### 최신 revision과 기존 연결의 차이

| 항목 | 최신 `2026-07-28` | 실습에서 만난 이전 revision |
|---|---|---|
| 서버 기능·버전 확인 | `server/discover`, 요청별 metadata | `initialize`와 initialized notification |
| HTTP 전송 | POST, JSON 또는 요청 단위 SSE 응답 | Streamable HTTP의 기존 세션·협상 규칙 |
| 세션·GET stream | 프로토콜 세션과 GET stream 제거 | 서버에 따라 `Mcp-Session-Id`, GET stream 지원 |
| 헤더 | `MCP-Protocol-Version`, `Mcp-Method`, 해당 요청의 `Mcp-Name` | 협상된 revision의 규칙을 적용 |

**SSE 응답 자체가 모두 사라진 것은 아닙니다.** 최신 규칙을 이전 revision으로 협상된 연결에 무조건 적용하지 않습니다. 실습 클라이언트는 SDK v2의 `auto` 모드를 사용하고, 실제 협상 결과를 저장합니다. [버전 협상 사양](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)과 [Streamable HTTP 사양](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)이 기준입니다.

프로토콜의 `server/discover`와 OAuth의 **protected-resource metadata(PRM)**도 다릅니다. 후자는 클라이언트가 어느 authorization server와 scope를 사용해야 하는지 찾는 경로입니다.

## 서버별로 서로 다른 인증 계약

| 서버 | 확인한 버전·연결 | 호출자 인증 | downstream 인증 |
|---|---|---|---|
| GitHub MCP | 공개 release `v1.12.1`; hosted 배포 버전과 동일하다고 가정하지 않음 | GitHub OAuth 또는 PAT | GitHub 권한 |
| Azure MCP | 안정판 `2.0.5`, HTTP 및 stdio | HTTP에서 Entra; 로컬 stdio는 프로세스 신뢰 경계 | 사용자 OBO 또는 명시적 호스팅 자격 증명 |
| AKS MCP | `v0.0.20`, **로컬 stdio** | 로컬 신뢰 클라이언트·프로세스 | Azure 자격 증명과 Kubernetes 인증을 각각 사용 |
| Microsoft Learn MCP | 공개 endpoint; 실제 협상은 `2025-06-18` | 인증 불필요 | 공개 문서 검색·조회 |

![로컬 개발 클라이언트가 Azure와 AKS에는 로컬 사용자 자격 증명을, GitHub에는 GitHub 자격 증명을 사용하고 Learn에는 토큰을 보내지 않는 구조](images/local-upstreams.svg)

### Azure MCP의 주의점

- HTTP의 위임 scope는 `Mcp.Tools.ReadWrite`입니다. `--read-only`는 도구를 제한하지만 scope를 `Mcp.Tools.Read`로 바꾸지 않습니다.
- `--outgoing-auth-strategy UseOnBehalfOf`는 사용자 위임입니다.
- `UseHostingEnvironmentIdentity`는 호스팅 환경의 자격 증명을 사용합니다. 로컬에서는 Azure CLI 사용자일 수 있고, 클라우드에서는 관리 ID일 수 있습니다. 이름만 보고 항상 같은 의미라고 해석하지 않습니다.
- 조사 시점의 컨테이너 `latest`는 `3.0.0-beta.43`과 같은 manifest를 가리켰습니다. 실습은 안정판 `2.0.5`의 확인한 digest를 고정했습니다.

인증 구성은 [공식 OBO 배포 문서](https://learn.microsoft.com/azure/developer/azure-mcp-server/how-to/deploy-remote-mcp-server-on-behalf-of)와 [공식 템플릿](https://github.com/Azure-Samples/azmcp-obo-template)을 기준으로 하되, 공용 ingress 기본값을 내부망 설계로 바꿨습니다.

### AKS MCP의 버전 경계

[v0.0.20 release](https://github.com/Azure/aks-mcp/releases/tag/v0.0.20)는 HTTP/SSE, browser-facing OAuth/OBO, token forwarding, Docker·Helm 및 원격 배포를 제거했습니다. 이 버전에 `--transport`를 넣거나 원격 게이트웨이 뒤에 배치하는 것을 지원 예제로 소개하면 안 됩니다.

`--access-level readonly`는 실수의 영향을 줄이는 도구 제한이지 사용자 격리나 RBAC를 대신하는 보안 경계가 아닙니다. 실습에서는 새 클러스터의 별도 kubeconfig와 지정 namespace만 사용합니다.

### GitHub와 Learn은 Entra OBO 변환 대상이 아니다

GitHub 서버의 `--authorization-server`를 Entra URL로 바꾸는 것만으로 GitHub 토큰 검증·발급 체계가 바뀌지 않습니다. 사용자별 GitHub 권한이 필요하면 별도 GitHub OAuth 연결을 유지해야 합니다.

Learn을 Entra로 보호된 APIM 뒤에 둘 수는 있지만, 그때도 **upstream Learn에는 원래 Entra 토큰을 보내지 않습니다.** 내부 front door를 만들었다고 외부 GitHub·Learn endpoint가 private endpoint로 바뀌는 것도 아닙니다.

## Azure 호스팅·인증 적용 지점

| 선택지 | 인증을 붙이는 곳 | 내부망 구성 | OBO에서 직접 구현·확인할 것 |
|---|---|---|---|
| Container Apps | 앱의 JWT 검증 또는 Easy Auth | Internal workload-profiles environment, private DNS | confidential middle tier, consent, 사용자별 token 획득 |
| APIM | `validate-azure-ad-token` 등 gateway 정책 | Developer/Premium classic internal injection; Standard v2는 private endpoint + outbound integration 구분 | 프록시·REST 변환 자체는 OBO가 아님 |
| App Service | Easy Auth 또는 앱 middleware | Private endpoint는 inbound, VNet integration은 outbound | access-token audience와 downstream OBO |
| Functions | built-in auth 또는 함수/서버 코드 | Flex Consumption의 private networking; legacy Consumption과 구분 | hosting 모델·MCP transport·인증 preview 범위 |
| AKS에 자체 MCP 앱 호스팅 | 애플리케이션·ingress/gateway | 내부 LoadBalancer·DNS·network policy | Workload Identity와 사용자 OBO 구분 |

마지막 행은 **사용자 정의 MCP 앱의 AKS 호스팅**이지, AKS MCP v0.0.20 서버를 원격 배포해도 된다는 뜻이 아닙니다.

### 1. 내부 Container Apps + 공식 Azure MCP OBO

![내부 Container Apps의 Azure MCP가 Entra 사용자 토큰을 검증하고 관리 ID 기반 federated credential로 confidential client를 인증한 뒤 별도 ARM 토큰을 얻는 구조](images/container-apps-obo.svg)

관리 ID는 여기서 **서버 애플리케이션 자신을 증명하는 수단**입니다. ARM에서 사용자를 대신하는 토큰은 OBO 결과물입니다. 호스팅 관리 ID에 넓은 Reader를 부여하여 OBO 실패를 가리는 방식은 사용하지 않습니다.

Native Azure MCP의 tenant·audience·scope 검사와 별도로, 실습에서는 Container Apps authentication으로 허용 client ID를 제한했습니다. 앱 등록의 사전 승인과 런타임 caller ACL을 같은 것으로 취급하지 않습니다.

내부 ACA 환경에서 앱 ingress의 `external: true`는 ACA 환경 밖의 **VNet 내 접근**을 의미할 수 있습니다. 환경의 internal 설정과 앱 ingress 플래그를 따로 봅니다. VNet 환경의 관리 RG와 인프라 비용도 함께 계산해야 합니다.

### 2. APIM의 REST-to-MCP

![Entra로 보호된 APIM이 기존 REST operation을 native MCP tool에 연결하고 실제 REST 백엔드를 호출하는 구조](images/apim-rest-tools.svg)

APIM이 이미 관리하는 REST operation을 선택하여 **MCP tool 리소스에 연결**합니다. 별도 MCP 서버 프로세스가 없어도 protocol 변환을 할 수 있습니다. 그러나 REST backend의 인증·권한이 자동으로 사용자 OBO가 되는 것은 아닙니다.

실증 기준은 API 생성 성공이 아니라 **독립 REST 호출 → 도구 목록 → 해당 tool 호출 → 실제 backend invocation marker**입니다. [REST 노출 문서](https://learn.microsoft.com/azure/api-management/export-rest-mcp-server)를 기준으로, 도구의 `operationId`가 실제 operation에 연결되었는지 확인합니다.

### 3. APIM의 기존 MCP 프록시

![APIM이 Entra 토큰을 검증한 뒤 Authorization을 제거하고 기존 공개 Learn MCP 서버에 연결하는 구조](images/apim-existing-mcp.svg)

REST operation을 MCP로 바꾸는 것이 아니라 **기존 MCP 서버의 도구를 프록시**합니다. 실습의 Learn 경로는 native MCP API, 명시적 backend 리소스, `backendId` 및 `message` endpoint를 사용했습니다.

확인일의 관리 문서와 실제 계약 차이는 [관측 기록](../../../cases/azure-api-management/mcp-entra-validation/index.md)에 남겼습니다. `serviceUrl`만 넣고 HTTP 200 또는 빈 도구 목록을 확인한 것은 성공이 아닙니다.

### 4. App Service 대안

![App Service private endpoint로 들어온 요청을 Easy Auth 또는 JWT middleware에서 검증하고 별도 confidential middle tier에서 OBO를 수행하는 대안](images/app-service-alternative.svg)

**이 경로는 조사 대안이며 이번 실행의 배포 결과가 아닙니다.** 고객 소유 RG 하나에 자원을 모으는 제약이 강하면 App Service가 비교하기 쉽습니다. Private endpoint와 VNet integration은 다른 방향의 기능이고, public access 차단과 SCM/Kudu private DNS도 별도로 확인해야 합니다.

App Service의 MCP authorization/PRM 및 built-in REST-to-MCP에는 확인일 기준 preview 범위가 있습니다. 다중 MCP 서버·사용자별 토큰 관리가 필요하면 built-in 변환만으로 해결된다고 가정하지 않습니다.

### 5. Functions Flex 대안

![Functions Flex Consumption에서 private endpoint와 VNet integration을 사용하고 stateless SDK MCP와 인증·위임 코드를 분리하는 대안](images/functions-alternative.svg)

**이 경로도 조사 대안입니다.** 기존 SDK 서버를 self-hosted/custom-handler 방식으로 호스팅하는 문서는 public preview, Flex Consumption, stateless Streamable HTTP라는 범위를 명시합니다. 함수 key만으로 Entra/OBO 요구를 충족했다고 판단하지 않습니다.

## APIM SKU를 고를 때

| SKU | 이 실습 관점의 판단 |
|---|---|
| Consumption | 현재 native MCP 적용 SKU 목록에 없고 요구한 private networking에도 맞지 않음 |
| Developer | Internal VNet과 private backend 연결을 검증하는 실습에 선택; SLA 없음 |
| Basic / Standard classic | Inbound private endpoint와 private backend egress 능력을 혼동하지 않음 |
| Basic v2 | MCP 기능 목록에 있다고 private networking도 같은 것은 아님 |
| Standard v2 | Outbound integration만으로 ingress가 private해지지 않음; inbound private endpoint도 설계 |
| Premium 계열 | 해당 세대의 injection·private networking 기능과 비용을 별도 비교 |

SKU 판단은 [기능 비교표](https://learn.microsoft.com/azure/api-management/api-management-features)와 [가상 네트워크 모델](https://learn.microsoft.com/azure/api-management/virtual-network-concepts)을 함께 봅니다.

## Entra OBO에서 바꾸면 안 되는 경계

1. 클라이언트가 받은 token A의 `aud`는 **중간 MCP API**여야 합니다. ARM token을 MCP 인증으로 재사용하지 않습니다.
2. confidential middle tier가 token A를 assertion으로 제출해 **downstream용 token B**를 얻습니다.
3. token B의 리소스와 사용자 권한이 downstream 호출에 맞아야 합니다. ARM과 Kubernetes의 audience도 구분합니다.
4. application-only token을 사용자 OBO의 입력으로 대체하지 않습니다.
5. GitHub credential manager 연결은 별도의 외부 OAuth 연결입니다. 일반적인 Entra→GitHub 토큰 변환으로 설명하지 않습니다.

v2 access token의 `aud`는 API의 client GUID입니다. OAuth에 요청하는 scope 문자열과 JWT `scp`의 표기, PRM의 resource URL을 한 문자열로 취급하면 안 됩니다. [claims 검증](https://learn.microsoft.com/entra/identity-platform/claims-validation)과 [OBO 계약](https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow)이 기준입니다.

## 검증 범위와 다음 선택

- **실제 검증:** 새 Azure 기반 자원, 지정 사용자 token·OBO, 네 upstream MCP, 내부 hosted MCP, APIM native REST 도구 및 Learn 프록시. 정확한 테스트·시각은 관측 기록과 JSON을 봅니다.
- **별도 확인 필요:** 회사 LAN/VPN/ExpressRoute, 다른 사용자와 다른 RBAC, 모든 Conditional Access 조합, 각 IDE의 대화형 discovery/PKCE, App Service·Functions 실제 배포.
- **자동으로 따라오지 않는 것:** 테넌트 전체 동의, GitHub 사용자별 credential 연결, 비용 상한, RG 삭제에 의한 Entra 객체 정리.

먼저 [내부망·Entra 가이드](../../../guides/azure-api-management/mcp-entra-private-access/index.md)로 인증·네트워크 경계를 정하고, [실습](../../../labs/azure-api-management/mcp-rest-and-upstream/index.md)으로 선택한 경로를 재현하세요.
