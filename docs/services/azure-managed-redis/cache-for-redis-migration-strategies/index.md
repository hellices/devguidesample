---
title: Azure Cache for Redis에서 Azure Managed Redis로 이전하는 전략
description: 데이터 정합성과 쓰기 중단 시간을 기준으로 RDB, RIOT-X, dual-write, 엔드포인트 전환을 비교합니다.
document_type: guide
services: [azure-managed-redis]
technologies: [redis]
tags: [migrate, evaluate]
status: needs-review
verification_status: needs-review
sources_checked_at: 2026-09-28
official_sources:
  - title: Migration options - Migrate from Basic, Standard, and Premium tiers to Azure Managed Redis
    url: https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-options
  - title: Plan execution - Migrate from Basic, Standard, and Premium tiers to Azure Managed Redis
    url: https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-self-service
  - title: Import and Export data in Azure Managed Redis
    url: https://learn.microsoft.com/azure/redis/how-to-import-export-data
  - title: How to configure Azure Cache for Redis
    url: https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure
last_verified: 2026-09-28
review_cycle_days: 180
applies_to: [Azure Cache for Redis Basic/Standard/Premium에서 Azure Managed Redis로 이전]
---

# Azure Cache for Redis → Azure Managed Redis 이전 전략

| 방법·원문 | 데이터 정합성 | 실시간성·쓰기 중단 | 장점 | 한계 |
|---|---|---|---|---|
| [RDB export/import](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-self-service#export-and-import-data-using-an-rdb-file) | 스냅샷 시점까지만 보존 | 무손실 전환 시 export부터 전환까지 쓰기 중단 필요 | 절차 단순, 키 전체를 스냅샷으로 이전 | **원본 Premium만** export 지원; 이후 변경분 미반영, 대용량일수록 중단 길어짐 |
| [RIOT-X 초기 복사](https://redis.github.io/riotx/replication/overview.html) | 복사 중 바뀐 키의 최종 상태 보장 불가 | 복사 중 원본 사용 가능; 최종 동기화는 별도 | 기존 데이터를 온라인으로 백필 | 복사 시간·부하, 쓰기·삭제·TTL 변경 확인 필요 |
| [RIOT-X live](https://redis.github.io/riotx/replication/modes.html) | **무손실 보장 없음**: 변경 알림 유실 가능 | 초기 복사와 변경분 추적; 짧은 전환 가능성 | 중단 시간을 줄이는 보조 수단 | 원본 keyspace notifications 필요; 유실·처리 지연 시 재검증 필요 |
| [백필 + 애플리케이션 dual-write](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-self-service#dual-write-strategy) | 쓰기·삭제·TTL을 빠짐없이 반영하고 검증할 때 확보 가능 | 백필 중 서비스 지속; 마지막 전환만 제어 | 전환 순서와 시점 통제 | 앱 수정·양쪽 운영 필요; 기존 키는 dual-write만으로 이전되지 않음 |
| [AMR migration scripts](https://github.com/AzureManagedRedis/amr-migration-scripts) | **데이터 복사 없음** | DNS/접속 대상 전환 시 잠깐 재연결 | 기존 호스트명·액세스 키 유지 | 별도 데이터 이전 필수; preview, 전환 시점 통제 불가 |

**두 축의 의미:** 정합성은 *전환 후 누락·오래된 데이터가 허용되는가*, 실시간성은 *운영 중 복사·변경 추적이 가능한가*와 *최종 쓰기 중단을 얼마나 줄일 수 있는가*. 어느 방법도 데이터의 중요도와 실제 쓰기량을 대신 판단하지 못함.

## 요구사항별 선택

- **재생성 가능한 캐시:** 새 AMR에 빈 상태로 전환하거나 스냅샷을 미리 적재. 누락·오래된 키의 영향 확인.
- **Premium, 긴 중단 허용, 무손실 필요:** 쓰기 중지 → RDB export → AMR import → 검증 → 전환. 스냅샷 이후 쓰기를 허용하면 무손실 아님.
- **수 GB~수십 GB, 짧은 중단과 높은 정합성 필요:** dual-write 시작 → 기존 키 백필 → 데이터 대조 → 최종 쓰기 제어·잔여 변경분 정리 → 대상 읽기/쓰기 전환. 백필이 최신 쓰기를 덮지 않도록 충돌 순서까지 설계. RIOT-X live는 보조 수단이지 무손실 복제의 근거가 아님.

## 실행 전 확인

1. 원본 **SKU**, 실제 사용 메모리, 키 개수·큰 키, 쓰기/삭제 빈도, TTL과 허용 중단 시간 확인. 원본 Basic은 [keyspace notifications 설정을 지원하지 않아](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure#keyspace-notifications) RIOT-X live 방식의 전제가 맞지 않음.
2. 대상 메모리 여유와 네트워크 경로 확인. [AMR는 메모리 약 20%를 시스템 용도로 예약](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-self-service#step-2-migrate-your-data). 일부 키로 복사 처리량·원본 부하를 실측하고 전체 시간을 산정.
3. 방법별 검증 범위 확정: 키와 값, TTL, 삭제·만료·갱신, 애플리케이션 연결과 재연결. dual-write 시 실패·재시도와 백필/동시 쓰기의 순서까지 검증.
4. 데이터 이전 완료 후 접속 전환. [DNS 전환 도구](https://github.com/AzureManagedRedis/amr-migration-scripts)는 `skipDataMigration = true`로 동작하며, [preview 제한](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-options#limitations)(Private Endpoint·VNet 주입·지역 복제 캐시 등)을 먼저 확인. 지원되지 않으면 앱 연결 설정을 직접 변경.

> **RDB의 시간 함정:** 전송량이 30 GB이고 실제 속도가 20 MB/s라면 *전송만* 약 25분. export·import·검증·전환 시간이 추가됨. 중단 허용 시간이 이 전체보다 짧다면 RDB 단독은 선택지에서 제외.

## RIOT-X란?

[RIOT-X](https://redis.io/docs/latest/integrate/riot/)는 **Redis 공식 문서에 소개된 데이터 입출력 CLI**. Redis 간 키 복사뿐 아니라 파일·데이터베이스와의 데이터 이동도 지원. [Redis 조직의 배포 저장소](https://github.com/redis/riotx-dist)와 [사용 문서](https://redis.github.io/riotx/)는 별도.

- **기본 복사:** 원본 키를 스캔하고 값을 읽어 대상에 기록.
- **`--mode live`:** 초기 복사와 함께 keyspace notifications로 변경된 키를 추적. 알림 유실 가능성 때문에 무손실 복제 아님.
- **`--struct`:** Redis 버전 간 DUMP 형식이 호환되지 않을 때 데이터 구조별 명령으로 이전. [Microsoft의 AMR 이전 예시](https://techcommunity.microsoft.com/blog/azure-managed-redis/data-migration-with-riot-x-for-azure-managed-redis/4404672)에서도 권장.

**구분:** RIOT-X는 데이터 복사 도구. Azure의 [AMR migration scripts](https://github.com/AzureManagedRedis/amr-migration-scripts)는 데이터가 아닌 접속 대상 전환 도구.

## 참고

- [Microsoft Learn: 이전 옵션과 도구 제한](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-options)
- [Microsoft Learn: 데이터 이전 전략](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-self-service#step-2-migrate-your-data)
- [Microsoft Learn: AMR import 동작과 RDB 호환성](https://learn.microsoft.com/azure/redis/how-to-import-export-data)
- [RIOT-X: live 모드의 정합성 제한](https://redis.github.io/riotx/replication/modes.html)
- [RIOT-X: 버전 차이 시 `--struct` 방식](https://redis.github.io/riotx/replication/types.html)
- [실측: RIOT-X 초기 복사와 live 모드](../riotx-migration-poc/index.md)
