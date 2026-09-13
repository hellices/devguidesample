---
title: Azure MCP 구성 — APIM·Toolbox·IQ의 활용과 선택 기준
description: 공통 정책 관리에는 APIM, 도구 집합 공유에는 Toolbox, 기업 데이터 연결에는 IQ를 사용하는 이유와 조합 기준을 설명합니다.
document_type: guide
redirect_from:
  - guides/azure-architecture/mcp-configuration/index.md
  - labs/azure-architecture/mcp-configuration/index.md
  - labs/azure-api-management/mcp-rest-and-upstream/index.md
services: [azure-architecture, azure-api-management, microsoft-foundry, microsoft-entra-id, azure-container-apps, azure-ai-search]
technologies: [mcp, azure-cli]
tags: [design, secure, ai-agents, identity]
status: current
verification_status: verified
sources_checked_at: 2026-09-14
official_sources:
  - title: AI gateway in Azure API Management
    url: https://learn.microsoft.com/azure/api-management/genai-gateway-capabilities
  - title: About MCP servers in Azure API Management
    url: https://learn.microsoft.com/azure/api-management/mcp-server-overview
  - title: Expose and govern an existing MCP server
    url: https://learn.microsoft.com/azure/api-management/expose-existing-mcp-server
  - title: Expose REST API in API Management as an MCP server
    url: https://learn.microsoft.com/azure/api-management/export-rest-mcp-server
  - title: Secure access to MCP servers in API Management
    url: https://learn.microsoft.com/azure/api-management/secure-mcp-servers
  - title: About API credentials and credential manager
    url: https://learn.microsoft.com/azure/api-management/credentials-overview
  - title: Validate Microsoft Entra token
    url: https://learn.microsoft.com/azure/api-management/validate-azure-ad-token-policy
  - title: Secure a Model Context Protocol (MCP) server with Microsoft Entra ID
    url: https://learn.microsoft.com/entra/agent-id/secure-mcp-server-with-entra-id
  - title: Microsoft identity platform and OAuth 2.0 authorization code flow
    url: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-auth-code-flow
  - title: How to integrate Azure API Management with Azure Application Insights
    url: https://learn.microsoft.com/azure/api-management/api-management-howto-app-insights
  - title: Feature-based comparison of the Azure API Management tiers
    url: https://learn.microsoft.com/azure/api-management/api-management-features
  - title: Use a virtual network to secure inbound or outbound traffic for Azure API Management
    url: https://learn.microsoft.com/azure/api-management/virtual-network-concepts
  - title: What is Toolbox in Foundry?
    url: https://learn.microsoft.com/azure/foundry/agents/concepts/toolbox-overview
  - title: Create and manage a toolbox in Foundry
    url: https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox
  - title: How toolbox authentication works in Microsoft Foundry
    url: https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-authentication
  - title: Enable tool search in a toolbox
    url: https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-search
  - title: Network isolation for a toolbox in Microsoft Foundry
    url: https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox-network-isolation
  - title: What is Foundry IQ?
    url: https://learn.microsoft.com/azure/foundry/agents/concepts/what-is-foundry-iq
  - title: Connect a Foundry IQ knowledge base to Foundry Agent Service
    url: https://learn.microsoft.com/azure/foundry/agents/how-to/foundry-iq-connect
  - title: "Quickstart: Add a Foundry IQ knowledge base to a hosted agent with a toolbox"
    url: https://learn.microsoft.com/azure/foundry/agents/quickstarts/quickstart-foundry-iq-hosted-agent
  - title: Connect agents to Microsoft 365 with Work IQ (preview)
    url: https://learn.microsoft.com/azure/foundry/agents/how-to/tools/work-iq
  - title: Connect agents to Microsoft Fabric with Fabric IQ (preview)
    url: https://learn.microsoft.com/azure/foundry/agents/how-to/tools/fabric-iq
  - title: Microsoft identity platform and OAuth 2.0 On-Behalf-Of flow
    url: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow
  - title: Choose an Azure service for your MCP server
    url: https://learn.microsoft.com/azure/container-apps/mcp-choosing-azure-service
  - title: Versioning
    url: https://modelcontextprotocol.io/docs/2026-07-28/learn/versioning
  - title: Key Changes
    url: https://modelcontextprotocol.io/specification/2026-07-28/changelog
  - title: Overview
    url: https://modelcontextprotocol.io/specification/2026-07-28/basic
  - title: Streamable HTTP
    url: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
  - title: Versioning and Compatibility
    url: https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning
  - title: Discovery
    url: https://modelcontextprotocol.io/specification/2026-07-28/server/discover
  - title: Lifecycle
    url: https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle
  - title: Transports
    url: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
  - title: Authorization
    url: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
  - title: Authorization Server Discovery
    url: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/authorization-server-discovery
  - title: Client Registration
    url: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration
  - title: Authorization Security Considerations
    url: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations
last_verified: 2026-09-14
review_cycle_days: 90
applies_to:
  - Azure API Management MCP endpoints
  - Microsoft Foundry Toolbox and IQ tool connections
  - Microsoft Entra ID authorization
related_cases:
  - validation/index.md
---

# Azure MCP 구성 — APIM·Toolbox·IQ의 활용과 선택 기준

**Azure API Management(APIM)**는 여러 API와 MCP 서버에 공통 접근 정책을 적용하는 API 관리 서비스입니다. 개발 도구가 사용할 endpoint를 제공하고 인증·인가, 호출 제한, backend routing과 요청 기록을 중앙에서 관리합니다.

**Microsoft Foundry Toolbox**는 MCP·REST API·IQ 도구를 업무에 필요한 toolset으로 묶어 **하나의 MCP endpoint**로 제공하는 서비스입니다. 도구별 connection 인증, version, 검색과 정책을 관리하므로 여러 client가 같은 도구 집합을 재사용할 수 있습니다.

## 소개하는 서비스

| 서비스 | 사용하는 이유 | 핵심 기능 | 공식 문서 |
|---|---|---|---|
| **APIM / AI gateway** | 여러 팀의 API·MCP에 조직 공통 운영 정책을 적용 | 인증·인가, 호출 제한, routing, 요청 기록, REST-to-MCP | [AI gateway](https://learn.microsoft.com/azure/api-management/genai-gateway-capabilities), [MCP 연결](https://learn.microsoft.com/azure/api-management/expose-existing-mcp-server) |
| **Foundry Toolbox** | Client마다 반복하는 도구 연결·인증·변경 관리를 줄이고 도구 집합 공유 | 단일 MCP endpoint, connection, version, Tool search, 정책·관측 | [Toolbox 개요](https://learn.microsoft.com/azure/foundry/agents/concepts/toolbox-overview), [Tool search](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-search) |
| **Work IQ·Fabric IQ·Foundry IQ** | AI가 조직의 업무 context와 데이터·지식을 활용 | Microsoft 365, Fabric 의미 모델, 기업 문서 knowledge base 연결 | [Work IQ](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/work-iq), [Fabric IQ](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/fabric-iq), [Foundry IQ](https://learn.microsoft.com/azure/foundry/agents/concepts/what-is-foundry-iq) |

### 이 문서의 범위와 읽는 순서

대상은 **HTTP 기반 MCP tool의 제공·호출, Entra 인증, 사용자 위임과 내부망 접속**입니다. `tools/list`와 `tools/call`을 중심으로 설명합니다.

| 목적 | 읽을 곳 | 결정하거나 완성할 것 |
|---|---|---|
| 솔루션 선택 | 서비스 표 → 1–3장 → [6장](#6) | APIM 관리, Toolbox 통합 또는 두 서비스 조합 선택 |
| 접근·권한 설계 | [4장](#4) → [인증 상세](authentication/index.md) | 누가 접속하고 누구의 권한으로 도구를 실행할지 결정 |
| 자체 MCP 서버 배포 | [5장](#5-mcp) → [호스팅 참고](hosting-reference/index.md) | 실행 환경·private network·배포 방식 선택 |
| 명령 실행과 결과 비교 | [7장](#7) → sample·[실행 사례](validation/index.md) | 배포·도구 호출·인가 확인·리소스 정리 |

SDK나 gateway의 wire 동작을 구현·진단할 때는 Appendix를 읽습니다.

## 1. APIM / AI gateway로 MCP 접근 관리

APIM은 client와 backend 사이에서 요청을 처리하는 **API gateway와 관리 기능**을 제공합니다. 여러 팀이 운영하는 API·MCP 서버를 등록하고, 인증·접근 제어·호출 제한·routing 정책을 공통 방식으로 적용할 수 있습니다.

[AI gateway](https://learn.microsoft.com/azure/api-management/genai-gateway-capabilities)는 이 APIM gateway를 AI 모델·MCP 도구·agent API에 활용하는 기능입니다. 이 문서에서는 **MCP에 대한 조직 공통 정책과 기존 API의 도구화**에 집중합니다.

### MCP 운영에서 제공하는 기능

| 기능 | 활용 상황 |
|---|---|
| **공유 MCP 접점** | 개발 도구와 애플리케이션에 승인된 gateway 주소 제공 |
| **인증·인가 정책** | Entra token과 scope·허용 client를 검사해 업무별 접근 통제 |
| **호출 제한·routing** | 사용자·애플리케이션별 사용량을 관리하고 요청을 지정한 backend로 전달 |
| **사내·타사 서비스 연결** | Azure뿐 아니라 호환되는 외부 MCP에 backend별 인증과 정책 적용 |
| **REST-to-MCP** | 운영 중인 REST operation을 MCP tool로 제공 |
| **운영 관측** | 요청·응답 상태, latency, 정책 차단과 correlation 정보를 수집 |

기존 API 관리 체계를 MCP까지 확장하거나, 여러 팀의 도구 접근을 같은 정책으로 운영하려는 경우에 적합합니다.

[![MCP client가 중앙의 APIM으로 요청하고 APIM이 사내 MCP·타사 MCP·REST API로 전달하는 단순한 요청 흐름](images/mcp-reference-architecture.svg)](images/mcp-reference-architecture.svg)

### 기존 MCP와 REST API

- **기존 MCP:** APIM에 remote MCP endpoint를 연결하고 정책을 적용합니다.
- **기존 REST API:** 선택한 REST operation을 MCP tool로 제공합니다. 별도 MCP 업무 서버 코드를 작성하지 않고 기존 API를 도구로 사용할 수 있습니다.

APIM에서는 API/MCP별 endpoint와 정책을 관리합니다. 업무용 도구 집합을 하나의 consumer endpoint로 구성하는 방법은 Toolbox 장에서 설명합니다.

### 운영 정책을 한곳에 모으는 이유

Client별로 인증과 호출 제한을 반복 구현하는 대신 gateway에서 운영 기준을 적용하고, 요청 기록을 backend 로그와 연결해 장애·접근 문제를 추적할 수 있습니다. 감사가 필요하면 수집·보관·접근 통제까지 설계합니다. [Application Insights의 성능 telemetry만으로 전수 감사를 보장하지는 않습니다](https://learn.microsoft.com/azure/api-management/api-management-howto-app-insights#performance-implications-and-log-sampling).

## 2. IQ 도구와 MCP는 어떻게 연결되는가

IQ는 **업무 데이터·지식을 제공하는 서비스**이며, MCP는 연결 방식입니다. AI의 답변에 사내 문서, Microsoft 365 업무 이력, Fabric의 지표·의미 모델이 필요할 때 해당 IQ를 연결합니다. 데이터 서비스가 관리하는 context와 권한을 활용하면서 필요한 기능을 도구로 사용할 수 있습니다.

| IQ | 제공하는 기능 | MCP·Toolbox 연결 |
|---|---|---|
| **Work IQ** | Microsoft 365의 메일·회의·파일·채팅 등 업무 context | Work IQ Chat은 A2A를 사용하며 해당 경로의 OBO를 명시. 다른 선택 항목은 MCP endpoint 사용. Toolbox는 선택한 도구를 자신의 MCP endpoint로 제공 |
| **Fabric IQ** | Ontology, Power BI semantic model, Fabric data agent를 통한 업무 데이터 조회·추론 | Fabric item 유형별 MCP endpoint 제공. 연결 identity와 인증 방식은 item·connection 경로에 따라 다름 |
| **Foundry IQ** | Azure AI Search 기반 knowledge base에서 여러 source를 검색하고 근거 있는 결과 반환 | Knowledge base의 MCP endpoint를 Toolbox connection으로 연결하는 [공식 예제](https://learn.microsoft.com/azure/foundry/agents/quickstarts/quickstart-foundry-iq-hosted-agent#step-3-provision-azure-resources-and-the-knowledge-base) 제공 |

| 주의점 | 확인 |
|---|---|
| 지원 상태 | Work IQ·Fabric IQ 연결은 preview 포함. Foundry IQ 일부는 GA지만 [MCP 연결 예제](https://learn.microsoft.com/azure/foundry/agents/how-to/foundry-iq-connect)는 preview API 사용 |
| 데이터 권한 | Source ACL·사용자 token 전달 설정 확인. MCP 연결 자체가 데이터 권한 검사를 완성하지 않음 |
| Identity | 위 Foundry IQ 예제는 `agentic-identity`이며 사용자 OBO 예제가 아님 |
| 운영 조건 | 서비스별 비용·라이선스·데이터 처리 위치 확인 |

## 3. Toolbox로 IQ와 MCP를 하나의 endpoint에 구성

**Toolbox는 Microsoft Foundry에서 도구 집합을 만들고 공유하는 관리형 서비스**입니다. 여러 MCP 서버·OpenAPI·IQ 도구를 선택해 하나의 toolset으로 구성하고, client에는 하나의 MCP endpoint를 제공합니다.

예를 들어 기업 문서 검색, 업무 REST API, Microsoft 365 도구를 사용하는 assistant를 만들 때 각 client에 서버 주소와 인증 로직을 반복해서 구성하는 대신 Toolbox에 connection을 관리할 수 있습니다. 같은 toolset을 여러 애플리케이션에서 재사용하며, Foundry 밖의 MCP-compatible client에서도 연결할 수 있습니다.

### Toolbox의 핵심 기능

| 기능 | 제공하는 내용 |
|---|---|
| **도구 구성·공유** | 필요한 MCP·OpenAPI·IQ 도구를 선택해 업무별 toolset으로 제공 |
| **단일 MCP endpoint** | Client가 도구별 endpoint 대신 Toolbox를 통해 목록을 조회하고 호출 |
| **Connection 인증** | 도구별 사용자 OAuth, 서비스 identity, key와 token lifecycle 관리 |
| **Version 관리** | 도구 집합의 새 version을 확인하고 default version으로 전환 |
| **Tool search** | 요청에 관련된 도구 정의를 검색해 model context에 필요한 도구만 제공 |
| **정책·관측** | Toolset의 인증·인가, guardrail과 observability를 중앙에서 관리 |

[![하나의 Toolbox MCP endpoint가 Work IQ·Fabric IQ·Foundry IQ 및 사내·타사 MCP 도구에 연결하며 downstream protocol은 MCP 또는 A2A로 구분되는 구성](images/toolbox-iq-mcp.svg)](images/toolbox-iq-mcp.svg)

Microsoft Learn은 이 기능을 [Build·Discover·Consume·Govern](https://learn.microsoft.com/azure/foundry/agents/concepts/toolbox-overview)으로 설명합니다. 도구 통합과 인증·version 관리를 먼저 구성하고, 도구가 많아지면 Tool search로 탐색을 최적화할 수 있습니다.

### Tool search와 토큰 절감 데모

도구가 늘어날수록 모든 도구 정의를 매번 model context에 넣는 부담이 커집니다. **Tool search는 필요한 도구를 찾아 정의를 제공**하고, 자주 쓰는 도구는 pin·auto-pin으로 노출해 검색 부담을 줄입니다.

Microsoft Learn의 [Toolbox 개요](https://learn.microsoft.com/azure/foundry/agents/concepts/toolbox-overview)에 삽입된 **[Toolboxes in Microsoft Foundry 영상](https://www.youtube.com/watch?v=7bBvmifVMew)**에서 이 차이를 보여줍니다.

| 영상 위치 | 확인할 내용 |
|---|---|
| [3:22부터](https://www.youtube.com/watch?v=7bBvmifVMew&t=202s) | Work IQ 도구 추가와 connection 인증 |
| [6:05부터](https://www.youtube.com/watch?v=7bBvmifVMew&t=365s) | 전체 도구 정의가 context를 차지하는 문제와 필요한 도구만 찾는 방식 |
| [8:34–9:13](https://www.youtube.com/watch?v=7bBvmifVMew&t=514s) | 같은 상품 catalog 질문에 대해 발표자가 제시한 input token 비교 |

| 해당 데모 | Input tokens |
|---|---:|
| 전체 도구 정의를 사용하는 비교 대상 | 4,676 |
| 필요한 도구를 검색해 사용하는 비교 대상 | 467 |

영상의 **상품 catalog 조회 시연에서는 input tokens가 약 90% 감소**했습니다. 결과는 model·도구·질문·cache 조건에 따라 달라집니다.

- 같은 model·도구·질문 조건에서 업무 완료까지의 input/output tokens, cache, 검색 횟수, latency·재시도를 비교합니다.
- 설정: [Tool search 공식 문서](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-search) · [Toolbox sample](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-architecture/mcp-configuration/samples/toolbox)

## 4. 접근과 사용자 권한을 통제하는 이유

MCP 도구는 실제 업무 데이터와 API를 사용합니다. **누가 MCP에 접속할 수 있는지**와 **도구가 누구의 권한으로 실행되는지**를 나눠 설계합니다.

| 통제 지점 | 필요한 이유 | 사용하는 기능 |
|---|---|---|
| **APIM의 MCP 접점** | 승인된 사용자·client만 업무 도구에 접근 | Entra 로그인, PRM 제공, JWT·scope 정책 |
| **Toolbox의 connection** | 여러 client가 도구별 인증을 반복 구현하지 않고 재사용 | 사용자 OAuth, 서비스 identity, credential·token lifecycle 관리 |
| **데이터 API 접근** | 사용자가 원래 가진 데이터 권한을 도구 호출에도 적용 | 사용자 위임이 필요한 중간 MCP API의 Entra OBO 또는 지원되는 사용자 connection |

**OAuth + PKCE는 client와 Entra**, **PRM·token 검증은 APIM/MCP Server**에 적용합니다. 앱 등록·claim·정책·완료 기준은 [인증 상세](authentication/index.md), 실제 명령과 결과는 [인증 확인 절차](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/authentication-checks.md)와 [실행 사례](validation/index.md#oauth)에서 설명합니다.

## 5. MCP 서버를 준비하는 방법

| 방법 | 사용할 때 | 구현·확인 위치 |
|---|---|---|
| SDK로 MCP 서버 작성 | 자체 업무 로직과 데이터 접근을 tool로 구현 | Container Apps·App Service·Functions·AKS 등에서 실행. [Azure hosting 비교](https://learn.microsoft.com/azure/container-apps/mcp-choosing-azure-service) |
| 기존 REST API 변환 | 이미 운영하는 API operation을 tool로 제공 | APIM REST-to-MCP 또는 지원되는 Toolbox OpenAPI 도구 구성 |
| 기존 remote MCP 연결 | 사내·타사에서 제공하는 도구 재사용 | 원래 endpoint의 protocol·인증·network 조건을 확인해 직접 또는 gateway/Toolbox를 통해 연결 |

- 기존 remote MCP는 Azure에 다시 배포하지 않고 연결할 수 있습니다.
- 서버 실행 위치, toolset 통합, 공통 정책 적용 위치는 따로 선택합니다.

## 6. 엔터프라이즈 구성에 적용할 때의 판단

**설계 제안**이며 제품 지원 판정과 구분합니다.

| 요구사항 | 우선 검토 | 선택하는 이유 |
|---|---|---|
| 여러 MCP·IQ를 한 주소로 제공 | Toolbox 단독 | 도구 연결·인증·version을 한곳에서 관리 |
| 여러 팀과 기존 API의 공통 통제 | APIM | 승인 endpoint와 운영 정책을 MCP에도 공통 적용 |
| 조직의 업무 데이터·지식 활용 | 필요한 IQ 도구 + Toolbox | 데이터별 context를 도구로 연결하고 재사용 |
| 도구 공유와 조직 공통 정책이 모두 필요 | Toolbox의 custom MCP connection에 APIM endpoint 연결 | Client의 도구 통합과 API 운영 정책을 함께 적용 |

**도구를 묶는 요구만 있다면 Toolbox부터**, **기존 API까지 같은 운영 기준으로 관리하려면 APIM을 함께 검토**합니다. 내부망 구성은 [APIM](https://learn.microsoft.com/azure/api-management/virtual-network-concepts)과 [Toolbox](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox-network-isolation)의 network 조건에 맞춥니다.

### 적용 시 명시적인 제약

| 항목 | 적용할 조건 |
|---|---|
| APIM의 remote MCP 연결 | [공식 연결 조건](https://learn.microsoft.com/azure/api-management/expose-existing-mcp-server)에 맞는 `2025-06-18` 이상 서버와 Streamable HTTP 또는 SSE transport 사용 |
| APIM Developer | 비운영·평가용 tier이며 SLA 없음. 운영 환경의 private network는 [SKU별 기능](hosting-reference/index.md#apim-sku)으로 선택 |
| MCP streaming | APIM에서 response body를 읽어 buffering을 유발하지 않도록 구성 |
| Toolbox tool 호출 | [비스트리밍 `tools/call` 미지원](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox#troubleshoot). 지원되는 streaming client 방식 사용 |
| Client의 부가 기능 로드 | APIM은 prompts 미지원, Toolbox는 `prompts/list` 미구현. Tools를 사용할 client에서 prompts 자동 로드가 필요 없다면 해제 |

## 7. 실행 예제와 확인 결과

**명령·정리는 sample**, **실행 환경·응답·캡처는 사례**에서 확인합니다. GitHub·Azure·AKS·Learn MCP를 예제 대상으로 사용합니다.

| 할 일 | 실행 자료 | 결과를 볼 곳 |
|---|---|---|
| `azd` 배포와 내부망 접속 | [Walkthrough 1–3](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/walkthrough.md#1-azd로-환경-배포) | [배포·연결 기록](validation/index.md) |
| APIM REST wrapping·MCP proxy·OBO·인가 확인 | [Walkthrough 4–8](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/walkthrough.md#4-entra-access-token-준비) | [도구 호출과 인증 응답](validation/index.md#apim-rest-to-mcp) |
| PRM·앱 등록·token 오류 진단 | [인증 확인 절차](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/authentication-checks.md) | [단계별 관측](validation/index.md#oauth) |
| Toolbox 구성·Tool search·version 관리 | [Toolbox sample](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-architecture/mcp-configuration/samples/toolbox) | Sample의 확인 방법과 앞의 공식 데모 |
| 실습 종료 | [Walkthrough 9](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/walkthrough.md#9-환경-정리) | ARM 리소스와 Entra 앱 정리 |

## Appendix. “MCP 2.0”과 실제 protocol 변경

**2026-09-13 확인 기준** 공식 Current MCP protocol은 [`2026-07-28`](https://modelcontextprotocol.io/docs/2026-07-28/learn/versioning)입니다. Protocol은 날짜형 revision을 사용합니다. **JSON-RPC 2.0**, Python SDK `2.x`, Azure MCP 제품 `2.x`는 서로 다른 버전 축입니다.

이 부록은 **자체 MCP server·SDK·gateway의 wire 호환성을 구현하거나 진단할 때** 사용합니다. 아래 규격 설명을 제품별 지원표로 해석하지 않습니다.

### `2025-11-25`와 `2026-07-28` 비교

[이전 lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle), [이전 transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [현재 변경 목록](https://modelcontextprotocol.io/specification/2026-07-28/changelog)을 기준으로 비교합니다.

| 항목 | `2025-11-25` | `2026-07-28` |
|---|---|---|
| 시작 절차 | `initialize` → `notifications/initialized` | Handshake 제거, 요청별 version·capability 선언 |
| Protocol session | 서버가 선택적으로 session ID 발급 | Protocol session과 `Mcp-Session-Id` 제거 |
| 서버 정보 | 초기화 결과의 정보·capability | `server/discover`로 조회. 서버 구현은 필수, client의 선행 호출은 선택 |
| HTTP 요청·응답 | POST 요청, JSON 또는 SSE 응답 | POST 요청과 JSON/SSE 응답 유지 |
| 독립 알림 스트림 | 선택적 GET SSE | GET 제거, `subscriptions/listen`의 POST 응답 스트림 |
| 추가 입력 요청 | 서버가 독립 JSON-RPC 요청을 전달 가능 | Multi-Round Trip Requests(MRTR)의 `input_required` 결과와 후속 요청 |
| 결과 구분 | `resultType` 없음 | `resultType` 필수. 구형 응답의 생략 값은 `complete`로 해석 |
| SSE 재개·취소 | 재개를 선택적으로 지원, 단절 자체는 취소가 아님 | `Last-Event-ID` 재개 제거, 응답 스트림 종료로 해당 요청 취소 |

**SSE가 없어졌다는 뜻이 아닙니다.** 독립 GET 스트림과 session 계약이 바뀌었으며 POST의 SSE 응답은 유지됩니다. 이전 구현도 session과 GET 스트림을 반드시 제공해야 했던 것은 아닙니다.

<details markdown="1">
<summary>상세 wire 규격 — SDK·전송·오류 처리를 직접 구현하거나 진단할 때</summary>

### 요청별 metadata와 HTTP header

아래는 현재 [기본 메시지 계약](https://modelcontextprotocol.io/specification/2026-07-28/basic)과 [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)의 **RPC 요청** 요구사항입니다.

| 위치 | 요구사항 |
|---|---|
| `params._meta["io.modelcontextprotocol/protocolVersion"]` | 매 요청 필수 |
| `params._meta["io.modelcontextprotocol/clientCapabilities"]` | 매 요청 필수. 선택적 capability가 없으면 `{}` |
| `params._meta["io.modelcontextprotocol/clientInfo"]` | 매 요청 권고 |
| `result._meta["io.modelcontextprotocol/serverInfo"]` | 매 결과 권고 |
| `MCP-Protocol-Version` | 본문의 protocol version과 일치해야 함 |
| `Mcp-Method` | 본문의 JSON-RPC `method`와 일치해야 함 |
| `Mcp-Name` | `tools/call`, `resources/read`, `prompts/get`에서 필수. 해당 `params.name` 또는 `params.uri` 사용 |
| `Accept` | `application/json`과 `text/event-stream`을 모두 포함 |

`clientInfo`와 `serverInfo`는 자체 신고 정보이지 인증된 identity가 아닙니다. `Mcp-Name`을 안전한 ASCII header 값으로 표현할 수 없다면 명세의 Base64 sentinel 인코딩을 적용합니다. HTTP POST에는 단일 JSON-RPC request 또는 notification을 보내며 client가 JSON-RPC response를 보내지는 않습니다. 현재 core에는 client→server HTTP notification이 없으므로 RPC header 요구사항을 notification에 임의로 확장하지 않습니다.

### Discovery와 오류 처리

[`server/discover`](https://modelcontextprotocol.io/specification/2026-07-28/server/discover)의 정상 응답은 `result.supportedVersions`를 사용합니다. 지원하지 않는 버전 오류는 `error.data.supported`와 `error.data.requested`를 사용합니다. OAuth authorization server discovery와는 다른 기능입니다.

| 상황 | 현재 HTTP / JSON-RPC 계약 |
|---|---|
| 지원하지 않는 revision | `400` / `-32022` |
| 필수 본문 metadata 누락 | `400` / `-32602` |
| 필요한 client capability 누락 | `400` / `-32021` |
| 필수 header 누락·형식 오류·본문과 불일치 | `400` / `-32020` |
| 구현하지 않은 RPC method | `404` / `-32601` |
| Modern-only endpoint의 GET/DELETE | `405` 권고 |
| Access token 부재·무효 / 권한 부족 | 각각 `401` / `403` |

구형 session의 `404`는 재초기화를 의미할 수도 있었습니다. [버전 호환 처리](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)는 상태 코드만 보지 않고 구조화된 오류를 검사합니다. 특히 `401/403`을 protocol downgrade로 처리하거나, modern header 오류를 무조건 `initialize` 재시도로 바꾸지 않습니다. Notification의 `202 Accepted`·빈 본문을 일반 tool 실행 완료 응답으로 해석하지 않습니다.

### HTTP authorization의 protocol 요구사항

MCP authorization 자체는 선택적이며, 다음은 [HTTP authorization을 채택하는 경우](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)의 계약입니다.

| 항목 | 현재 요구사항 |
|---|---|
| Protected resource | RFC 9728 metadata와 하나 이상의 `authorization_servers` 제공 |
| Metadata 위치 | 서버는 401 challenge의 `resource_metadata` 또는 well-known 방식 제공. Client는 둘 다 지원하고 challenge URL 우선 |
| Authorization server | RFC 8414 또는 OIDC Discovery 지원. Client는 두 방식과 발견된 `issuer`의 일치 여부 확인 |
| 대상 리소스 | Authorization·token 요청 모두에 RFC 8707 `resource` 포함. 대상 MCP 서버의 canonical URI 사용 |
| PKCE | 구현과 서버 지원 확인 필수. 기술적으로 가능하면 `S256` 사용 |
| Client 등록 | Client ID는 필요하지만 DCR은 필수가 아님. 사전 등록 옵션·CIMD 지원은 권고, DCR은 현재 선택적·deprecated |
| Token | 대상 리소스·유효성·필요 권한을 검증. `resource`를 보냈다는 사실이 서버 검증을 대신하지 않음 |

세부 요구사항은 [authorization server discovery](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/authorization-server-discovery), [client registration](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration), [security considerations](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations)를 따릅니다. 해당 규격의 client는 metadata의 `code_challenge_methods_supported` 선언이 없으면 authorization을 중단합니다. 사전 등록·DCR credential은 issuer별로 관리합니다. CIMD의 참조 규격은 현재 IETF draft입니다.

### Gateway를 사이에 둘 때

Client→gateway와 gateway→MCP backend의 실제 revision을 각각 확인합니다. 헤더를 추가하거나 session header만 제거하는 것으로 신·구 protocol 변환이 끝나지 않습니다. JSON/SSE 보존, buffering·timeout과 취소 동작도 확인합니다.

단절된 요청을 재실행하려면 새 request ID를 사용하지만, 이미 발생한 업무 부작용이 롤백되었다는 뜻은 아닙니다. 쓰기 도구의 자동 재시도는 별도의 멱등성 정책이 필요합니다. Protocol의 session 제거는 token audience를 없애거나 Entra OBO를 자동으로 제공하는 변경이 아닙니다.

</details>
