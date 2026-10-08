---
title: Azure Daily Update — 2026-10-07
description: 2026-10-07 Azure 업데이트 요약
report_date: 2026-10-07
generated_at: 2026-10-08T09:04:03+09:00
---

# Azure 일일 업데이트 브리핑 — 2026-10-07

- **조사 대상:** 2026-10-07 00:00–23:59 (Asia/Seoul)
- **AI & Apps:** 2건
- **Infra:** 2건
- **Database:** 1건
- **총계:** 5건
- **핵심 한 줄:** AKS가 하이퍼바이저 없이 베어메탈에서 동작하는 Ubuntu 프리뷰를
  열었고, Azure SQL Database의 Always Encrypted SGX enclave는 2027년 10월
  VBS enclave로 전환이 예고됐습니다.

!!! note "검증 범위"
    Azure Updates 개별 링크(`azure.microsoft.com/updates?id=...`)는
    2026-10-08 확인 시에도 클라이언트 렌더링 페이지만 반환해 상세 본문을
    직접 열 수 없었습니다. 항목의 날짜·제목·분류·요약은 Microsoft 공식 Azure
    service updates RSS에서 확인했고, 스포트라이트의 제품 동작·지원 범위·
    제한·마이그레이션 절차는 Microsoft Learn 원문 전체와 대조했습니다.

## AI & Apps

| 상태 | 서비스 | 업데이트 | 범위와 핵심 변경 |
|---|---|---|---|
| Retirement | Azure App Service (Azure Stack Hub) | [Retirement: Azure App Service on Azure Stack Hub](https://azure.microsoft.com/updates?id=568178) | Azure Stack Hub의 App Service가 2029-09-30에 완전히 폐지됩니다. 2026-09-30부터는 신규 설치가 중단되고 새 릴리스·기능·개선이 제공되지 않으며, 기존 배포는 지원 종료일까지만 유지됩니다. |
| Retirement | Azure App Service | [Retirement: Support for Java 8, 11 and 17 will end on September 1, 2027](https://azure.microsoft.com/updates?id=568585) | 2027-09-01부터 App Service에서 Java 8, 11, 17에 대한 보안 업데이트와 고객 지원이 중단됩니다. 앱은 계속 실행되지만 지원되는 Java 버전으로 업그레이드가 필요합니다. |

## Infra

| 상태 | 서비스 | 업데이트 | 범위와 핵심 변경 |
|---|---|---|---|
| Public Preview | Azure Kubernetes Service (AKS) | [[In preview] Public Preview: AKS on bare metal now on Ubuntu](https://azure.microsoft.com/updates?id=573782) | 고객이 보유한 Ubuntu 24.04.3/24.04.4 LTS 하드웨어에 하이퍼바이저 없이 AKS를 직접 설치하는 기능이 Public Preview로 공개됐습니다. 현재는 East US 리전의 단일 노드 클러스터만 지원됩니다. |
| Retirement | AKS (Azure Monitor 플랫폼 메트릭) | [Retirement: Pod name dimension in AKS pod platform metrics](https://azure.microsoft.com/updates?id=570232) | 2027-09-30부터 `kube_pod_status_phase` 등 AKS pod 플랫폼 메트릭의 pod name 차원 지원이 종료되고 집계(pod 수) 카운터로 전환됩니다. 어느 메트릭이 포함되는지 세부 목록은 원문 리디렉션 문제로 전체를 **확인하지 못했습니다**. |

## Database

| 상태 | 서비스 | 업데이트 | 범위와 핵심 변경 |
|---|---|---|---|
| Retirement | Azure SQL Database | [Retirement: Always Encrypted with Intel SGX Enclaves](https://azure.microsoft.com/updates?id=569236) | Intel SGX 기반 secure enclave 지원이 2027-10-31에 종료되며, DC-series 하드웨어도 단계적으로 폐지됩니다. 고객은 하드웨어에 의존하지 않는 Virtualization-Based Security(VBS) enclave로 전환해야 합니다. |

## 오늘의 스포트라이트

### 1. AKS on bare metal: 하이퍼바이저 없이 고객 소유 Ubuntu 서버에서 Kubernetes 실행

**무엇이 바뀌었나**

AKS가 하이퍼바이저 계층 없이 호스트 운영체제와 하드웨어에서 직접 동작하는
"AKS on bare metal"을 Public Preview로 공개했습니다. Azure Local의 검증된
소형 하드웨어에서는 Azure Linux 3.0을, 고객이 직접 보유한 하드웨어에서는
Ubuntu 24.04.3 LTS 또는 24.04.4 LTS를 호스트 OS로 사용할 수 있습니다.
Azure Arc가 호스트와 클러스터를 Azure에 연결해 수명주기와 정책을 관리합니다.

**왜 중요한가**

- 매장, 공장, 현장 사무소처럼 가상화 계층을 두기 어렵거나 기존 하드웨어를
  재사용해야 하는 edge 환경에서 하이퍼바이저 오버헤드 없이 Kubernetes를
  운영할 수 있습니다.
- Azure Arc 기반 관리로 온프레미스에서도 Azure와 동일한 Kubernetes API와
  도구 경험을 유지합니다.
- Ubuntu 옵션은 호스트를 재이미징하지 않고 기존 인프라에 AKS를 추가할 수
  있어 reimaging 비용과 downtime을 줄입니다.

**대상과 가용성**

- Public Preview이며 자체 선택(opt-in) 방식으로 제공되고 SLA 적용 대상이
  아닙니다.
- Ubuntu 옵션은 East US 리전에서만 사용할 수 있으며, 호스트당 단일 노드
  클러스터 1개만 지원됩니다.
- 클러스터 생성·관리는 Azure CLI 확장(`aksarc`)으로 수행하며, Azure
  portal은 읽기 전용 상태 확인만 제공합니다.
- 기본 Kubernetes 버전은 1.33.3이며 patch 버전 업그레이드만 지원됩니다.

**전제 조건과 제한**

- 최소 사양: x86_64 2 physical core, 4 GB RAM, 256 GB 여유 디스크(권장은
  4 core·8 GB·256 GB 이상).
- 호스트 OS 설치·패치·커널·드라이버 유지관리는 고객 책임이며, AKS는
  Kubernetes 계층만 관리합니다.
- 고정 node/control plane IP와 outbound HTTPS(443) 연결이 필요하며,
  `Microsoft.HybridCompute`, `Microsoft.HybridContainerService`,
  `Microsoft.Kubernetes`, `Microsoft.ExtendedLocation`,
  `Microsoft.HybridConnectivity`, `Microsoft.AzureStackHCI` provider 등록이
  필요합니다.
- 다중 노드 클러스터, 호스트당 다중 클러스터, minor 버전 업그레이드는
  지원되지 않으며 Ubuntu 24.04.5 LTS는 아직 지원되지 않습니다.
- 프리뷰 기간 생성한 클러스터는 GA 전환 시 in-place 업그레이드가 보장되지
  않아 재생성과 워크로드 재배포 계획이 필요할 수 있습니다.

**비용과 운영 영향**

- Public Preview 기간 AKS 클러스터 리소스 자체는 zero-rated billing
  meter로 과금되지 않지만, Arc-enabled 머신과 Monitor·Policy 등 연계
  Azure 서비스는 표준 요금이 적용됩니다.
- 운영팀은 host OS 패치, 네트워크·방화벽 구성, 보안 업데이트 적용을 직접
  수행해야 하므로 기존 AKS(완전관리형) 대비 운영 부담이 늘어납니다.

**다음 단계**

1. East US 리전에서 비프로덕션 Ubuntu 호스트로 사전 요구사항(네트워크,
   provider 등록)을 구성합니다.
2. 단일 노드 제약과 patch 전용 업그레이드가 실제 워크로드 요구사항과
   맞는지 검증합니다.
3. GA 전환 시 클러스터 재생성 가능성을 전제로 백업·재배포 절차를 미리
   준비합니다.

### 2. Azure SQL Database의 Always Encrypted: Intel SGX에서 VBS enclave로 전환 예고

**무엇이 바뀌었나**

Azure SQL Database에서 Always Encrypted with secure enclaves가 사용하는
Intel SGX(DC-series 전용) enclave 지원이 2027-10-31에 종료됩니다. 종료일
이후 DC-series compute tier에 남아 있는 데이터베이스는 Azure가 자동으로
표준 시리즈(non-DC) compute tier로 이동시키고 Virtualization-Based
Security(VBS) enclave를 활성화합니다. VBS는 Windows hypervisor 기반의
software 기술로 특수 하드웨어가 필요하지 않습니다.

**왜 중요한가**

- DC-series 하드웨어는 리전 가용성과 성능 제약이 있던 반면, VBS enclave는
  DTU 모델을 포함한 대부분의 하드웨어 구성에서 사용할 수 있어 선택지가
  넓어집니다.
- SGX enclave는 Microsoft Azure Attestation을 통한 attestation이
  필수였지만, Azure SQL Database의 VBS enclave는 attestation을 지원하지
  않아(미사용) 구성이 단순해집니다.
- 마이그레이션을 미루면 종료일에 자동 전환되므로, 애플리케이션이 VBS
  동작 방식과 호환되는지 사전에 검증하지 않으면 예기치 않은 동작 변경을
  겪을 수 있습니다.

**대상과 가용성**

- 영향 대상은 vCore 구매 모델의 DC-series 하드웨어로 Intel SGX enclave를
  사용 중인 Azure SQL Database뿐입니다. SQL Server 2019 이상은 이미 VBS
  enclave만 지원하므로 영향이 없습니다.
- VBS enclave는 Jio India Central을 제외한 모든 Azure SQL Database
  리전에서 사용할 수 있습니다.

**제한과 호환성**

- DC-series가 아닌 표준 시리즈(Gen5 등)와 DTU 구매 모델은 애초에 Intel
  SGX를 지원하지 않으므로 VBS로만 구성할 수 있습니다.
- 클라이언트 드라이버가 VBS enclave와 attestation 설정을 지원해야 하며,
  SGX 전용으로 구성된 attestation 정책이나 연결 문자열은 제거하거나
  갱신해야 합니다.
- 보안 강도 차이가 있을 수 있으므로(enclave 유형별 공격 표면), 규제·
  컴플라이언스 요구사항이 SGX 수준의 host 격리를 요구한다면 Azure
  Confidential VM의 SQL Server 같은 대안을 검토해야 합니다.

**마이그레이션과 운영 영향**

- 포털, PowerShell 또는 CLI로 데이터베이스/탄력적 풀의 compute tier를
  DC-series에서 표준 시리즈로 변경하면 VBS enclave가 활성화됩니다.
- 2027-10-31 이전에 애플리케이션의 attestation 설정과 connection string을
  점검하고, 영향받는 DC-series 데이터베이스 목록을 먼저 인벤토리해야
  합니다.
- 자동 전환에 의존하면 compute tier 변경 시점을 직접 통제할 수 없으므로,
  유지보수 기간을 정해 계획적으로 전환하는 편이 운영 리스크를 줄입니다.

**다음 단계**

1. Azure portal 또는 스크립트로 DC-series 하드웨어를 사용하는 데이터베이스를
   식별합니다.
2. 비프로덕션 환경에서 표준 시리즈로 compute tier를 변경해 VBS enclave
   동작과 애플리케이션 드라이버 호환성을 검증합니다.
3. 검증 후 production 데이터베이스를 2027-10-31 이전에 순차적으로
   전환합니다.

## 출처

- [Azure service updates RSS](https://www.microsoft.com/releasecommunications/api/v2/azure/rss)
  — 확인 시점 2026-10-08; 각 항목의 `pubDate`/`a10:updated` 값을 Asia/Seoul
  기준으로 환산해 2026-10-07 00:00–23:59 범위를 판정함
- [What is Azure Kubernetes Service on bare metal? (preview)](https://learn.microsoft.com/en-us/azure/aks-hybrid-edge/bare-metal/aks-bare-metal-overview)
  — Microsoft Learn 최종 업데이트 2026-09-22
- [Public preview limitations for AKS on bare metal (preview)](https://learn.microsoft.com/en-us/azure/aks-hybrid-edge/bare-metal/aks-bare-metal-preview-limitations)
  — Microsoft Learn 최종 업데이트 2026-09-22
- [Prepare an Ubuntu Host for AKS on Bare Metal (Preview)](https://learn.microsoft.com/en-us/azure/aks-hybrid-edge/bare-metal/aks-bare-metal-ubuntu-system-requirements)
  — Microsoft Learn 최종 업데이트 2026-09-22
- [Always Encrypted with secure enclaves - SQL Server](https://learn.microsoft.com/en-us/sql/relational-databases/security/encryption/always-encrypted-enclaves?view=sql-server-ver17)
  — Microsoft Learn 최종 업데이트 2026-10-01
- [Enable Always Encrypted with Secure Enclaves - Azure SQL Database](https://learn.microsoft.com/en-us/azure/azure-sql/database/always-encrypted-enclaves-enable?view=azuresql)
  — Microsoft Learn 최종 업데이트 2026-10-01
- [Language Runtime Support Policy - Azure App Service](https://learn.microsoft.com/en-us/azure/app-service/language-support-policy)
  — Microsoft Learn 최종 업데이트 2026-06-12
- [Plan a Migration to Azure App Service from Azure Stack Hub](https://learn.microsoft.com/en-us/azure-stack/operator/app-service-planning-migrate-to-azure)
  — Microsoft Learn 최종 업데이트 2026-07-13
- [Azure Stack Hub - Microsoft Lifecycle](https://learn.microsoft.com/en-us/lifecycle/products/azure-stack-hub)
  — Microsoft Learn 최종 업데이트 2022-10-25(Azure Stack Hub 제품 전체는
  "In Support"이며, App Service 리소스 공급자 개별 폐지 일정은 Azure
  Updates 공지로만 확인됨)

**검증일:** 2026-10-08
