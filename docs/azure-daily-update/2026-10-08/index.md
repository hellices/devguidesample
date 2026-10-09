---
title: Azure Daily Update — 2026-10-08
description: 2026-10-08 Azure 업데이트 요약
report_date: 2026-10-08
generated_at: 2026-10-09T09:04:19+09:00
---

# Azure 일일 업데이트 브리핑 — 2026-10-08

- **조사 대상 기간:** 2026-10-08 00:00–23:59 (Asia/Seoul)
- **AI & Apps:** 2건
- **Infra:** 0건 — 업데이트 없음
- **Database:** 1건
- **총계:** 3건
- **핵심 한 줄:** Anyscale on Azure가 GA로 발표됐으며, Linux용 SQL Server는
  지원 CU에서 `sysadmin` 없이 대량 적재 권한을 부여할 수 있게 됐습니다.

!!! note "조사 방법과 확인 범위"
    Azure Updates 화면이 사용하는 Microsoft 공식
    [Release Communications API](https://www.microsoft.com/releasecommunications/api/v2/azure)에서
    `created` 또는 `modified`가 조사 기간에 속하는 항목을 조회했습니다.
    UTC 범위는 2026-10-07T15:00:00Z 이상, 2026-10-08T15:00:00Z 미만이며,
    응답의 전체 건수 3건과 반환 항목 3건이 일치하고 다음 페이지가 없음을
    확인했습니다. ID로 중복을 제거하고 각 항목을 한 범주에만 배치했습니다.
    AKS에서 실행되는 Anyscale은 주된 용도가 AI·분산 Python 애플리케이션
    플랫폼이므로 AI & Apps로 분류했습니다.

    개별 Azure Updates 링크는 HTTP 200으로 열리지만 초기 HTML에는 상세
    본문이 렌더링되지 않습니다. 같은 화면의 공식 API에서 개별 항목 원문
    전체를 읽고, 공식 RSS의 게시 시각과 대조했습니다. 아래 두 GA 항목은
    UTC로는 10월 7일이지만 한국시간으로는 10월 8일에 게시됐습니다.
    날짜가 모두 없는 항목을 조회한 결과는 0건으로, 날짜 확인 불가로 제외한
    항목은 없었습니다. API의 현재 생성·최종 수정 시각을 기준으로 하며,
    변경 전 본문이나 모든 과거 수정 이력을 복원한 조사는 아닙니다.

    제품 주장은 2026-10-09 Microsoft Learn MCP 검색 후 선택한 6개 문서의
    원문 전체와 대조했습니다. 미확인 가격·버전·이전 제공 이력은
    **확인 필요**로 남겼으며, GA를 프리뷰와 혼용하지 않습니다.

## AI & Apps

| 제목 / Azure Updates 원문 | 제품·서비스 | 상태 | 핵심 변경점 | 적용 지역·대상 | 게시 / 최종 수정 시각 (Asia/Seoul) |
|---|---|---|---|---|---|
| [Generally Available: Anyscale on Azure](https://azure.microsoft.com/updates?id=573744) | Anyscale on Azure, Azure Kubernetes Service (AKS) | GA | 고객 AKS에서 Ray 기반 분산 Python 워크로드를 실행하는 관리형 플랫폼이 GA로 발표됐습니다. Azure Native Integration으로 Azure 서비스와 연동합니다. | 지원 리전의 AKS·AI/ML 및 분산 Python 워크로드. 리전 목록은 아래 스포트라이트 참조. | 2026-10-08 02:06:00 / 동일 |
| [Announcing: Multiparty private offers in Microsoft Marketplace expands to Hong Kong](https://azure.microsoft.com/updates?id=571831) | Microsoft Marketplace | Announcement, Effective (2026-10); GA/Preview 구분은 확인 필요 | 소프트웨어 회사와 채널 파트너가 고객에게 공동으로 판매하는 multiparty private offers의 지원 시장이 Hong Kong SAR로 확대됐습니다. 공식 문서의 지원 국가 표에서 홍콩 고객과 채널 파트너 모두 지원됨을 확인했습니다. | 홍콩의 고객 청구 계정·채널 파트너 세금 프로필이 대상이며, 컴퓨팅 리전 확대를 뜻하지 않습니다. [적격 조건](https://learn.microsoft.com/partner-center/marketplace-offers/multiparty-private-offers-overview#supported-countries) 참조. | 2026-10-08 23:17:44 / 동일 |

## Infra

**업데이트 없음.** 조사 대상 기간에 해당하는 항목 중 Infra로 단독 분류한
항목은 없습니다.

## Database

| 제목 / Azure Updates 원문 | 제품·서비스 | 상태 | 핵심 변경점 | 적용 지역·대상 | 게시 / 최종 수정 시각 (Asia/Seoul) |
|---|---|---|---|---|---|
| [Generally Available: Enabling the Bulk admin role for SQL Server on Linux](https://azure.microsoft.com/updates?id=573443) | SQL Server on Linux | GA | SQL Server 2025 CU9 및 SQL Server 2022 CU27부터 `bulkadmin` 역할 또는 `ADMINISTER BULK OPERATIONS` 권한으로 대량 적재할 수 있습니다. 이전에 필요했던 `sysadmin` 권한을 적재 담당자에게 부여하지 않아도 됩니다. | Linux용 SQL Server의 온프레미스, Azure VM, 컨테이너 배포. 특정 Azure 리전 제한은 원문에 명시되지 않았습니다. | 2026-10-08 01:57:04 / 동일 |

## 오늘의 스포트라이트

신규 플랫폼의 실무 적용 범위와 데이터 적재의 최소 권한 운영 영향을 기준으로
2개를 선정했습니다. 홍콩 Marketplace 확대는 전체 목록에 포함하되 특정
시장에 한정된 변경이므로 심층 항목 수를 억지로 채우지 않았습니다.

### 1. Anyscale on Azure GA: 고객 AKS에서 운영하는 분산 Python 플랫폼

**무엇이 바뀌었나 / 이전 상태 대비 차이**

[Azure Updates 발표](https://azure.microsoft.com/updates?id=573744)는 Anyscale on
Azure의 GA를 명시합니다. Ray 자체나 AKS의 새로운 GA를 뜻하는 발표가 아니라,
Anyscale의 Azure 통합 플랫폼 제공 상태에 관한 발표입니다. 이전 프리뷰의
기간·기능 차이와 기존 고객의 자동 전환 여부는 원문에 없어 **확인 필요**입니다.
[제품 개요](https://learn.microsoft.com/azure/anyscale-on-azure/overview)는
고객 구독의 AKS에서 데이터 평면을 실행하고, Anyscale이 별도의 제어 평면에서
스케줄링·모니터링·작업 관리를 수행하는 구조를 설명합니다.

**중요한 이유 / 사용 사례와 기대 효과**

- 발표 원문은 데이터 준비, 분산 학습, 미세 조정, 강화 학습, 추론 및
  에이전트 실행을 활용 사례로 제시합니다. 대상은 분산 Python 또는 AI/ML
  워크로드를 Azure에서 운영하는 개발팀·ML 플랫폼팀입니다.
- AKS, Blob Storage·ADLS, ACR, Load Balancer 연동과 Microsoft Entra ID
  SSO를 사용할 수 있습니다. 기존 Azure 자원·인증 체계와 연결할 수 있다는
  점이 실무상 이점이며, 정량 성능 개선이나 비용 절감률은 이 발표에서
  검증되지 않았습니다.
  [근거: 제품 개요](https://learn.microsoft.com/azure/anyscale-on-azure/overview)

**가용성 / 지역 / SKU·버전**

- **GA**입니다. 지원 리전은 West Central US, East US, East US 2,
  West US 2, West US 3, South Central US, West Europe, North Europe,
  Sweden Central, UK South, Australia East, Southeast Asia입니다.
  확인한 목록에는 한국 리전이 없습니다.
- GPU·고성능 VM SKU 가용성과 할당량은 리전별로 다릅니다. 하나의 클러스터를
  여러 리전에 걸쳐 실행하는 것으로 해석하면 안 됩니다.
  [근거: 지원 리전과 지역 제약](https://learn.microsoft.com/azure/anyscale-on-azure/supported-regions)
- 배포 quickstart는 worker당 최소 4 vCPU와 `Standard_D4s_v5` 또는
  동등 사양을 시작점으로 안내합니다. 모든 워크로드에 동일 SKU가 최적이라는
  뜻은 아니며, 최소 Ray·Kubernetes 버전과 워크로드별 GPU SKU는
  **확인 필요**입니다.
  [근거: 배포 전제 조건](https://learn.microsoft.com/azure/anyscale-on-azure/quickstart-azure-cli)

**전제 조건 / 제한 / 호환성과 마이그레이션**

- Azure 구독의 Owner 또는 Administrator 역할, 외부 Microsoft Entra
  테넌트의 서비스 주체 생성 권한, 필요한 리소스 공급자 등록과 약관 수락을
  확인해야 합니다. AKS에는 OIDC issuer·workload identity가 필요합니다.
- 워크로드 사용자에게는 Anyscale cloud 리소스의
  **Anyscale Platform Contributor** 역할을 명시적으로 부여해야 합니다.
  quickstart는 head node와 서비스 접근을 위한 ingress/gateway controller도
  요구합니다.
  [근거: quickstart](https://learn.microsoft.com/azure/anyscale-on-azure/quickstart-azure-cli)
- 일반 Anyscale SaaS와 같다고 가정하면 안 됩니다. Azure 통합에는 VM stack,
  Anyscale-hosted cloud, lineage tracking, job queue 및 일부 CLI·조직 설정
  기능 제한이 있습니다. cloud·cloud resource의 생성·삭제는 Azure에서
  관리하며, Anyscale CLI의 해당 관리 명령은 지원되지 않습니다.
  [근거: 제한 사항](https://learn.microsoft.com/azure/anyscale-on-azure/overview#limitations)
- 기존 환경을 옮길 때는 인증·스토리지·이미지·작업 관리 흐름을 비프로덕션에서
  대조해야 합니다. 무중단 이전이나 자동 마이그레이션은 **확인 필요**이며,
  이 발표가 이를 보장하지는 않습니다.

**비용 / 보안 / 운영 영향**

- Anyscale 사용료 외에 고객 구독의 AKS·ACR 등 Azure 자원 비용도 발생합니다.
  구체적인 단가·계약 할인·총비용은 **확인 필요**입니다.
  [근거: 비용 FAQ](https://learn.microsoft.com/azure/anyscale-on-azure/faq#how-much-does-anyscale-on-azure-cost)
- 데이터·워크로드는 선택한 리전의 데이터 평면에 있지만, 제어 평면은
  미국에서 동작하며 시스템 로그·메트릭·클러스터 상태 등 운영 메타데이터가
  이동합니다. 로그 수집을 활성화하면 구조화된 애플리케이션 로그도 포함되므로
  데이터 레지던시·보안 요구사항을 먼저 검토해야 합니다.
  [근거: 데이터 위치와 제어 평면](https://learn.microsoft.com/azure/anyscale-on-azure/supported-regions#data-residency-and-the-control-plane)
- 리소스 정리 시 작업·workspace·service를 먼저 종료하고, cloud resource,
  cloud, AKS 순서로 정리합니다. AKS를 먼저 삭제하면 operator가 워크로드를
  종료하지 못할 수 있습니다.
  [근거: 운영·삭제 FAQ](https://learn.microsoft.com/azure/anyscale-on-azure/faq#in-what-order-should-i-delete-anyscale-on-azure-resources)

**바로 확인하거나 시도할 다음 단계**

1. 지원 리전, CPU/GPU 할당량과 미국 제어 평면으로 이동하는 메타데이터를
   검토합니다.
2. [공식 quickstart](https://learn.microsoft.com/azure/anyscale-on-azure/quickstart-azure-cli)에
   따라 비프로덕션 AKS에서 권한·gateway·cloud 상태를 확인합니다.
3. 대표 Ray 작업 1개로 처리 시간과 전체 Azure·Anyscale 비용을 측정하고,
   기존 실행 방식과 비교한 뒤 프로덕션 도입을 결정합니다.

### 2. SQL Server on Linux: 대량 적재 계정에서 sysadmin 권한 분리

**무엇이 바뀌었나 / 중요한 이유**

이전 Linux용 SQL Server에서 `BULK INSERT`와 `OPENROWSET(BULK...)` 실행에는
`sysadmin` 역할이 필요했습니다. 이제 SQL Server 2022 **CU27 이상** 또는
SQL Server 2025 **CU9 이상**에서는 `bulkadmin` 역할이나
`ADMINISTER BULK OPERATIONS` 권한을 사용할 수 있습니다. ETL·배치 적재
담당자에게 전체 관리자 권한 대신 필요한 적재 권한을 부여할 수 있다는 점이
핵심 보안 변화입니다.
[근거: Azure Updates](https://azure.microsoft.com/updates?id=573443),
[Microsoft Learn 원문](https://learn.microsoft.com/sql/linux/security/bulk-operations?view=sql-server-ver17)

**대상 / 사용 사례 / 가용성 / 지역·SKU·버전**

- **GA**이며 Linux용 SQL Server의 온프레미스, Azure VM, 컨테이너에서
  파일 기반 대량 적재를 수행하는 DBA·데이터 엔지니어링팀이 대상입니다.
  기존 Linux 적재 배치의 권한 축소에 활용할 수 있습니다.
- 지원 시작 버전은 위 CU 기준입니다. Azure SQL Database나 모든 구버전
  Linux SQL Server에 동일하게 적용된다고 해석하면 안 됩니다.
- 발표와 구성 문서에 특정 Azure 리전·VM SKU 제한이나 에디션별 추가 조건이
  명시되지 않았습니다. 개별 에디션·배포 조합의 적격성은 **확인 필요**입니다.
  [근거: 적용 범위와 전제 조건](https://learn.microsoft.com/sql/linux/security/bulk-operations?view=sql-server-ver17)

**전제 조건 / 제한 / 보안**

- Linux 호스트와 SQL Server 인스턴스의 관리 권한으로 초기 설정을 해야
  합니다. 이후 적재 사용자의 SQL 권한, `mssql` 서비스 계정의 파일 읽기 권한,
  관리자 승인 디렉터리 설정을 함께 구성해야 합니다.
- `mssql-conf`의 `bulkadmin.allowedpathslist`로 허용 경로를 지정합니다.
  설정 변경은 즉시 적용되며 SQL Server 서비스 재시작이 필요하지 않습니다.
- 허용 경로는 디렉터리의 절대 경로여야 합니다. 루트 경로, 상대 경로,
  심볼릭 링크와 문서에 열거된 보안 민감 경로는 사용할 수 없습니다.
- 적재 계정에는 대량 작업 권한 외에도 대상 데이터베이스 사용자와 필요한
  테이블 권한을 구성해야 합니다. SQL 권한만 부여하고 파일 접근·경로
  승인을 생략하면 충분하지 않습니다.
  [근거: 파일·경로·SQL 권한 구성](https://learn.microsoft.com/sql/linux/security/bulk-operations?view=sql-server-ver17)

**호환성 / 마이그레이션 / 비용 / 운영 영향**

- 기존 적재 배치는 지원 CU로 업그레이드한 테스트 환경에서 파일 접근과
  테이블 권한을 검증한 뒤 적재 전용 계정으로 전환합니다. 필요한 다른
  관리자 작업까지 담당하는 계정이라면 검토 없이 `sysadmin`을 제거하지
  않습니다.
- CU downgrade 호환성은 **확인 필요**입니다. Learn 문서의 지원 시작
  CU27/CU9와 downgrade 절의 CU24/CU3 경계가 서로 다르므로, 이 브리핑은
  그 사이 버전에서의 권한 동작을 단정하지 않습니다.
  [근거: 업그레이드·다운그레이드 설명](https://learn.microsoft.com/sql/linux/security/bulk-operations?view=sql-server-ver17#upgrade-and-downgrade-behavior)
- 원문에는 이 기능의 추가 요금이나 비용 절감 수치가 없습니다.
  무료라고 단정하지 않으며, 라이선스·호스트·스토리지 비용과 CU 적용
  작업 비용은 별도 **확인 필요**입니다.
- 운영상 기대 효과는 적재 계정의 권한 범위 축소입니다. 배치 성능 향상은
  발표된 내용이 아니므로, 실패율·성능·권한 회귀를 별도로 측정해야 합니다.

**바로 확인하거나 시도할 다음 단계**

1. Linux 인스턴스의 CU 버전과 적재 배치가 사용하는 관리자 작업을
   확인합니다.
2. [공식 구성 문서](https://learn.microsoft.com/sql/linux/security/bulk-operations?view=sql-server-ver17)에
   따라 승인 경로·파일 읽기 권한·적재 전용 SQL 권한을 테스트 환경에
   구성합니다.
3. 두 적재 방식의 정상 동작과 금지 경로의 거부를 확인한 뒤 기존 계정의
   과도한 권한을 축소합니다. downgrade 계획이 있다면 위 CU 경계의
   불일치를 제품 지원에 먼저 확인합니다.

## 출처

확인일은 **2026-10-09 (Asia/Seoul)**입니다. Azure Updates 원문은 공식 API의
전체 본문과 RSS 게시 시각을 함께 확인했으며, Microsoft Learn은 MCP의
`microsoft_docs_search` 후 `microsoft_docs_fetch`로 원문 전체를 조회했습니다.
Learn의 아래 날짜는 원문 HTML의 `ms.date`이며, `updated_at`은 별도로
구분해 기록합니다.

| 출처 | URL | 게시일 또는 문서 날짜 / 최종 수정일 |
|---|---|---|
| Azure Updates — Anyscale on Azure | [원문](https://azure.microsoft.com/updates?id=573744), [공식 전체 본문](https://www.microsoft.com/releasecommunications/api/v2/azure/573744) | 생성·수정 2026-10-07T17:06:00.3228241Z, 한국시간 2026-10-08 02:06 |
| Azure Updates — SQL Server on Linux bulkadmin | [원문](https://azure.microsoft.com/updates?id=573443), [공식 전체 본문](https://www.microsoft.com/releasecommunications/api/v2/azure/573443) | 생성·수정 2026-10-07T16:57:04.0990443Z, 한국시간 2026-10-08 01:57 |
| Azure Updates — Hong Kong multiparty private offers | [원문](https://azure.microsoft.com/updates?id=571831), [공식 전체 본문](https://www.microsoft.com/releasecommunications/api/v2/azure/571831) | 생성·수정 2026-10-08T14:17:44.5087831Z, 한국시간 2026-10-08 23:17 |
| Azure Updates 목록·시각 대조 | [공식 API](https://www.microsoft.com/releasecommunications/api/v2/azure), [공식 RSS](https://www.microsoft.com/releasecommunications/api/v2/azure/rss) | 개별 게시·수정 시각은 위 3개 원문에 기록. 피드 자체의 게시일은 확인 필요 |
| What is Anyscale on Azure? | [Microsoft Learn](https://learn.microsoft.com/azure/anyscale-on-azure/overview) | ms.date 2026-10-05 / updated_at 2026-10-07T13:59:00Z |
| Anyscale on Azure frequently asked questions | [Microsoft Learn](https://learn.microsoft.com/azure/anyscale-on-azure/faq) | ms.date 2026-10-06 / updated_at 2026-10-07T13:59:00Z |
| Anyscale on Azure supported regions | [Microsoft Learn](https://learn.microsoft.com/azure/anyscale-on-azure/supported-regions) | ms.date 2026-10-05 / updated_at 2026-10-07T13:59:00Z |
| Quickstart: Deploy Anyscale on Azure | [Microsoft Learn](https://learn.microsoft.com/azure/anyscale-on-azure/quickstart-azure-cli) | ms.date 2026-10-05 / updated_at 2026-10-07T13:59:00Z |
| Configure bulk import operations for SQL Server on Linux | [Microsoft Learn](https://learn.microsoft.com/sql/linux/security/bulk-operations?view=sql-server-ver17) | ms.date 2026-09-29 / updated_at 2026-09-30T17:42:00Z |
| Multiparty private offers overview | [Microsoft Learn](https://learn.microsoft.com/partner-center/marketplace-offers/multiparty-private-offers-overview) | ms.date 2026-10-06 / updated_at 2026-10-06T22:04:00Z |
