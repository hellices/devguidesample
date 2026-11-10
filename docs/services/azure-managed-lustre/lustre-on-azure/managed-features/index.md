---
title: 'Azure Managed Lustre 관리형 기능: 처리량 tier·Blob HSM 통합·보안·운영 범위'
description: Azure Managed Lustre가 오픈 소스 Lustre 위에 더하는 처리량 tier, Blob Storage HSM 통합, 암호화·root squash, 유지 관리·모니터링·확장 기능과 단일 영역 내구성 같은 제약을 비교합니다.
document_type: research
services: [azure-managed-lustre, azure-storage]
technologies: [lustre]
tags: [evaluate, storage]
status: current
verification_status: needs-review
sources_checked_at: 2026-11-10
published_at: 2026-11-10
topic_order: 2
official_sources:
  - title: What is Azure Managed Lustre?
    url: https://learn.microsoft.com/azure/azure-managed-lustre/amlfs-overview
  - title: Azure Managed Lustre file system prerequisites
    url: https://learn.microsoft.com/azure/azure-managed-lustre/amlfs-prerequisites
  - title: Connect clients to an Azure Managed Lustre file system
    url: https://learn.microsoft.com/azure/azure-managed-lustre/connect-clients
  - title: Troubleshoot Azure Managed Lustre deployment issues
    url: https://learn.microsoft.com/azure/azure-managed-lustre/troubleshoot-deployment
  - title: Create an Azure Managed Lustre file system by using the Azure portal
    url: https://learn.microsoft.com/azure/azure-managed-lustre/create-file-system-portal
  - title: Create an Azure Managed Lustre file system by using Azure Resource Manager templates
    url: https://learn.microsoft.com/azure/azure-managed-lustre/create-file-system-resource-manager
  - title: Use Azure Blob Storage with Azure Managed Lustre
    url: https://learn.microsoft.com/azure/azure-managed-lustre/blob-integration
  - title: Import data from Azure Blob Storage
    url: https://learn.microsoft.com/azure/azure-managed-lustre/import-data
  - title: Export data to Azure Blob Storage
    url: https://learn.microsoft.com/azure/azure-managed-lustre/export-data
  - title: Restore data from Blob Storage
    url: https://learn.microsoft.com/azure/azure-managed-lustre/restore-data
  - title: Use customer-managed encryption keys with Azure Managed Lustre
    url: https://learn.microsoft.com/azure/azure-managed-lustre/customer-managed-encryption-keys
  - title: Configure root squash settings for Azure Managed Lustre file systems
    url: https://learn.microsoft.com/azure/azure-managed-lustre/root-squash-configure-settings
  - title: Enable and validate virtual network encryption with Azure Managed Lustre
    url: https://learn.microsoft.com/azure/azure-managed-lustre/vnet-encryption
  - title: Azure security baseline for Azure Managed Lustre
    url: https://learn.microsoft.com/security/benchmark/azure/baselines/azure-managed-lustre-security-baseline
  - title: Monitor Azure Managed Lustre
    url: https://learn.microsoft.com/azure/azure-managed-lustre/monitor-file-system
  - title: Azure Managed Lustre monitoring data reference
    url: https://learn.microsoft.com/azure/azure-managed-lustre/monitor-file-system-reference
  - title: Use quotas in Azure Managed Lustre file systems
    url: https://learn.microsoft.com/azure/azure-managed-lustre/lustre-quotas
  - title: Expand an Azure Managed Lustre file system by using the Azure portal
    url: https://learn.microsoft.com/azure/azure-managed-lustre/expand-file-system-portal
  - title: Use multiple clusters for regional failover recovery
    url: https://learn.microsoft.com/azure/azure-managed-lustre/amlfs-region-recovery
  - title: Optimize file and directory layouts in Azure Managed Lustre
    url: https://learn.microsoft.com/azure/azure-managed-lustre/optimize-file-layouts
  - title: Optimize Azure Managed Lustre performance
    url: https://learn.microsoft.com/azure/azure-managed-lustre/optimize-performance
  - title: Azure Managed Lustre MLPerf Storage v3.0 results
    url: https://learn.microsoft.com/azure/azure-managed-lustre/mlperf-storage-v3-results
  - title: Azure Managed Lustre pricing
    url: https://azure.microsoft.com/pricing/details/managed-lustre/
---

# Azure Managed Lustre 관리형 기능: 처리량 tier·Blob HSM 통합·보안·운영 범위

Azure Managed Lustre(AMLFS)의 핵심 가치는 **Lustre 서버 계층(MGS·MDS·OSS)과 그
패치·디스크 운영을 Microsoft가 맡고, Azure Blob Storage를 HSM 백엔드로 연결해
주는 것**입니다. 반대로 서버 튜닝, LNet 구성, 영역 간 이중화 같은 자체 운영
Lustre의 자유도는 줄어듭니다. 오픈 소스 Lustre의 구조는
[Lustre 아키텍처](../upstream-architecture/index.md), client 연결은
[컴퓨트 연결](../compute-integration/index.md)에서 다룹니다.

| 운영 영역 | 자체 운영 Lustre | Azure Managed Lustre |
|---|---|---|
| 서버 노드 | MGS·MDS·OSS 설치, 커널·ldiskfs/ZFS 관리 | 서비스가 고객 subnet에 배치·관리. 호스트·OS 접근 불가 |
| HA·장애 조치 | Pacemaker·Corosync·STONITH, 공유 스토리지 직접 구성 | 고객이 구성하지 않음. 서비스 내부 HA 방식은 공개 문서에 없음 |
| 디스크 보호 | OST RAID 6, MDT RAID 10 등 직접 설계 | Premium SSD LRS managed disk |
| 용량·성능 단위 | OST·OSS 추가로 설계 | MB/s per TiB tier와 고정 용량 증분 선택 |
| HSM | coordinator·copytool·백엔드 직접 구성 | Blob 컨테이너 지정만으로 import·export 제공 |
| 업데이트 | 직접 계획·적용 | 고객이 정한 유지 관리 창에 대개 3개월마다(필요 시) 적용 |
| 모니터링 | 별도 도구 구성 | Azure Monitor 지표·리소스 로그 |

## 서비스 모델: 고객 subnet의 관리형 서버와 고정 fsname { #service-model }

AMLFS 서버는 고객이 지정한 VNet subnet에 IP를 받아 배치되지만, 고객은 서버
호스트나 OS에 접근할 수 없습니다. subnet에는 모든 OSS, MDS와 데이터 이동용 agent
노드의 IP가 필요하며, 서비스가 만든 `amlfs-*-snic` NIC는 변경하지 않아야 합니다.
client는 MGS IP와 고정 fsname `lustrefs`로 mount합니다.

- Lustre 버전: client 호환 기준으로 **2.15 또는 2.17**(OS에 따라 다름)입니다. 서버 측
  정확한 릴리스와 주 버전 업그레이드 방식은 Learn에 명시되어 있지 않습니다.
- client: Linux만 지원하며, Microsoft가 배포판·커널별 client 패키지를 제공합니다.

## 처리량 tier와 용량 증분: MB/s per TiB SKU { #throughput-tiers }

AMLFS는 Durable SSD 유형에서 TiB당 처리량이 다른 다섯 tier를 제공하며
(`AMLFS-Durable-Premium-<tier>`), 용량은 tier별 고정 증분으로만 늘어납니다. MLPerf
결과 문서는 증분 하나당 공칭 대역폭을 2,000 MB/s로 계산합니다. 이 기준에서 20·40
tier의 공칭 밀도는 tier 이름보다 조금 높은 20.8·41.7 MB/s per TiB입니다.

| tier (MB/s per TiB) | 최소·증분 | 기본 최대 | 최대(Blob 통합) | 최대(Blob 미통합) |
|---|---|---|---|---|
| 20 | 96 TiB | 3,072 TiB | 5,088 TiB | 25,632 TiB |
| 40 | 48 TiB | 1,536 TiB | 2,544 TiB | 12,816 TiB |
| 125 | 16 TiB | 512 TiB | 1,024 TiB | 4,096 TiB |
| 250 | 8 TiB | 256 TiB | 1,024 TiB | 2,048 TiB |
| 500 | 4 TiB | 128 TiB | 1,024 TiB | 1,024 TiB |

- 기본 최대를 넘는 용량은 지원 요청으로 구독을 활성화해야 합니다.
- MDT는 용량 증분마다가 아니라 tier별 용량 간격(20 tier 5,120 TiB, 40 tier 2,560 TiB,
  125·250·500 tier 1,024 TiB)마다 하나씩 자동 추가됩니다. 표의 Blob 통합 최대치는 이
  간격을 각 tier 증분의 배수로 내림한 값이며, 문서는 **Blob 통합 파일 시스템이 두 번째
  metadata server(MDS)를 넘어 확장할 수 없다**고 설명합니다. 그 결과 20·40·125·250 tier는
  Blob 통합 시 최대 용량이 낮아지고, 500 tier는 두 경우 모두 1,024 TiB입니다.
- Microsoft가 공개한 MLPerf Storage v3.0 결과에서 tier 125·4,096 TiB 구성은 학습
  읽기 379.1 GiB/s, checkpoint 쓰기 642.2 GiB/s를 기록했습니다. 16개 시뮬레이션
  가속기 구성에서는 다섯 tier 모두 공칭 대역폭 밀도의 95.6–97.3%를 보였습니다.
  Microsoft는 이 값이 성능 보장이 아니라고 밝힙니다.
- 가격은 tier별 GiB당 시간·월 단가의 종량제입니다. 기준일의 가격 페이지에는 40·125·
  250·500 tier만 표시되어 20 tier 가격은 확인하지 못했습니다.

### AMLFS 20: 대용량·다중 MDS용 20 MB/s per TiB SKU { #amlfs-20 }

"AMLFS 20"은 Lustre 버전이 아니라 **`AMLFS-Durable-Premium-20` SKU**, 즉 위 표의
20 MB/s per TiB tier를 가리킵니다. Microsoft는 2025-11-18 Tech Community 블로그
[Announcing the Public Preview of AMLFS 20](https://techcommunity.microsoft.com/blog/azurehighperformancecomputingblog/announcing-the-public-preview-of-amlfs-20-azure-managed-lustre-new-sku-for-massi/4470665)에서
이 SKU를 public preview로 발표했습니다. 블로그가 밝힌 특징은 다음과 같습니다.

- 단일 namespace 최대 25 PiB, 총 대역폭 최대 512 GB/s
- 프로비저닝 용량 5 PiB마다 MDS를 하나씩 추가하는 다중 MDS 구조로, mdtest에서
  metadata 연산이 5배 이상 향상
- 최대 200억 inode
- 이전에는 12.5 PiB를 넘는 데이터셋에 여러 파일 시스템이 필요했던 부분을 단일 파일
  시스템으로 대체
- 초기 사용은 신청 양식으로 접수

TiB당 처리량이 가장 낮은 대신 용량 상한이 가장 높아, 대역폭보다 데이터셋 크기와 파일
수가 큰 AI 데이터 준비·대규모 HPC 데이터셋에 맞춘 SKU입니다. Learn의 tier 표에서 20
tier의 Blob 미통합 최대 25,632 TiB와 MDT 추가 간격 5,120 TiB(5 PiB)는 블로그의
25 PiB·5 PiB당 MDS와 일치합니다.

## Blob Storage 통합: Lustre HSM 기반 import·export { #blob-hsm }

Blob 통합은 **Lustre HSM을 서비스가 대신 구성한 기능**입니다. 오픈 소스 Lustre에서
직접 운영해야 하는 coordinator·copytool·백엔드 연결을 컨테이너 지정만으로 대체합니다.
단, **파일 시스템을 만들 때만** 켤 수 있고 이것이 HSM 기능을 쓰는 유일한 방법입니다.

| 기능 | 동작 | 주요 제약 |
|---|---|---|
| 초기 import | 생성 시 지정한 prefix의 namespace와 metadata만 가져오고, 파일 내용은 첫 접근 때 읽어 옴 | prefix는 생성 후 변경 불가. 배포 완료가 import 완료보다 먼저 보고될 수 있음 |
| 수동 import job | 충돌 모드(fail·skip·overwrite-dirty·overwrite-always)와 오류 허용 수준 지정 | 포털 기준 prefix 최대 10개 |
| 사전 적재(restore) | `lfs hsm_restore`로 내용을 미리 가져옴 | 최대 약 7.5 GiB/s |
| auto-import | Blob change feed로 컨테이너 변경을 계속 반영 | 계층 네임스페이스 계정 미지원, change feed 보존 7일 이상, 실행 중 `lfs hsm_*` 사용 금지 |
| export job | 새로 만들거나 바뀐 파일을 Blob으로 복사 | metadata만 바뀐 파일·이름 변경·삭제는 반영 안 함. hard link는 개별 blob |
| auto-export | export를 반복 실행해 지속 동기화 | metadata·삭제 미동기화. 파일 시스템이나 Blob 통합을 삭제하기 전 마지막 성공 반복 시각과 실패 파일 수 0을 확인하고 auto-export를 중지 |

- 네 종류 job(수동 import·수동 export·auto-import·auto-export)은 **한 번에 하나만**
  실행됩니다.
- 사전 조건: "HPC Cache Resource Provider" 서비스 주체에 Storage Account
  Contributor·Storage Blob Data Contributor 역할, 저장소 계정 키 접근 허용, 같은
  계정의 데이터·로그 컨테이너 2개, 컨테이너 익명 접근 비공개.
- 계층 네임스페이스와 평면 네임스페이스 계정을 모두 지원하지만, auto-import는 계층
  네임스페이스 계정에서 쓸 수 없습니다.
- POSIX 소유자·그룹·권한은 blob metadata로, 디렉터리는 `hdi_isfolder` 빈 blob으로
  보존됩니다.

## 보안: 저장 암호화·CMK·root squash·VNet 격리 { #security }

AMLFS는 저장 데이터를 기본 암호화하고, 데이터 평면 접근 제어는 Lustre의 POSIX
UID·GID 모델과 VNet 격리를 따릅니다.

| 영역 | 내용 |
|---|---|
| 저장 암호화 | Microsoft 관리 키 기본 적용, managed disk에 VM host encryption |
| 고객 관리 키(CMK) | **생성 시에만** 설정. Key Vault RSA 2048 키와 사용자 할당 managed identity 필요, 이후 키 유형·identity 변경 불가 |
| root squash | Lustre nodemap 기반, REST API `rootSquashSettings`로 `RootOnly`·`All`·`None`(기본) 지정 |
| 네트워크 | 고객 VNet에 배치, IPv4 전용, Lustre 포트 TCP 988·1019–1023 |
| 전송 중 암호화 | 지원 VM 계열에서 VNet encryption(DTLS 1.2)으로 client 트래픽 암호화. `AllowUnencrypted` 모드만 지원해 AMLFS가 암호화를 강제하지 않으며, 배포 후 켜면 유지 관리 이벤트와 클러스터 재부팅 뒤 적용 |
| 데이터 상주 | 배포 리전 밖에 고객 데이터를 저장하지 않음 |

Azure 보안 기준선은 데이터 평면 Entra ID 인증·Azure RBAC, Customer Lockbox, 서비스
기본 백업을 지원하지 않는다고 표시합니다. 다만 이 기준선은 MCSB v1.0 기반이라
최신이 아닐 수 있다고 스스로 밝히며, "전송 중 암호화 미지원" 항목은 별도 Learn 문서의
VNet encryption 지원과 맞지 않습니다.

## 운영: 유지 관리 창·Azure Monitor·quota·확장 { #operations }

AMLFS는 업데이트와 관측을 Azure 표준 운영 체계에 맞춰 제공합니다.

- **유지 관리 창**: 요일과 UTC 시각을 필수로 지정합니다. 보안 업데이트와 Lustre 코드
  수정이 대개 3개월마다 적용되며, 그동안 I/O가 일시 중단될 수 있습니다. Service Health
  알림으로 예정 업데이트를 받을 수 있습니다.
- **모니터링**: OST·MDT 용량과 파일 수, client 지연·처리량, HSM 요청, eviction,
  rebalancer 지표를 1분 단위 플랫폼 지표로 제공하고, 감사 로그는 `AFSAuditLogs`
  테이블로 보냅니다. Microsoft는 OST 사용률 85% 경보를 예시로 듭니다.
- **quota**: 표준 `lfs setquota`로 사용자·그룹·프로젝트별 블록·inode 한도를 지정합니다.
  root에는 적용되지 않으며 기본 유예 기간은 1주입니다.
- **확장**: 온라인 확장은 GA이며 지원 요청으로 구독을 활성화해야 합니다. 축소는 할 수
  없고 최종 용량 기준으로 과금됩니다. 확장 뒤 데이터·metadata **rebalancing은 public
  preview**입니다.

## 내구성·가용성: 단일 영역 LRS 디스크와 Blob 기반 복구 { #durability }

AMLFS 파일 시스템은 가용성 영역을 지원하는 리전에서 **항상 하나의 영역**에 배치되고,
Durable 유형은 Premium SSD **LRS** managed disk를 사용합니다. 영역·리전 수준
이중화가 필요하면 Blob Storage 통합으로 ZRS·GRS 계정에 데이터를 내보내야 합니다.

리전 장애 복구도 자동 장애 조치가 아니라, 다른 리전 Blob에 데이터를 보관해 두었다가
보조 리전에 새 AMLFS를 만들고 import한 뒤 모든 client가 **새 mount 주소**로 다시
mount하는 절차입니다. 따라서 AMLFS를 원본 저장소가 아니라 **Blob 앞단의 고성능
작업 계층**으로 설계하는 것이 문서의 권장 방향과 일치합니다(설계 해석).

## 자체 운영 Lustre 대비 제약 { #constraints }

관리형 모델의 대가로 다음 선택지는 고객이 바꿀 수 없습니다.

- 서버 측 Lustre 튜닝, backend 파일 시스템 선택, LNet 네트워크 유형(문서의 mount 예시는
  모두 `@tcp`이며 `o2ib` 등은 문서화되지 않음)
- 생성 후 변경할 수 없는 항목: VNet·subnet, Blob 통합 여부와 초기 import prefix,
  CMK 사용 여부와 identity, 용량 축소
- 단일 영역 배치와 LRS 디스크, 서비스 기본 백업 부재
- Blob 통합 시 MDS 2개 한도와 낮은 최대 용량, 한 번에 하나의 HSM job
- client는 Linux 전용이며 Kubernetes는 AKS만 지원

## 해석 제한과 미확인 사항 { #limitations }

- 서버 측 Lustre 정확한 릴리스, 주 버전 업그레이드 방식, 지원 리전 목록, 영역 중복
  옵션은 Learn 문서에서 확인하지 못했습니다.
- auto-import·auto-export는 preview 표시가 없지만 GA라고 명시된 문구도 찾지 못했습니다.
- Resource Manager 템플릿 문서는 SKU 표에 20 tier를 포함하지만 허용 SKU 이름 목록에는
  빠져 있어 문서 내부가 일치하지 않습니다.
- **20 tier(AMLFS 20)의 preview·GA 상태**: 블로그는 2025-11-18에 public preview로
  발표했고, 기준일의 Learn tier 표는 preview 표시 없이 20 tier를 나열합니다. 반면 가격
  페이지, Resource Manager 템플릿의 허용 SKU 목록, Azure Lustre CSI driver v0.6.0의
  동적 프로비저닝 허용 `sku-name` 목록에는 20 tier가 없습니다. GA 여부와 구독별 사용
  가능 여부는 배포 전에 확인해야 합니다.
- Learn은 MDT 추가 간격(MDT 단위)과 Blob 통합 한도(MDS 단위)를 다른 단위로 설명하며,
  정확한 용량 경계에서 몇 개의 MDS·MDT가 배치되는지는 명시하지 않습니다. 배포 후 MDT
  수는 mount한 client에서 `lfs df -h`로 확인합니다.
- MLPerf 수치는 Microsoft가 공개한 시험 구성의 결과이며 이 문서에서 재측정하지
  않았습니다.

## 공식 출처

이 문서의 주장은 front matter `official_sources`에 기록한 Microsoft Learn 원문과
Azure 가격 페이지와 대조했습니다. 2026-11-10에 각 문서를 전체 조회했습니다.
