---
title: MCP backend 호스팅과 예제 서버 참고
description: 자체 MCP 서버의 실행 환경·private network와 예제 서버별 인증 조건을 비교하고, APIM SKU 선택과 배포 절차를 연결합니다.
document_type: research
topic_order: 2
redirect_from:
  - research/azure-api-management/mcp-authentication-options/index.md
services: [azure-architecture, azure-api-management, azure-container-apps, azure-app-service, azure-functions, azure-kubernetes-service, microsoft-foundry, microsoft-entra-id]
technologies: [mcp, azure-cli, bicep, python]
tags: [design, evaluate, ai-agents, networking]
status: current
verification_status: needs-review
sources_checked_at: 2026-09-13
published_at: 2026-09-12
official_sources:
  - title: What is Toolbox in Foundry?
    url: https://learn.microsoft.com/azure/foundry/agents/concepts/toolbox-overview
  - title: Create and manage a toolbox in Foundry
    url: https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox
  - title: Network isolation for a toolbox in Microsoft Foundry
    url: https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox-network-isolation
  - title: Choose an Azure service for your MCP server
    url: https://learn.microsoft.com/azure/container-apps/mcp-choosing-azure-service
  - title: Configure App Service built-in MCP (preview)
    url: https://learn.microsoft.com/azure/app-service/configure-mcp-built-in
  - title: Versioning and Compatibility
    url: https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning
  - title: Authorization
    url: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
  - title: MCP Python SDK
    url: https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/README.md
  - title: Remote builds support with Azure Container Registry
    url: https://learn.microsoft.com/azure/developer/azure-developer-cli/remote-builds
  - title: Azure Developer CLI schema reference
    url: https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-schema
  - title: Customize your Azure Developer CLI workflows using command and event hooks
    url: https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-extensibility
  - title: About MCP servers in Azure API Management
    url: https://learn.microsoft.com/azure/api-management/mcp-server-overview
  - title: Expose REST API in API Management as an MCP server
    url: https://learn.microsoft.com/azure/api-management/export-rest-mcp-server
  - title: Manage MCP servers programmatically in API Management
    url: https://learn.microsoft.com/azure/api-management/manage-mcp-servers-rest-api
  - title: Feature-based comparison of the Azure API Management tiers
    url: https://learn.microsoft.com/azure/api-management/api-management-features
  - title: Use a virtual network to secure inbound or outbound traffic for Azure API Management
    url: https://learn.microsoft.com/azure/api-management/virtual-network-concepts
  - title: Microsoft identity platform and OAuth 2.0 On-Behalf-Of flow
    url: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow
  - title: Secure applications and APIs by validating claims
    url: https://learn.microsoft.com/entra/identity-platform/claims-validation
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
  - title: Use private endpoints for Azure App Service apps
    url: https://learn.microsoft.com/azure/app-service/overview-private-endpoint
  - title: Configure built-in MCP server authorization (Preview)
    url: https://learn.microsoft.com/azure/app-service/configure-authentication-mcp
  - title: Self-hosted remote MCP server on Azure Functions (public preview)
    url: https://learn.microsoft.com/azure/azure-functions/self-hosted-mcp-servers
  - title: Azure Functions networking options
    url: https://learn.microsoft.com/azure/azure-functions/functions-networking-options
---

# MCP backend 호스팅과 예제 서버 참고

**자체 MCP 서버의 실행 환경을 선택하거나 sample의 서버별 차이를 확인할 때** 읽는 자료입니다. 관리·도구 통합·인증의 전체 구성은 [대표 가이드](../index.md)를 사용합니다.

| 선택할 것 | 읽을 부분 |
|---|---|
| 예제 서버의 실행·인증 방식 | 서버별 인증 차이와 고정 버전 조건 |
| 자체 MCP 코드의 실행 환경 | Azure 호스팅 옵션과 구성 패턴 |
| Private APIM의 SKU | APIM SKU 선택 |
| 실제 배포·호출 | [Sample walkthrough](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/walkthrough.md) |

## MCP protocol과 패키지 버전

“MCP 2.0”만으로는 어떤 버전을 사용하는지 알 수 없습니다. protocol revision, SDK, 서버 패키지를 각각 지정해야 연결 방식을 비교할 수 있습니다.

| 구분 | 비교에 사용한 값 | 의미 |
|---|---|---|
| MCP protocol revision | `2026-07-28` | 날짜로 구분하는 MCP 사양 |
| Python SDK | `mcp==2.2.0` | SDK 패키지 버전 |
| 메시지 형식 | JSON-RPC `2.0` | MCP 요청·응답의 RPC 형식 |
| 인증 표준 | OAuth `2.0` / `2.1` | access token 발급과 사용에 관한 표준 |
| Azure MCP Server | `2.0.5` | Azure MCP 서버 패키지 버전 |

Python SDK v2는 최신 사양과 이전 revision을 함께 지원합니다. SDK를 업데이트해도 연결한 서버가 사용하는 protocol revision까지 바뀌지는 않습니다. Learn MCP 연결에서 확인한 revision은 `2025-06-18`이며, Azure MCP 패키지 `2.0.5` 역시 “MCP protocol 2.0”을 뜻하지 않습니다.

`2026-07-28` 사양은 `server/discover`와 요청별 metadata를 사용하며 protocol session과 GET stream을 제거했습니다. 이전 revision의 연결에서는 `initialize`와 해당 revision의 세션 규칙을 사용합니다. HTTP POST에 대한 SSE 응답은 최신 사양에도 있으므로 “SSE를 모두 제거했다”는 설명은 맞지 않습니다. 자세한 차이는 [versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)과 [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)에 있습니다.

MCP의 `server/discover`는 서버 기능을 확인하는 요청입니다. OAuth의 protected-resource metadata(PRM)는 클라이언트가 사용할 authorization server와 scope를 알려주는 문서로, 목적이 다릅니다.

## Sample에 사용한 MCP 서버의 인증 차이

아래 표는 sample에서 사용하는 고정 버전과 연결 방식입니다.

| MCP 서버 | 연결 방식 | 사용하는 자격 증명과 권한 |
|---|---|---|
| Azure MCP `2.0.5` | 로컬 stdio 또는 원격 HTTP | 로컬에서는 Azure 자격 증명, 원격에서는 Entra access token과 OBO 또는 호스팅 환경의 자격 증명 |
| AKS MCP `v0.0.20` | **로컬 stdio만 지원** | 로컬 사용자의 Azure CLI 로그인과 kubeconfig, Azure·Kubernetes RBAC |
| GitHub MCP | GitHub hosted 또는 로컬 서버 | GitHub OAuth 또는 PAT, 해당 GitHub 사용자의 repository 권한 |
| Microsoft Learn MCP | 공개 HTTP endpoint | 인증 없이 공개 문서 검색·조회 |

![로컬 개발 클라이언트가 Azure와 AKS에는 로컬 사용자 자격 증명을, GitHub에는 GitHub 자격 증명을 사용하고 Learn에는 토큰을 보내지 않는 구조](images/local-upstreams.svg)

### Azure MCP의 OBO와 read-only 설정

Azure MCP `2.0.5`의 incoming delegated scope는 `Mcp.Tools.ReadWrite`입니다. `--read-only`를 사용해도 scope 이름은 바뀌지 않습니다. 도구의 읽기 전용 설정과 사용자의 Azure RBAC를 함께 적용합니다.

`--outgoing-auth-strategy UseOnBehalfOf`는 로그인한 사용자 대신 Azure 서비스를 호출합니다. `UseHostingEnvironmentIdentity`는 서버가 실행되는 환경의 자격 증명을 사용합니다. 이때 로컬에서는 Azure CLI 사용자, Azure에서는 managed identity가 사용될 수 있으므로 사용자별 권한이 필요한 서비스에는 OBO 여부를 명확히 설정해야 합니다.

연결 예제는 Azure MCP `2.0.5`와 Python SDK `2.2.0`을 기준으로 합니다. 서버를 업그레이드할 때는 패키지 버전뿐 아니라 protocol revision, 요구 scope, 사용할 도구도 함께 확인합니다.

### AKS MCP v0.0.20의 지원 범위

[v0.0.20 release](https://github.com/Azure/aks-mcp/releases/tag/v0.0.20)는 HTTP/SSE, browser-facing OAuth/OBO, token forwarding, container image·Helm·원격 배포를 제거했습니다. MCP 클라이언트가 로컬 binary를 stdio subprocess로 실행하는 방식만 지원합니다. `--access-level readonly`는 도구를 제한하는 옵션이며 Azure·Kubernetes RBAC를 대체하지 않습니다.

확인일의 [AKS Learn 문서](https://learn.microsoft.com/azure/aks/aks-model-context-protocol-server)에는 아직 원격 모드와 `--transport` 예제가 남아 있습니다. **v0.0.20에는 release의 로컬 stdio 구성을 적용합니다.** 해당 버전을 APIM 뒤에 원격 배포하는 예제로 사용하지 않습니다.

### GitHub OAuth와 익명 Learn 호출

Entra ID로 내부 MCP를 보호해도 GitHub API를 호출할 때는 GitHub OAuth 또는 PAT가 필요합니다. Entra OBO로 GitHub access token이 발급되는 것은 아닙니다.

Learn은 익명으로 호출합니다. APIM에서 Entra 인증을 추가하더라도 backend Learn 요청에는 incoming `Authorization` header를 전달하지 않습니다. 이 구성은 내부 사용자의 APIM 접근을 제한하는 것이며, 공개 GitHub·Learn endpoint 자체를 private endpoint로 바꾸지는 않습니다.

## Azure 호스팅 옵션

| 선택지 | 적합한 상황 | 내부망 접속 | 인증·OBO 구성 |
|---|---|---|---|
| Container Apps | 공식 Azure MCP나 자체 MCP를 container로 운영 | Internal environment와 private DNS | 앱의 JWT 검증·Container Apps authentication, 서버의 OBO |
| App Service | 기존 웹 앱 운영 방식으로 자체 MCP 배포 | Inbound private endpoint, outbound VNet integration | Easy Auth 또는 앱 middleware, 별도 OBO 구현 |
| Functions Flex Consumption | SDK 기반 stateless MCP 호스팅 | Private endpoint와 VNet integration | Built-in auth 또는 서버 코드, 별도 OBO 구현 |

APIM은 위 실행 환경에 둔 MCP를 관리하거나 REST operation을 MCP tool로 제공합니다. 로컬 PC의 private 접속에는 VPN/ExpressRoute 경로와 DNS를, HTTP 요청에는 Entra 인증을 구성합니다.

Container Apps dynamic sessions는 별도 선택지입니다. Platform이 제공하는 Python·shell 실행 도구와 session별 격리를 사용하며, 직접 작성한 MCP 서버를 배포하는 standalone Container Apps와는 다릅니다.

### 여러 도구를 묶어 제공할 때

Toolbox는 MCP·OpenAPI·IQ 도구를 하나의 endpoint에 구성하고 connection 인증·version을 관리합니다. 기능과 선택 기준은 [대표 가이드의 Toolbox 장](../index.md#3-toolbox-iq-mcp-endpoint), 구성 명령은 [Toolbox sample](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-architecture/mcp-configuration/samples/toolbox)에 정리합니다.

### APIM 없이 REST API를 변환하는 옵션

App Service built-in MCP **preview**는 **Basic 이상 전용 tier**에서 기존 API의 OpenAPI **3.0.x** 명세를 읽어 operation을 MCP tool로 노출합니다. OpenAPI 3.1.x는 지원하지 않습니다. Foundry Toolbox의 OpenAPI tool도 REST API를 toolset에 포함할 수 있습니다. 따라서 REST-to-MCP가 필요하다는 이유만으로 APIM을 필수로 선택할 필요는 없습니다.

## 구성 패턴과 적용 조건

### 1. Container Apps에서 Azure MCP OBO 사용

![내부 Container Apps의 Azure MCP가 Entra 사용자 토큰을 검증하고 관리 ID 기반 federated credential로 confidential client를 인증한 뒤 별도 ARM 토큰을 얻는 구조](images/container-apps-obo.svg)

요청은 다음 순서로 처리됩니다.

1. 로컬 클라이언트가 Azure MCP API를 대상으로 access token을 받습니다.
2. Container Apps authentication이 허용 client ID를 검사하고, Azure MCP가 tenant·audience·scope를 검사합니다.
3. Azure MCP가 managed identity와 FIC로 confidential client를 인증하고, 사용자 token을 OBO user assertion으로 제출합니다.
4. ARM용 access token으로 Azure 리소스를 조회합니다. 조회 범위는 사용자의 Azure RBAC에 따릅니다.

Managed identity와 FIC는 이 흐름에서 **서버 앱의 인증 수단**입니다. ARM의 리소스 권한은 OBO를 통해 전달한 사용자에게 적용됩니다.

Native Azure MCP의 허용 클라이언트는 Container Apps `authConfigs`의 `identityProviders.azureActiveDirectory.validation.defaultAuthorizationPolicy.allowedApplications`로 제한합니다. 앱 등록의 `preAuthorizedApplications`는 consent 설정이므로 이 ACL을 대신하지 않습니다.

Internal Container Apps 환경의 앱 ingress `external: true`는 VNet에서 앱으로 접근할 수 있게 합니다. 인터넷 공개 설정이 아닙니다. 환경의 private DNS와 개발 PC의 DNS 전달 경로도 구성해야 합니다.

### 2. APIM에서 REST API를 MCP tool로 제공

![Entra로 보호된 APIM이 기존 REST operation을 native MCP tool에 연결하고 실제 REST 백엔드를 호출하는 구조](images/apim-rest-tools.svg)

APIM이 관리하는 REST API operation을 선택하면 MCP tool로 노출할 수 있습니다. 별도 MCP 서버 프로세스 없이 APIM이 MCP 요청을 REST 호출로 연결합니다.

샘플은 가상 inventory REST API를 사용합니다. [Sample walkthrough](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/walkthrough.md)에서는 inventory를 REST로 조회하고, MCP 도구 목록을 확인한 뒤 같은 항목을 tool로 조회합니다. Tool 리소스의 **`operationId`가 실제 REST operation의 리소스 ID를 가리켜야** 이 호출이 연결됩니다.

이 기능 자체가 REST backend의 인증을 OBO로 바꾸지는 않습니다. 업무 API를 연결할 때는 그 API의 access token, managed identity 또는 다른 인증 방식을 별도로 구성합니다. Python MCP의 resource group OBO 조회는 이 REST inventory 경로와 별개의 MCP 도구입니다.

### 3. APIM으로 기존 Learn MCP 프록시

![APIM이 Entra 토큰을 검증한 뒤 Authorization을 제거하고 기존 공개 Learn MCP 서버에 연결하는 구조](images/apim-existing-mcp.svg)

이 방식은 기존 MCP 서버가 이미 제공하는 도구를 APIM을 통해 호출합니다. REST-to-MCP의 `operationId` 연결과 달리, MCP API에 **backend 리소스, `backendId`, `message` endpoint**를 연결합니다. Learn 요청에서는 APIM이 incoming Entra token을 검사한 뒤 `Authorization` header를 제거합니다.

APIM의 `2025-09-01-preview` 관리 문서·Bicep 타입과 실제 API·공식 AI-Gateway 샘플 사이에는 차이가 있습니다. 문서의 endpoint 배열 대신 실제 구성은 `message`를 key로 둔 `endpoints` object와 `backendId`를 사용합니다. 이 차이는 [사례 기록](../validation/index.md)에 정리했으며, 관리 API 버전을 바꿀 때 다시 확인해야 합니다.

### 4. App Service 대안

![App Service private endpoint로 들어온 요청을 Easy Auth 또는 JWT middleware에서 검증하고 별도 confidential middle tier에서 OBO를 수행하는 대안](images/app-service-alternative.svg)

기존 App Service 운영 환경에서 자체 MCP 서버를 웹 앱으로 제공할 때 고려할 수 있습니다.

Private endpoint는 앱으로 들어오는 요청에 사용하고, VNet integration은 앱이 private backend를 호출할 때 사용합니다. Private endpoint를 추가하는 것만으로 public access가 비활성화되지는 않습니다. 앱의 public access 설정과 SCM/Kudu용 private DNS도 함께 구성해야 합니다.

App Service의 MCP authorization과 PRM 지원은 확인일 기준 **preview**입니다. Easy Auth를 적용하더라도 ARM 등 다른 API를 사용자 권한으로 호출하려면 앱의 OBO 구현과 delegated permission·consent가 필요합니다.

### 5. Functions Flex Consumption 대안

![Functions Flex Consumption에서 private endpoint와 VNet integration을 사용하고 stateless SDK MCP와 인증·위임 코드를 분리하는 대안](images/functions-alternative.svg)

SDK 기반 MCP 서버를 self-hosted/custom-handler 방식으로 호스팅하는 옵션입니다. [공식 문서](https://learn.microsoft.com/azure/azure-functions/self-hosted-mcp-servers)의 지원 범위는 **public preview, Flex Consumption, stateless Streamable HTTP**입니다.

Flex Consumption은 private endpoint와 VNet integration을 지원하지만 legacy Consumption은 같은 네트워크 기능을 제공하지 않습니다. Function key는 사용자 access token이 아니므로, Entra 사용자 인증과 OBO가 필요하다면 built-in auth 또는 서버 코드에서 별도로 처리해야 합니다.

## azd 기반 실습 구성

[Sample walkthrough](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/walkthrough.md)에서 Entra 준비 → `azd` preview·배포 → 내부망 연결 → 도구·OBO 호출 → 정리를 순서대로 실행합니다. Sample은 Container Apps와 APIM Developer를 사용하며 ACR remote build로 image를 만듭니다. 도구 버전·비용·정리 명령은 해당 sample에서 확인합니다.

## APIM SKU 선택

다음은 [MCP 지원 tier](https://learn.microsoft.com/azure/api-management/mcp-server-overview#availability)에서 private 구성을 선택할 때의 기준입니다.

| SKU | Private 구성 | 적용 조건 |
|---|---|---|
| Developer | Internal VNet injection으로 내부 client·backend 연결 | 비운영·평가용, SLA 없음 |
| Basic / Standard classic | Inbound private endpoint | VNet injection·private backend 연결 기능은 지원하지 않음 |
| Basic v2 | Public gateway | Inbound private endpoint·VNet 연결 기능은 지원하지 않음 |
| Standard v2 | Inbound private endpoint + outbound VNet integration | 내부 client와 private backend 경로를 각각 구성 |
| Premium classic | Internal/external VNet injection | 배포 모드와 network 규칙에 맞춰 연결 |
| Premium v2 | Gateway VNet injection 또는 private endpoint·outbound integration | 선택한 networking model에 맞춰 구성 |

세부 옵션은 [기능 비교표](https://learn.microsoft.com/azure/api-management/api-management-features)와 [VNet 구성 문서](https://learn.microsoft.com/azure/api-management/virtual-network-concepts)를 따릅니다. Developer portal의 “Entra integration” 항목을 API의 JWT 검증 정책 지원 여부와 혼동하지 않습니다.

## OBO에 필요한 token과 권한

OBO의 입력은 중간 MCP API를 대상으로 발급한 **사용자 access token**입니다. v2 token의 `aud`는 중간 API의 client ID(GUID)여야 하며, ARM용 token이나 app-only token을 입력으로 사용할 수 없습니다.

중간 API는 confidential client로 인증한 뒤 별도의 ARM access token을 받습니다. API 앱의 delegated permission·consent와 사용자의 Azure RBAC가 모두 필요합니다. Scope URI, JWT의 `scp`, PRM의 `resource` URL은 용도가 다른 값입니다.

실제 앱 등록과 APIM 정책은 [Entra 인증 가이드](../authentication/index.md)에 있습니다. 다른 IDE나 사용자를 연결할 때는 client ID·redirect URI·consent·Conditional Access와 해당 사용자의 RBAC를 적용해 같은 호출 순서로 확인할 수 있습니다.
