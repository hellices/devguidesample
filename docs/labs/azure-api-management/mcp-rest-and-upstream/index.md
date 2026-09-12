---
title: 내부망 MCP 실습 — APIM REST 도구 변환과 Entra OBO를 따로 검증하기
description: 새 실습 리소스 그룹에서 APIM의 REST-to-MCP, 기존 MCP 프록시, Azure MCP의 사용자 위임을 배포하고 인증 실패까지 확인합니다.
document_type: lab
services: [azure-api-management, azure-container-apps, azure-kubernetes-service, microsoft-entra-id]
technologies: [azure-cli, bicep, python]
tags: [ai-agents, authentication, authorization, deployment, networking]
status: verified
verification_status: needs-review
sources_checked_at: 2026-09-12
official_sources:
  - title: Expose REST API in API Management as an MCP server
    url: https://learn.microsoft.com/azure/api-management/export-rest-mcp-server
  - title: Manage MCP servers programmatically in API Management
    url: https://learn.microsoft.com/azure/api-management/manage-mcp-servers-rest-api
  - title: Secure access to MCP servers in API Management
    url: https://learn.microsoft.com/azure/api-management/secure-mcp-servers
  - title: Validate Microsoft Entra token
    url: https://learn.microsoft.com/azure/api-management/validate-azure-ad-token-policy
  - title: Microsoft identity platform and OAuth 2.0 On-Behalf-Of flow
    url: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow
  - title: Deploy Azure MCP Server with on-behalf-of authentication
    url: https://learn.microsoft.com/azure/developer/azure-mcp-server/how-to/deploy-remote-mcp-server-on-behalf-of
  - title: Virtual network configuration
    url: https://learn.microsoft.com/azure/container-apps/custom-virtual-networks
  - title: Enable authentication and authorization in Azure Container Apps with Microsoft Entra ID
    url: https://learn.microsoft.com/azure/container-apps/authentication-entra
  - title: Microsoft.App containerApps/authConfigs
    url: https://learn.microsoft.com/azure/templates/microsoft.app/2025-01-01/containerapps/authconfigs
  - title: Use kubelogin to authenticate users in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/kubelogin-authentication
  - title: "Quickstart: Build and run a container image using Azure Container Registry Tasks"
    url: https://learn.microsoft.com/azure/container-registry/container-registry-quickstart-task-cli
last_verified: 2026-09-12
review_cycle_days: 90
estimated_time: 120m
cost: paid
cleanup_required: true
related_cases:
  - ../../../cases/azure-api-management/mcp-entra-validation/index.md
related_guides:
  - ../../../guides/azure-api-management/mcp-entra-private-access/index.md
---

# 내부망 MCP 실습 — APIM REST 도구 변환과 Entra OBO를 따로 검증하기

MCP 엔드포인트가 응답하는 것, Entra 토큰을 검증하는 것, 사용자의 권한으로 Azure를 조회하는 것은 서로 다른 성공 조건입니다. 이 실습은 세 조건을 분리합니다. **APIM의 REST-to-MCP 변환도 OBO와 별개의 기능**으로 검증합니다.

실제 실행 시점의 성공·실패·미실행 항목은 [검증 기록](../../../cases/azure-api-management/mcp-entra-validation/index.md)에 보존합니다. 이 페이지의 명령은 재실행 절차이며, 명령이 있다는 이유만으로 모든 경로가 검증된 것은 아닙니다.

## 목표와 구성

| 경로 | 확인할 것 | 확인하지 않는 것 |
|---|---|---|
| 로컬 → 공식 GitHub / Learn / Azure / AKS MCP | 실제 서버와 연결하고 읽기 도구 호출 | 네 서버의 인증이 모두 Entra OBO라는 가정 |
| 로컬 → 내부 Container Apps → Azure MCP 2.0.5 | Entra 사용자 토큰 → OBO → Azure 조회 | 호스팅 관리 ID로 사용자를 대체하는 접근 |
| 로컬 → 내부 Container Apps → Python MCP | 사용자 토큰 검증과 고정된 실습 RG에 대한 OBO | 임의 구독·URL·명령을 실행하는 범용 프록시 |
| 로컬 → 내부 APIM → REST operation | REST operation이 실제 MCP tool로 노출되고 백엔드 호출로 이어지는지 | 가짜 `tools/call` 응답 또는 기존 MCP 프록시로 대체 |
| 로컬 → 내부 APIM → Learn MCP | Entra로 게이트웨이를 보호하고 익명 백엔드로 연결 | Entra 토큰을 Learn으로 전달하는 동작 |

설계 대안과 각 SVG는 [인증·호스팅 비교](../../../research/azure-api-management/mcp-authentication-options/index.md)에서 확인합니다. 실행 코드, Bicep, 테스트와 수집기는 [실습 소스](https://github.com/hellices/devguidesample/tree/main/samples/azure-api-management/mcp-entra-lab)에 있습니다.

### 리소스 그룹의 실제 범위

직접 만드는 실습 RG는 하나입니다. **전체 배포가 RG 하나에만 들어가는 것은 아닙니다.**

- 새 AKS는 별도 노드 RG를 만듭니다.
- VNet을 사용하는 Container Apps 환경도 별도 관리형 인프라 RG를 만듭니다.
- Entra 애플리케이션과 서비스 주체는 RG가 아닌 테넌트 객체입니다.

모든 이름과 객체 ID는 저장소 밖의 비공개 상태 파일에 기록합니다. 기존 RG를 가져다 쓰지 않으며, 초기 what-if가 기존 리소스의 변경·삭제를 요구하면 배포를 중단합니다.

### 내부망 검증 경로

회사 LAN과 새 Azure VNet 사이의 VPN/ExpressRoute를 자동으로 만들지 않습니다. 실습에서는 새 AKS의 전용 probe를 통해 내부 엔드포인트에 도달합니다.

```text
로컬 MCP 클라이언트
  → 127.0.0.1의 kubectl port-forward
  → 인증된 AKS 관리 연결
  → VNet 안의 HTTPS CONNECT probe
  → 내부 APIM / 내부 Container Apps
```

probe는 지정된 실습 호스트의 443번 포트만 허용하며 공개 Service·Ingress를 만들지 않습니다. CONNECT 안의 TLS는 MCP 엔드포인트까지 유지합니다. **이것은 관리 터널을 이용한 VNet 내부 실증이지, 회사 VPN·DNS가 준비되었다는 증거가 아닙니다.** AKS 관리 API의 인증된 공개 접근과 MCP 데이터 엔드포인트의 내부 접근도 구분합니다.

## 사전 조건

| 조건 | 실습에서 필요한 이유 |
|---|---|
| Azure CLI의 사용자 로그인 | 앱 전용 로그인은 사용자 OBO 증거가 될 수 없음 |
| 선택 구독의 새 RG·네트워크·서비스 배포 권한 | 격리된 리소스만 생성 |
| 해당 배포 범위의 역할 할당 권한 | 새 관리 ID의 AcrPull, 새 AKS의 운영자 역할 설정 |
| 테넌트의 앱 등록 및 필요한 동의 권한 | 새 API scope와 현재 사용자에 한정한 위임 동의 설정 |
| Azure CLI, Bicep, kubectl, kubelogin, GitHub CLI | 배포와 공식 로컬 MCP 연결 |
| Python 3.13 및 저장소의 테스트 의존성 | 샘플과 검증기 실행 |
| 필요한 공개 서비스로의 송신 | Entra, GitHub, Learn 및 이미지·패키지 다운로드 |

로컬 Docker daemon은 필수 조건이 아닙니다. Python 서버 이미지는 ACR Tasks로 빌드합니다. 구독·테넌트 정책이나 할당량 때문에 단계가 실패하면 원인을 해결한 뒤 재실행하며, 인증을 끄거나 공용 ingress로 바꾸지 않습니다.

## 비용과 안전 경계

실습 기본값은 Korea Central의 APIM Developer 1개, Container Apps Consumption workload profile, ACR Basic, AKS Free 제어 평면과 `Standard_D4as_v5` 노드 1개입니다. Developer APIM과 단일 노드 구성은 운영 환경의 SLA·가용성 기준이 아닙니다.

2026-09-12 UTC에 조회한 공개 Retail Prices API의 두 meter는 다음과 같습니다.

| Meter | USD / 1 Hour |
|---|---:|
| APIM Developer Unit | 0.0658 |
| Linux VM D4as v5 | 0.212 |

두 meter만 24시간 단순 합산하면 약 **USD 6.67**입니다. **전체 견적이나 비용 상한이 아닙니다.** 디스크, 로드 밸런서, 공용 IP, DNS, Container Apps 관리 인프라·실행, ACR·빌드, 송신 및 세금·계약 할인은 별도입니다. [APIM 가격 조회](https://prices.azure.com/api/retail/prices?$filter=serviceName%20eq%20%27API%20Management%27%20and%20armRegionName%20eq%20%27koreacentral%27%20and%20skuName%20eq%20%27Developer%27)와 [VM 가격 조회](https://prices.azure.com/api/retail/prices?$filter=serviceName%20eq%20%27Virtual%20Machines%27%20and%20armRegionName%20eq%20%27koreacentral%27%20and%20armSkuName%20eq%20%27Standard_D4as_v5%27%20and%20productName%20eq%20%27Virtual%20Machines%20Dasv5%20Series%27%20and%20skuName%20eq%20%27Standard_D4as_v5%27%20and%20priceType%20eq%20%27Consumption%27)를 재조회하세요.

**`expiresOn` 태그는 자동 삭제 기능이 아닙니다.** PR 검토를 기다리는 동안에도 리소스 비용이 발생합니다. 배포 전 정리 담당자와 유지 기간을 정하고, 검토가 끝나면 아래 정리 절차를 실행합니다.

- GitHub 개발자 토큰을 Azure에 업로드하지 않습니다.
- OBO 실패를 관리 ID나 client credentials 성공으로 대체하지 않습니다.
- 익명 REST 백엔드는 가상 재고만 반환하는 실습 fixture입니다. 업무 데이터를 같은 설정으로 공개하지 않습니다.
- 사용자 토큰은 증거 파일에 저장하지 않습니다. 짧은 수명의 실습용 confidential-client secret은 비공개 상태와 Container Apps secret에만 보관합니다.

## 배포

아래 명령은 저장소 루트의 Bash 기준입니다. 다른 셸에서는 환경 변수와 경로 문법을 조정합니다.

### 1. 환경과 비공개 상태 경로

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-docs.txt \
  -r samples/azure-api-management/mcp-entra-lab/requirements.txt

export LAB_SAMPLE="samples/azure-api-management/mcp-entra-lab"
export PYTHONPATH="$LAB_SAMPLE"
npm ci --prefix "$LAB_SAMPLE" --no-audit --no-fund
export LAB_PRIVATE="$(mktemp -d)"
chmod 700 "$LAB_PRIVATE"
export LAB_STATE="$LAB_PRIVATE/state.json"
```

문서 CI에는 샘플 의존성이나 애플리케이션 테스트를 추가하지 않습니다. 위 설치는 실습자가 로컬에서 샘플 테스트까지 실행하기 위한 것입니다.

비공개 디렉터리는 저장소 밖에 두세요. 이후 재개·정리에 필요하므로 경로를 보관하되, 상태 파일·비밀·kubeconfig를 PR에 첨부하지 않습니다.

### 2. 계획, 실제 ARM 검증, 기반 배포

```bash
python "$LAB_SAMPLE/cloud_lab.py" --state "$LAB_STATE" plan \
  --location koreacentral
python "$LAB_SAMPLE/cloud_lab.py" --state "$LAB_STATE" validate
python "$LAB_SAMPLE/cloud_lab.py" --state "$LAB_STATE" deploy-foundation
```

`plan`은 현재 Azure CLI 사용자·구독에 상태를 묶고 새 이름을 선택할 뿐 Azure 리소스를 만들지 않습니다. `validate`는 ARM validation과 what-if를 실행합니다. `deploy-foundation`은 검증된 계획으로만 생성합니다.

```bash
python "$LAB_SAMPLE/cloud_lab.py" --state "$LAB_STATE" status
```

Container Apps가 생성한 DNS 이름은 배포 전 계산할 수 없습니다. 따라서 해당 DNS 레코드는 실제 이름을 받은 다음 애플리케이션 단계에서 검증·배포합니다. what-if의 `Unsupported`를 성공으로 무시하지 않습니다.

### 3. API·클라이언트와 사용자 위임

```bash
python "$LAB_SAMPLE/entra_setup.py" --state "$LAB_STATE" apps
python "$LAB_SAMPLE/entra_setup.py" --state "$LAB_STATE" grant-operator
python "$LAB_SAMPLE/entra_setup.py" --state "$LAB_STATE" federate-azure
```

| 등록 | 용도 |
|---|---|
| Public client | 비밀 없는 로컬 클라이언트 |
| Custom API, `Mcp.Access` | Python MCP와 실습 APIM API의 보호된 논리 API |
| Azure MCP API, `Mcp.Tools.ReadWrite` | 공식 Azure MCP 2.0.5의 별도 audience |

`--read-only`를 사용해도 공식 Azure MCP의 요구 scope 이름은 `Mcp.Tools.ReadWrite`입니다. 존재하지 않는 `Mcp.Tools.Read`로 바꾸지 않습니다.

API는 v2 access token을 요청하도록 구성하고, Azure CLI와 실습 public client를 지정 scope에 사전 승인합니다. ARM 위임 동의는 **현재 운영자에 대한 `consentType: Principal`**입니다. `AllPrincipals` 동의를 자동으로 추가하지 않습니다. 이 단계에 필요한 테넌트 권한이 없으면 중단하고 동의 정책을 확인합니다.

공식 Azure MCP의 관리 ID는 federated identity credential로 **confidential client 자신을 인증**합니다. 이후 ARM 조회는 사용자 OBO입니다. 이 관리 ID에 구독 Reader를 부여하여 사용자 권한을 대체하지 않습니다.

사전 승인만으로 caller가 제한되지는 않습니다. Python 서버는 비어 있지 않은 `ENTRA_ALLOWED_CLIENT_IDS`를 요구하고, native Azure MCP 앞의 Container Apps authentication에는 별도 allowed-applications 정책을 배포합니다.

### 4. 호스팅 전에 실제 토큰과 OBO 분리 검사

```bash
python "$LAB_SAMPLE/auth_probe.py" --state "$LAB_STATE" \
  --output "$LAB_SAMPLE/evidence/auth-local-live.json"
```

수집기는 두 API용 사용자 토큰의 서명·issuer·audience·scope를 확인하고, custom API의 OBO 토큰으로 새 RG를 조회합니다. 원래 MCP 토큰을 ARM에 보내면 401이어야 합니다.

**이 단계는 로컬 코드에서 실행한 실제 Entra/ARM 교환입니다.** 아직 호스팅된 MCP, MCP 클라이언트의 자동 OAuth discovery, 대화형 PKCE 흐름을 증명하지 않습니다. Azure CLI의 `get-access-token`에는 `--tenant`와 `--subscription`을 동시에 지정할 수 없습니다.

### 5. 컨테이너와 APIM의 두 가지 MCP 경로

```bash
python "$LAB_SAMPLE/cloud_stage.py" --state "$LAB_STATE" build
python "$LAB_SAMPLE/cloud_stage.py" --state "$LAB_STATE" deploy-apps
python "$LAB_SAMPLE/cloud_stage.py" --state "$LAB_STATE" deploy-apim
```

이미지는 빌드 후 digest로 고정합니다. 공식 Azure MCP도 조사한 안정 버전의 digest를 사용하며, 당시 beta를 가리킨 `latest`는 사용하지 않습니다.

APIM의 두 모델은 제어 평면에서 다릅니다.

| 모델 | 배포되는 연결 |
|---|---|
| **REST-to-MCP** | `type: mcp` API → `apis/tools` → 실제 REST operation의 ARM ID |
| **기존 MCP 프록시** | `type: mcp` API → backend base URL과 `mcpProperties`의 `streamable`·`message` endpoint |

REST 경로에는 가짜 `inputSchema`나 `"synthetic"` discriminator를 만들지 않습니다. 실제 `tools/list`가 반환하는 이름과 schema를 확인합니다. MCP API만 생성하고 도구 매핑을 생략한 것은 REST-to-MCP 구현이 아닙니다.

Learn 프록시는 URL이 `https://learn.microsoft.com/api`인 **backend 리소스**를 만들고 API의 `backendId`로 연결합니다. 실행 환경의 endpoint 계약은 `endpoints: { message: { uriTemplate: /mcp } }`였습니다. `serviceUrl`만 지정해 생성된 빈 도구 목록을 정상적인 프록시 연결로 판단하지 않습니다.

확인일의 Learn 관리 예제·Bicep 타입은 endpoint를 배열로 설명했지만, 실제 API는 배열을 거부하고 keyed object를 요구했습니다. [공식 AI-Gateway 샘플](https://github.com/Azure-Samples/AI-Gateway/blob/main/labs/mcp-from-graphql/src/mcp-api/api.bicep)도 이 차이를 명시합니다. 해당 필드의 `BCP036`만 국소적으로 예외 처리하며, 실제 read-back·도구 목록·호출로 확인합니다. 이 예외를 다른 검증 실패에 확대 적용하지 않습니다.

JWT 정책을 먼저 설치한 다음 API를 생성합니다. tenant, 허용 client, 해당 API audience와 `Mcp.Access`를 검증합니다. 익명으로 열어 두는 예외는 업무 데이터가 없는 protected-resource metadata뿐입니다. REST fixture와 Learn으로 나갈 때는 `Authorization`을 제거합니다.

## 내부 경로와 시나리오 실행

```bash
python "$LAB_SAMPLE/network_probe.py" --state "$LAB_STATE" prepare
python "$LAB_SAMPLE/network_probe.py" --state "$LAB_STATE" forward
```

`forward`는 별도 터미널에서 유지합니다. 임의의 사용 가능한 loopback 포트를 선택하고 비공개 `network.json`에 기록합니다. 운영자의 기존 기본 kubeconfig는 수정하지 않습니다.

공식 release에서 플랫폼에 맞는 AKS MCP 0.0.20을 설치하고 digest를 확인합니다. 확인한 macOS arm64 명령과 `AKS_MCP_BIN` 변수는 [샘플 README](https://github.com/hellices/devguidesample/blob/main/samples/azure-api-management/mcp-entra-lab/README.md#pinned-aks-mcp-runtime)에 있습니다.

```bash
python -m probe_upstreams --state "$LAB_STATE" --aks-binary "$AKS_MCP_BIN" \
  --output "$LAB_SAMPLE/evidence/upstreams.json"
python -m probe_cloud --state "$LAB_STATE" \
  --output "$LAB_SAMPLE/evidence/cloud.json"
python -m probe_native_gate --state "$LAB_STATE" --exercise-denial \
  --output "$LAB_SAMPLE/evidence/native-client-gate.json"
```

마지막 명령은 **실습 전용의 일시적 설정 변경 검사**입니다. Azure CLI client만 allowlist에서 제외하여 동일한 정상 token의 거부를 확인한 뒤 원래 정책을 복구합니다. 실행 중 다른 사용자가 해당 lab client를 사용하지 않게 하세요. `--exercise-denial`을 생략하면 설정·허용 호출만 읽기 방식으로 확인합니다.

실행해야 할 검증은 다음과 같습니다. **HTTP 200만으로 성공을 판단하지 않습니다.**

| 대상 | 긍정 검증 | 부정 검증 |
|---|---|---|
| APIM REST-to-MCP | 실제 REST 기준 응답, mapped tool, generated schema, 호출 결과와 backend invocation marker | 익명 initialize/list/call, ARM audience 토큰, 직접 REST 보호 |
| APIM Learn 프록시 | 실제 Learn 도구 조회·검색 | 익명·잘못된 audience, 원본 Entra 토큰의 외부 전달 금지 |
| 공식 Azure MCP | 실제 사용자 토큰과 읽기 도구, OBO에 의한 Azure 결과 | custom API 토큰·ARM 토큰·익명 요청 거부 |
| Python MCP | 가상 재고, 고정된 실습 RG의 OBO 조회, 실제 Learn 검색 | 만료·서명·issuer·tenant·scope·audience 오류, app-only 토큰 |
| 로컬 AKS MCP | 지정된 실습 kubeconfig에서 실제 읽기 도구 | 다른 기본 context 사용 금지, 원격 HTTP 서버로 오인 금지 |
| GitHub MCP | 실제 GitHub 자격 증명으로 공개 실습 저장소의 읽기 작업 | Entra 토큰으로 GitHub 인증을 대신하는 구성 금지 |

MCP Python SDK v2는 현재 사양과 이전 사양을 구분합니다. 연결별 실제 `protocol_version`을 기록하고, 최신 `server/discover` 방식과 기존 `initialize` 방식을 혼동하지 않습니다. MCP Python SDK 2.x를 설치했다는 사실만으로 APIM·Learn·Azure MCP가 모두 같은 최신 revision을 사용한다고 판단하지 않습니다.

## 증거와 테스트

```bash
python -m pytest "$LAB_SAMPLE/tests" -q
python "$LAB_SAMPLE/evidence.py" \
  "$LAB_SAMPLE/evidence/auth-local-live.json" \
  "$LAB_SAMPLE/evidence/auth-local-live.html"
```

증거 수집기는 사전 승인한 숫자·불리언·protocol revision·오류 코드만 저장합니다. 원본 응답, 토큰, tenant/subscription ID, 실제 hostname은 허용하지 않습니다. HTML을 브라우저에서 캡처할 때도 **실제 수집 결과의 정규화 화면**임을 표시합니다. Azure Portal 화면이나 실측하지 않은 실행 결과를 흉내 내지 않습니다.

로컬 단위 테스트, 실제 클라우드에서 수행한 토큰 검사, 호스팅된 MCP의 end-to-end 검사를 별도 결과로 남깁니다. 두 번째 사용자, 회사 VPN, 대화형 OAuth/PKCE를 실행하지 않았다면 그 사실도 기록합니다.

## 정리와 재개

먼저 로컬 port-forward를 종료합니다. 새 RG만 지웠다고 모든 실습 객체가 없어지는 것은 아닙니다.

```bash
python -m cleanup --state "$LAB_STATE"
```

위 명령은 삭제 없는 소유권 확인입니다. 검토 후 실제 삭제하려면 private state의 lab suffix를 명시적으로 확인합니다.

```bash
python -m cleanup --state "$LAB_STATE" \
  --confirm-delete "$(jq -r .suffix "$LAB_STATE")"
```

1. 비공개 상태에서 **이번 실행이 만든 RG와 세 앱의 객체 ID**를 확인합니다.
2. 실습 RG를 삭제하고 AKS·Container Apps가 관리하는 RG의 정리 완료를 확인합니다.
3. 이번 실습이 만든 Entra 앱·서비스 주체·사용자 동의·federated credential을 정리합니다.
4. 비공개 상태, 짧은 수명의 실습 secret, kubeconfig와 남은 빌드·진단 파일의 보관 필요성을 확인합니다.

기존 조직 앱·동의나 이름이 비슷한 다른 RG를 일괄 삭제하지 않습니다. PR을 열거나 머지하는 행위는 Azure 리소스와 Entra 객체를 정리하지 않습니다.

재개할 때는 새 계획으로 기존 RG를 가져오지 말고 원래 비공개 상태를 사용합니다. 토큰 만료·Conditional Access·동의 오류는 정상적으로 표면화해야 하며, 동일한 실패 토큰을 무한 재시도하거나 app-only 권한으로 우회하면 안 됩니다.

## 관련 문서

- [설계 선택과 지원 범위](../../../research/azure-api-management/mcp-authentication-options/index.md)
- [Entra와 내부망 구성 가이드](../../../guides/azure-api-management/mcp-entra-private-access/index.md)
- [실제 실행과 검증 기록](../../../cases/azure-api-management/mcp-entra-validation/index.md)
