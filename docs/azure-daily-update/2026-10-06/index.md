---
title: Azure Daily Update — 2026-10-06
description: 2026-10-06 Azure 업데이트 요약
report_date: 2026-10-06
generated_at: 2026-10-07T18:46:40+09:00
---

# Azure 일일 업데이트 브리핑 — 2026-10-06

- **조사 대상:** 2026-10-06 00:00–23:59 (Asia/Seoul)
- **AI & Apps:** 1건
- **Infra:** 1건
- **Database:** 3건
- **총계:** 5건
- **핵심 한 줄:** 데이터베이스의 지역·백업 선택지가 늘고, Application
  Gateway WAF의 IPv6 보호 범위가 프리뷰로 확대됐습니다.

!!! note "검증 범위"
    Azure Updates 개별 링크는 2026-10-07 확인 시 업데이트 상세 대신 공통
    보안 안내 페이지로 이동했습니다. 항목의 날짜·제목·분류·요약은 Microsoft
    공식 Azure service updates RSS에서 확인했고, 스포트라이트의 제품
    동작·지원 범위·제한은 Microsoft Learn 원문 전체와 대조했습니다.

## AI & Apps

| 상태 | 서비스 | 업데이트 | 범위와 핵심 변경 |
|---|---|---|---|
| Public Preview | Microsoft Fabric | [Table discovery in OneLake Catalog search](https://azure.microsoft.com/updates?id=573875) | 2026-10-15부터 semantic model, lakehouse, mirrored database의 table이 개별 검색 결과로 노출됩니다. table 이름·설명 또는 정확한 column 이름으로 global search와 Search API에서 찾을 수 있습니다. |

## Infra

| 상태 | 서비스 | 업데이트 | 범위와 핵심 변경 |
|---|---|---|---|
| Public Preview | Azure Application Gateway WAF | [IPv6 support for Application Gateway WAF](https://azure.microsoft.com/updates?id=573861) | Application Gateway v2의 dual-stack frontend로 들어오는 IPv6 트래픽에 WAF 검사와 적용을 제공합니다. IPv6 geo-based custom rule은 별도 preview feature 등록이 필요합니다. |

## Database

| 상태 | 서비스 | 업데이트 | 범위와 핵심 변경 |
|---|---|---|---|
| Public Preview | Azure HorizonDB | [Azure HorizonDB expands to additional regions](https://azure.microsoft.com/updates?id=572940) | PostgreSQL workload를 애플리케이션과 사용자에 더 가까운 Azure region에 배치할 수 있도록 프리뷰 가용 지역을 확대했습니다. 정확히 어느 region이 이번에 추가됐는지는 개별 업데이트 원문 리디렉션 문제로 **확인 필요**입니다. |
| Generally Available | SQL Server on Azure Virtual Machines | [SQL Server on Azure Virtual Machines in Azure Bleu](https://azure.microsoft.com/updates?id=571499) | SQL Server on Azure Virtual Machines를 프랑스 sovereign cloud 환경인 Azure Bleu에서 사용할 수 있습니다. |
| Public Preview | Azure Backup / Azure Database for PostgreSQL | [Azure Backup for PostgreSQL flexible server and elastic cluster (v2)](https://azure.microsoft.com/updates?id=573425) | `pg_dump` 기반 v1 대신 managed disk snapshot 기반 physical backup을 사용하며, flexible server와 elastic cluster에 vaulted long-term retention을 제공합니다. |

## 오늘의 스포트라이트

### 1. Azure Backup for PostgreSQL v2: 논리 백업에서 snapshot 기반 보호로

**무엇이 바뀌었나**

v2 프리뷰는 v1의 논리 `pg_dump` 방식 대신 managed disk snapshot 기반
physical backup을 사용합니다. 첫 백업은 전체 데이터를 전송하고 이후 백업은
변경 block만 증분 전송합니다. 보호 대상도 flexible server뿐 아니라 elastic
cluster까지 확장됩니다.

**왜 중요한가**

- v1의 최대 1 TB에서 Premium SSD v1은 32 TB, Premium SSD v2는 64 TB까지
  지원 범위가 커집니다.
- weekly full backup만 제공하던 v1과 달리 daily·weekly schedule, on-demand
  backup, 7일에서 10년까지의 독립 retention을 지원합니다.
- restore 결과를 storage container의 file로 받은 뒤 수동 import하는 대신,
  미리 만든 target server 또는 cluster에 `Restore as Server`로 복원합니다.
- Backup vault의 RBAC, soft delete, multi-user authorization과 WORM
  immutability를 적용할 수 있어 장기 보존과 삭제 방어에 유리합니다.

**대상과 전제 조건**

- PostgreSQL 15 이상
- General Purpose 또는 Memory Optimized compute tier
- Premium SSD v1 최대 32 TB 또는 Premium SSD v2 최대 64 TB
- primary server만 지원하며 read replica·geo-replica는 보호할 수 없음
- Backup vault는 datasource와 같은 region이어야 하며, 같은 tenant 안에서
  다른 subscription 사용 가능
- datasource 하나당 backup instance 하나만 허용되며 v1과 v2로 동시에
  보호할 수 없음

**도입 시 확인할 사항**

- Burstable tier와 PostgreSQL 14 이하는 지원되지 않습니다.
- database·table·object 단위 backup/restore는 지원되지 않습니다.
- restore target은 비어 있어야 하며 source와 같은 PostgreSQL major
  version·disk type·disk size를 사용해야 합니다. target에는 HA와
  geo-replica 구성이 없어야 합니다.
- 큰 server의 initial backup이나 높은 daily churn에서는 1일 RPO가 보장되지
  않을 수 있습니다.
- 비용은 protected instance fee와 vault에 저장된 backup storage fee로
  구성되므로 retention policy가 장기 비용을 좌우합니다.
- v1에서 v2로 이동한 뒤 v1으로 돌아가려면 protection을 중지하고 v1을 다시
  구성해야 합니다.

**다음 단계**

1. server version, tier, disk type·size와 region을 support matrix에서
   확인합니다.
2. non-production server에서 Backup vault 권한과 daily policy를 구성합니다.
3. 실제 restore target을 미리 만들고 복원 시간과 애플리케이션 전환 절차를
   측정한 뒤 v1에서 migration합니다.

### 2. Application Gateway WAF의 IPv6 inspection과 enforcement

**무엇이 바뀌었나**

Application Gateway WAF가 dual-stack Application Gateway의 IPv6
트래픽을 검사하고 적용하는 기능을 Public Preview로 제공합니다. managed
rule set 기반 IPv6 inspection, non-geo IPv6 custom rule, logging과
diagnostics에는 별도 feature registration이 필요하지 않습니다.

**왜 중요한가**

IPv6 frontend를 연 서비스가 IPv4와 별도의 우회 경로를 만들지 않고 같은 WAF
policy와 관측 체계로 트래픽을 보호할 수 있습니다. geo-based custom rule도
`AllowAppGwWafIpv6Geo` preview feature를 등록하면 IPv6 평가에 사용할 수
있습니다.

**대상과 가용성**

- Application Gateway v2 SKU
- IPv4와 IPv6를 함께 사용하는 dual-stack Application Gateway
- IPv6 Application Gateway 자체는 Application Gateway v2가 지원되는 모든
  public cloud region과 Azure Government, Microsoft Azure operated by
  21Vianet에서 제공됨
- WAF의 IPv6 기능은 Public Preview이며 preview 약관이 적용됨

**제한과 운영 영향**

- 기존 IPv4-only Application Gateway를 dual-stack으로 변환할 수 없으므로
  새 gateway를 배포해야 합니다.
- IPv6-only gateway, IPv6 backend, IPv6 Private Link는 지원되지 않습니다.
- Application Gateway Ingress Controller는 IPv6 구성을 지원하지 않습니다.
- IPv6 geo-based custom rule은 subscription에
  `Microsoft.Network/AllowAppGwWafIpv6Geo`를 등록해야 합니다.
- dual-stack 전환 전 DNS, listener, health probe, WAF log와 IPv4/IPv6
  양쪽 회귀 테스트가 필요합니다.

**다음 단계**

1. 새 v2 dual-stack gateway로의 병행 전환 계획을 세웁니다.
2. managed rule과 non-geo custom rule을 먼저 검증합니다.
3. geo rule이 필요하면 preview feature를 등록하고 WAF log에서 IPv6
   enforcement 결과를 확인합니다.

### 3. Azure HorizonDB의 프리뷰 지역 확대

**무엇이 바뀌었나**

공식 Azure Updates RSS는 Azure HorizonDB의 Public Preview 가용 region이
확대됐다고 안내합니다. Microsoft Learn의 현재 가용 목록은 다음과 같습니다.

- Americas: Canada Central, Central US, East US, West US 2, West US 3
- Europe: Germany West Central, Sweden Central
- Asia Pacific: Australia East, Korea Central

이번 공지에서 새로 추가된 region의 정확한 부분집합은 개별 업데이트 페이지가
상세 본문으로 열리지 않아 **확인 필요**입니다.

**왜 중요한가**

PostgreSQL-compatible workload를 사용자와 가까운 region에 배치할 선택지가
늘어나 latency와 data residency 요구를 맞추기 쉬워집니다. 다만 preview
서비스이므로 production 전환보다 workload 적합성, 연결 방식과 장애 복구
제약을 먼저 검증해야 합니다.

**현재 주요 제한**

- backup retention은 7일로 고정되며 configurable retention과 long-term
  retention은 아직 제공되지 않음
- cross-region read replica와 disaster recovery replication 미지원
- customer-managed key, configurable maintenance window, 내장 PgBouncer,
  index tuning, virtual network injection 미지원
- private connectivity는 Private Link를 사용
- region별 신규 deployment 제한이 있을 수 있으므로 portal 또는 Azure
  support에서 최종 가용성을 재확인해야 함

**다음 단계**

1. portal에서 subscription별 region 가용성과 quota를 확인합니다.
2. 기존 PostgreSQL client·extension·connection pooling 요구사항을 preview
   cluster에서 검증합니다.
3. cross-region DR이 필수인 workload는 기능이 제공될 때까지 별도 대안을
   유지합니다.

## 출처

- [Azure service updates RSS](https://www.microsoft.com/releasecommunications/api/v2/azure/rss)
  — last build 2026-10-06 22:37:54 UTC; 각 항목 KST 게시 시각과
  `updated` 값을 확인함
- [What's new in Microsoft Fabric?](https://learn.microsoft.com/fabric/fundamentals/whats-new)
  — Microsoft Learn 최종 업데이트 2026-10-03
- [What is Azure HorizonDB (Preview)?](https://learn.microsoft.com/azure/horizondb/overview)
  — Microsoft Learn 최종 업데이트 2026-09-22
- [About Azure PostgreSQL flexible server and elastic cluster vaulted backup
  (v2) (preview)](https://learn.microsoft.com/azure/backup/backup-azure-postgresql-flex-server-elastic-cluster-v2-overview)
  — Microsoft Learn 최종 업데이트 2026-09-29
- [Support matrix for Azure PostgreSQL flexible server and elastic cluster
  vaulted backup (v2) (preview)](https://learn.microsoft.com/azure/backup/backup-azure-postgresql-flex-server-elastic-cluster-v2-support-matrix)
  — Microsoft Learn 최종 업데이트 2026-09-29
- [Configure Application Gateway with a frontend public IPv6
  address](https://learn.microsoft.com/azure/application-gateway/ipv6-application-gateway-portal)
  — Microsoft Learn 최종 업데이트 2026-08-04
- [IPv6 geo-based custom rules for Azure Web Application Firewall
  (preview)](https://learn.microsoft.com/azure/web-application-firewall/ag/custom-rules-geo-based-ipv6)
  — Microsoft Learn 최종 업데이트 2026-10-03

**검증일:** 2026-10-07
