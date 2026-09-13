---
title: Azure MCP 구성 — APIM·Toolbox·IQ와 사용자 인증
description: APIM과 Foundry Toolbox의 핵심 기능과 공식 MCP 지원 범위를 비교하고, IQ 도구 통합·토큰 절감·OAuth와 OBO를 실행 예제에 연결합니다.
document_type: guide
redirect_from:
  - guides/azure-architecture/mcp-configuration/index.md
  - labs/azure-architecture/mcp-configuration/index.md
  - labs/azure-api-management/mcp-rest-and-upstream/index.md
services: [azure-architecture, azure-api-management, microsoft-foundry, microsoft-entra-id, azure-container-apps, azure-ai-search]
technologies: [mcp, azure-cli]
tags: [ai-agents, architecture, authentication, authorization, networking, monitoring]
status: current
verification_status: needs-review
sources_checked_at: 2026-09-13
official_sources:
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
last_verified: 2026-09-13
review_cycle_days: 90
applies_to:
  - Azure API Management MCP endpoints
  - Microsoft Foundry Toolbox and IQ tool connections
  - Microsoft Entra ID authorization
related_cases:
  - validation/index.md
---

# Azure MCP 구성 — APIM·Toolbox·IQ와 사용자 인증

**APIM은 MCP/API의 공통 접근 정책**, **Toolbox는 IQ를 포함한 도구 집합과 단일 MCP endpoint**를 제공합니다. [인증 단계별 확인](#4-mcp-authorization-obo)과 [실행 결과](#7)를 함께 비교합니다.

## 소개하는 서비스

| 서비스 | 핵심 기능 | 공식 문서 |
|---|---|---|
| **Azure API Management / AI gateway** | Remote MCP에 인증·인가·트래픽 정책 적용, REST operation을 MCP tool로 제공, 요청 telemetry와 backend credential 관리 | [기존 MCP 연결](https://learn.microsoft.com/azure/api-management/expose-existing-mcp-server), [REST-to-MCP](https://learn.microsoft.com/azure/api-management/export-rest-mcp-server), [인증](https://learn.microsoft.com/azure/api-management/secure-mcp-servers) |
| **Microsoft Foundry Toolbox** | 도구 집합을 하나의 MCP endpoint로 제공, connection 인증·version·정책 관리, Tool search로 필요한 도구 검색 | [Toolbox 개요](https://learn.microsoft.com/azure/foundry/agents/concepts/toolbox-overview), [인증](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-authentication), [Tool search](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-search) |
| **Work IQ·Fabric IQ·Foundry IQ** | 각각 Microsoft 365 업무 context, Fabric의 업무 데이터·의미 모델, 기업 문서 knowledge base를 도구로 제공 | [Work IQ](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/work-iq), [Fabric IQ](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/fabric-iq), [Foundry IQ](https://learn.microsoft.com/azure/foundry/agents/concepts/what-is-foundry-iq) |

### MCP HTTP auth 연결 상태

**실측 = 기존 실습의 관측**, **문서 = 제품 문서의 명시 범위**입니다. 사전 token 입력, MCP client의 자동 OAuth 로그인, downstream OBO를 구분합니다.

| 연결 방식 | APIM + Entra | Foundry Toolbox |
|---|---|---|
| **사전 발급한 access token으로 연결** | JWT 검증 정책을 구성해 사용. **실측:** 정상 token 200, wrong audience 401 | **문서:** Foundry용 credential/token과 project 권한으로 접근 |
| **MCP client의 자동 OAuth 로그인** | PRM을 별도로 구성. **현재 실습은 미완료:** discovery는 동작하지만 resource URI 정렬·PKCE 지원 선언 확인 조건이 남음 | Consumer endpoint의 PRM→등록→PKCE 전체 흐름은 **직접 미검증**. Backend의 `oauth2` 설정과는 다른 검사 |
| **Tool이 사용자 권한으로 데이터 호출** | MCP 서버에서 OBO 구현 가능. **실측:** Python MCP의 ARM OBO 성공. APIM 자체의 자동 OBO 실증은 아님 | **문서:** `oauth2`·`user-entra-token`. Work IQ Chat의 A2A 경로는 OBO 명시 |

이번 실측 대상 RG에는 Foundry project/Toolbox가 없습니다. [인증 재확인 기록](validation/index.md#oauth)은 APIM·Entra·직접 호스팅한 MCP에 한정합니다.

### MCP protocol 기능

[`2026-07-28`](https://modelcontextprotocol.io/docs/2026-07-28/learn/versioning) 기준입니다. **미기재는 미지원 판정이 아니며**, JSON-RPC 2.0·SDK `2.x`는 별도 버전입니다.

| 확인 항목 | APIM | Foundry Toolbox |
|---|---|---|
| MCP 연결·endpoint | 기존 remote MCP proxy와 REST-to-MCP 제공 | 하나의 MCP-compatible consumer endpoint 제공 |
| 전송·revision | 외부 서버에 `2025-06-18` 이상 및 Streamable HTTP 또는 SSE 요구 | Streamable HTTP client 예제 제공. [REST 호출 예제](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox)는 `initialize`와 `2025-03-26` 사용. 지원 가능한 전체 revision 목록은 아님 |
| `tools/list`·`tools/call` | 도구 노출과 정책 적용 문서화 | 도구 발견·호출 문서화. 비스트리밍 `tools/call` 미지원 제한 명시 |
| `resources` | **문서 상충:** [개요](https://learn.microsoft.com/azure/api-management/mcp-server-overview)는 미지원, [기존 MCP 연결](https://learn.microsoft.com/azure/api-management/expose-existing-mcp-server)은 외부 MCP resources 지원이라고 설명 | Skills를 MCP resources로 제공하고 `resources/list`로 확인하는 절차 문서화. 일반 remote resources 전체 중계는 미기재 |
| `prompts` | 미지원 명시 | `prompts/list` 미구현과 500 응답을 [문제 해결](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox#troubleshoot)에 명시 |
| `2026-07-28`의 discovery·metadata·MRTR·subscriptions | 확인한 제품 문서에 항목별 지원 목록 없음 | 확인한 제품 문서에 항목별 지원 목록 없음 |

- **APIM resources:** 문서 상충으로 확정하지 않으며, 아래 실습은 tools 중심입니다.
- **Toolbox streaming:** Client 사용 지침의 제한이지 최신 MCP 전체의 미지원 판정은 아닙니다.

## 1. APIM / AI gateway로 MCP 접근 관리

개발 도구는 APIM MCP 주소로 접속합니다. APIM이 사내·타사 backend별 인증·트래픽 정책을 적용합니다.

[![MCP client가 중앙의 APIM으로 요청하고 APIM이 사내 MCP·타사 MCP·REST API로 전달하는 단순한 요청 흐름](images/mcp-reference-architecture.svg)](images/mcp-reference-architecture.svg)

### 기존 MCP와 REST API

- **기존 MCP:** APIM에 remote MCP endpoint를 연결하고 정책을 적용합니다.
- **기존 REST API:** 선택한 REST operation을 MCP tool로 제공합니다. 별도 MCP 업무 서버 코드를 작성하지 않고 기존 API를 도구로 사용할 수 있습니다.

**APIM의 여러 API 관리 ≠ 모든 도구의 자동 단일 catalog 통합**입니다. 도구 집합 통합은 Toolbox 장에서 다룹니다.

### 사용자별 접근과 감사 기록

| 확인할 것 | 적용 기준 |
|---|---|
| 호출 주체 | [`validate-azure-ad-token`](https://learn.microsoft.com/azure/api-management/validate-azure-ad-token-policy)으로 검증한 identity·scope/role 사용. 임의의 사용자 header는 신원 증거가 아님 |
| 최종 사용자 | App-only token만으로 최종 사용자를 식별할 수 없음 |
| 실행 증거 | Gateway HTTP 로그와 tool 실행 결과를 correlation ID로 연결 |
| 보관·보호 | 수집 누락·보관 기간·접근 통제 설계. Token·민감 payload 원문 저장 금지 |
| Telemetry와 감사 | [Application Insights는 감사 시스템이 아님](https://learn.microsoft.com/azure/api-management/api-management-howto-app-insights#performance-implications-and-log-sampling). Sampling 로그만으로 전수 감사를 보장하지 않음 |

## 2. IQ 도구와 MCP는 어떻게 연결되는가

IQ는 **업무 데이터·지식을 제공하는 서비스**이며, MCP는 연결 방식입니다.

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

Client는 **하나의 Toolbox MCP endpoint**를 사용하고, Toolbox가 connection별 인증·도구 version·정책을 관리합니다. Foundry 밖의 MCP-compatible client도 사용할 수 있습니다.

[![하나의 Toolbox MCP endpoint가 Work IQ·Fabric IQ·Foundry IQ 및 사내·타사 MCP 도구에 연결하며 downstream protocol은 MCP 또는 A2A로 구분되는 구성](images/toolbox-iq-mcp.svg)](images/toolbox-iq-mcp.svg)

핵심 기능은 [Build·Discover·Consume·Govern](https://learn.microsoft.com/azure/foundry/agents/concepts/toolbox-overview)입니다.

- **도구 구성과 공유:** 업무에 필요한 도구를 모아 여러 client가 재사용합니다.
- **Connection 인증:** 도구에 맞는 OAuth·사용자 token·서비스 identity·key를 구성합니다.
- **Version과 정책:** 도구 집합을 version으로 관리하고 인증·인가·guardrail·관측 설정을 적용합니다.
- **Tool search:** 큰 도구 집합에서 해당 요청에 필요한 tool definition을 찾습니다.

### Tool search와 토큰 절감 데모

| 동작 | 내용 |
|---|---|
| 검색 | `tool_search`가 이름·description·parameter metadata를 BM25로 검색 |
| 실행 | `call_tool`로 선택한 도구 호출 |
| 초기 노출 | Pin·auto-pin 도구가 추가될 수 있어 항상 두 개만 노출되는 것은 아님 |

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

**약 90% 감소는 해당 영상의 시연 값**이며 자체 실측이나 일반 보장이 아닙니다.

- 같은 model·도구·질문 조건에서 업무 완료까지의 input/output tokens, cache, 검색 횟수, latency·재시도를 비교합니다.
- 설정: [Tool search 공식 문서](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-search) · [Toolbox sample](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-architecture/mcp-configuration/samples/toolbox)

## 4. MCP authorization과 OBO를 함께 설계하기

| 인증 구간 | 필요한 token |
|---|---|
| Client → MCP API | **A:** MCP API용 access token. MCP HTTP authorization의 대상 |
| MCP API → ARM·Graph 등 | **B:** 별도 데이터 API용 token. 사용자 위임이면 Entra OBO를 사용할 수 있음 |

[![MCP OAuth로 MCP API용 token A를 얻은 후 중간 API가 Entra OBO로 별도 데이터 API용 token B를 받는 흐름](images/mcp-oauth-obo.svg)](images/mcp-oauth-obo.svg)

### MCP HTTP auth에서 실제로 구성·확인할 단계

**2026-09-13 재확인 결과**입니다. APIM은 MCP protected resource, Entra는 authorization server, IDE/SDK는 OAuth client로 각각 설정합니다.

| 단계 | 구성 위치 | 기존 APIM + Entra 실측 | Toolbox consumer endpoint |
|---|---|---|---|
| **① 401 challenge·PRM** | MCP endpoint: RFC 9728 metadata, `resource_metadata`, scopes | APIM 정책으로 구성. **401 challenge → PRM 200** 확인 | 전체 자동 discovery 동작 직접 미검증 |
| **② Authorization server 발견** | Client가 PRM의 issuer를 따라 RFC 8414/OIDC metadata 조회 | **OIDC 200**, authorization·token·JWKS endpoint 확인 | 문서는 Foundry credential/token 사용을 설명. 실제 metadata는 미검증 |
| **③ Client 등록·scope·consent** | Entra 앱 등록 + 사용할 client | 등록된 public client의 사전 승인 설정 확인. 해당 client의 대화형 로그인은 미실행 | Azure credential 방식 문서화. 사용할 MCP client의 등록·consent 경로 확인 필요 |
| **④ PKCE/S256** | OAuth client + authorization server | Entra는 S256을 지원하지만 **이번 OIDC 응답에 `code_challenge_methods_supported` 없음** | 입력 endpoint의 PKCE 흐름 직접 미검증. Backend `oauth2` 설정과 별개 |
| **⑤ 대상 resource 정렬** | PRM `resource` ↔ Entra Application ID URI ↔ client 요청 | 앱에는 `api://...`만 등록. **HTTPS MCP URI 없음**, URL 대상 CLI token 요청은 `AADSTS500011` | `https://ai.azure.com/.default` token 사용 문서화. MCP 자동 OAuth의 URI 정렬은 미검증 |
| **⑥ Token·권한 검사** | MCP endpoint의 issuer·audience·expiry·scope/role 검증 | **정상 token 200 / wrong audience 401** | Foundry token·project 권한 검사 문서화. 직접 미실측 |
| **⑦ Token 갱신** | Client credential/refresh 흐름 | 수명주기 재검증은 미실행 | Consumer credential 갱신과 backend connection 갱신을 구분해야 함 |

- **PKCE 기능 ≠ 지원 선언:** [Entra는 S256 지원](https://learn.microsoft.com/entra/identity-platform/v2-oauth2-auth-code-flow#request-an-authorization-code). 그러나 [MCP 규격](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations#authorization-code-protection)은 metadata에 선언이 없으면 client가 authorization을 진행하지 않도록 요구합니다.
- **Resource 정렬:** [Entra MCP 구성 문서](https://learn.microsoft.com/entra/agent-id/secure-mcp-server-with-entra-id#step-3-set-the-application-id-uri-to-your-mcp-server-url)의 조건을 확인합니다. CLI의 URL 대상 검사는 브라우저 PKCE 전체 교환의 실증이 아닙니다.
- **현재 판정:** 사전 token 발급·API 검증·Python OBO는 성공. **자동 OAuth는 ④·⑤의 추가 확인/구성 전까지 완료로 표시하지 않습니다.** [실행 방법과 비식별 결과](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/authentication-checks.md)

### 연결된 tool의 인증: APIM과 Toolbox 비교

| 데이터 호출 방식 | APIM | Toolbox |
|---|---|---|
| 공유·서비스 credential | Credential manager의 unattended connection 또는 backend 인증 정책 | `custom-keys`, `project-managed-identity`, `agentic-identity` |
| 사용자별 OAuth connection | [Attended(user-delegated) connection](https://learn.microsoft.com/azure/api-management/credentials-overview#attended-user-delegated-scenario)으로 사용자 credential 관리·갱신·주입 | [`oauth2`](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-authentication)로 사용자 authorization·token lifecycle 관리 |
| 대상 서비스용 사용자 Entra token | 선택한 backend 인증/위임 구현에 따라 구성 | 지원 서비스의 `user-entra-token` |
| **명시적인 Entra OBO** | 이 실습은 **MCP 서버가 ARM OBO를 수행**. APIM의 자동 OBO 실증은 아님 | [Work IQ Chat A2A 경로](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/work-iq#how-it-works)는 OBO 명시. 모든 `oauth2` connection의 구현으로 일반화하지 않음 |

- 같은 논리적 MCP resource 내부 전달: token 검증과 [내부 구간 기밀성](https://www.rfc-editor.org/rfc/rfc6750.html#section-5.2) 유지.
- 다른 데이터 API 호출: [그 API용 별도 token](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations) 사용. 사용자 OBO에 app-only token을 넣지 않음.
- 사용자 OAuth를 공유/service credential로 조용히 바꾸지 않으며, Toolbox와 gateway가 서로 token을 덮어쓰지 않도록 소유 위치를 정함.

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

| 요구사항 | 우선 검토 | 추가 확인 |
|---|---|---|
| 여러 MCP·IQ를 한 주소로 제공 | Toolbox 단독 | Connection 인증·version·필요 도구 지원 |
| 여러 팀과 기존 API의 공통 통제 | APIM | 승인 endpoint, 호출 제한, 감사 이벤트 정책 |
| 두 서비스 병행 | 지원되는 custom MCP connection에서 APIM 주소 사용 검토 | 모든 IQ·managed OAuth가 같은 routing을 지원한다고 가정하지 않음 |
| 사용자별 데이터 권한 | 실제 identity·audience·consent 확인 | OBO와 MCP 자동 OAuth를 각각 검증 |
| 내부망 접근 | Client→entry와 entry→backend를 각각 점검 | Route·DNS·접근 제어와 [도구별 network 지원](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox-network-isolation) |

## 7. 실행 예제와 확인 결과

`azd`, MCP Inspector, HTTP 요청과 `kubectl`을 단계별로 실행했습니다. GitHub·Azure·AKS·Learn은 예제 대상입니다.

| 확인한 내용 | 실행 방법과 관측 결과 | 따라 하기·기록 |
|---|---|---|
| Azure 배포 | Native `azd up`으로 provisioning·ACR remote build·앱 배포, 33분 26초 | [배포 절차](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/walkthrough.md#1-azd로-환경-배포), [실행 이력](validation/index.md#_2) |
| REST-to-MCP | 원래 REST 응답과 MCP `getInventory` 결과의 가상 재고 비교 | [REST/MCP 호출 절차](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/walkthrough.md#5-rest-api를-apim-mcp-tool로-호출), [응답·캡처](validation/index.md#apim-rest-to-mcp) |
| 사용자 OBO | Native Azure MCP와 Python MCP의 도구 호출로 ARM resource group 조회 | [OBO 호출 절차](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/walkthrough.md#6-azure-mcp에서-obo로-azure-조회), [관측 결과](validation/index.md#azure-python-mcp-obo) |
| 기존 remote MCP proxy | APIM을 통해 Learn의 도구 목록과 검색 결과 확인 | [Proxy 호출 절차](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/walkthrough.md#7-apim을-통해-기존-learn-mcp-호출), [실행 기록](validation/index.md#learn-mcp) |
| 인증 실패·복구 | 무인증·wrong audience의 401, 허용 client 제외 시 403, 복구 후 정상 조회 | [401/403 절차](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/walkthrough.md#8-401과-403-확인), [응답 기록](validation/index.md#_3) |
| OAuth 단계 재확인 | PRM·Entra metadata·앱 URI와 token 검증·OBO를 각각 점검. 자동 OAuth의 남은 조건 확인 | [확인 절차](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/authentication-checks.md), [관측 결과](validation/index.md#oauth) |
| 로컬 MCP 연결 | Inspector로 GitHub·Azure·Learn 도구 호출, AKS MCP로 pod 조회 | [로컬 연결과 내부망 접속](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-architecture/mcp-configuration/samples/apim-entra-lab/walkthrough.md#2-로컬-mcp-서버-연결) |
| Toolbox·Tool search | 공식 문서·CLI와 azd service 구성을 확인한 수동 시나리오. **실제 Foundry 배포·토큰 절감 실측은 수행하지 않음** | [Toolbox sample과 확인 범위](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-architecture/mcp-configuration/samples/toolbox) |

**실측 범위:** APIM·Container Apps·Entra. IQ 실데이터 권한, Toolbox OAuth와 최신 MCP 전체 적합성은 미실증입니다.

## Appendix. “MCP 2.0”과 실제 protocol 변경

**2026-09-13 확인 기준** 공식 Current MCP protocol은 [`2026-07-28`](https://modelcontextprotocol.io/docs/2026-07-28/learn/versioning)입니다. Protocol은 날짜형 revision을 사용합니다. **JSON-RPC 2.0**, Python SDK `2.x`, Azure MCP 제품 `2.x`는 서로 다른 버전 축입니다.

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

세부 요구사항은 [authorization server discovery](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/authorization-server-discovery), [client registration](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration), [security considerations](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations)를 따릅니다. Metadata에 `code_challenge_methods_supported`가 없으면 PKCE 지원을 확인하지 못한 상태로 authorization을 진행하지 않습니다. 사전 등록·DCR credential은 issuer별로 관리합니다. CIMD의 참조 규격은 현재 IETF draft입니다.

이 protocol 요구사항이 Entra·모든 IDE·모든 gateway의 동일 기능 지원을 보장하지는 않습니다. Sample의 수동 token 발급·호출 결과를 각 IDE의 interactive OAuth 전체 흐름을 검증한 것으로 해석하지 않습니다.

### Gateway를 사이에 둘 때

Client→gateway와 gateway→MCP backend의 실제 revision을 각각 확인합니다. 헤더를 추가하거나 session header만 제거하는 것으로 신·구 protocol 변환이 끝나지 않습니다. JSON/SSE 보존, buffering·timeout과 취소 동작도 확인합니다.

단절된 요청을 재실행하려면 새 request ID를 사용하지만, 이미 발생한 업무 부작용이 롤백되었다는 뜻은 아닙니다. 쓰기 도구의 자동 재시도는 별도의 멱등성 정책이 필요합니다. Protocol의 session 제거는 token audience를 없애거나 Entra OBO를 자동으로 제공하는 변경이 아닙니다.
