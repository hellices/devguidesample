---
title: RIOT-X로 Azure Cache for Redis에서 Azure Managed Redis로 이전 검증
description: RIOT-X 초기 복사와 live 모드를 실제 Azure 캐시에서 시험한 범위, 처리 시간과 정합성 한계
document_type: research
services: [azure-managed-redis]
technologies: [redis]
tags: [migrate, evaluate]
status: current
verification_status: needs-review
sources_checked_at: 2026-09-28
official_sources:
  - title: Plan execution - Migrate from Basic, Standard, and Premium tiers to Azure Managed Redis
    url: https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-self-service
  - title: How to configure Azure Cache for Redis
    url: https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure
published_at: 2026-09-28
---

# RIOT-X 데이터 이전 실측: 초기 복사와 live 모드

**결론:** 초기 복사는 대량의 키와 값을 옮겼지만, live 모드에서 삭제한 키가 대상에 남음. 짧은 쓰기 중단이 가능하다는 것과 **데이터 정합성이 보장된다는 것은 별개**.

## 실험 조건

| 항목 | 구성 |
|---|---|
| 원본 → 대상 | Azure Cache for Redis **Standard C3** (Redis 6.0.14) → Azure Managed Redis **Balanced B20, NoCluster** (Redis 7.4.3) |
| 이전 도구 | RIOT-X **1.15.1**, TLS, `--struct`, RESP2 |
| live 전제 | 원본 keyspace notifications `KEA` |
| 데이터 | 타입별 시험 키 32개; 대량 시험 키 909,238개 × 4,096바이트 = 약 **3.47 GiB** 값 데이터 |
| 범위 | 단일 테스트 원본·대상, 동일 리전. 운영 트래픽·장애·수십 GB 이전은 미검증 |

## 단계별 결과

| 단계 | 관측 결과 |
|---|---|
| 초기 복사 | string, hash, list, set, sorted set, TTL 키 **32개** 일치 |
| live 변경 | 신규 키·값 갱신·TTL 단축 반영. 원본에서 `DEL`한 키는 **대상에 잔존**; 키 목록 불일치 |
| 대량 적재 | 50만 키 적재 약 **409초**. 100만 키를 목표로 추가 적재 중 원본 메모리 한도 오류로 **909,238개에서 중지**. 실제 저장된 키만 이전 대상으로 사용 |
| 대량 이전 1차 | 50만 키, 8개 작업 스레드에서 대상 읽기 타임아웃으로 실패. **426,770개만 복사된 상태** 확인 |
| 대량 이전 재시도 | 4개 작업 스레드, 읽기/쓰기 배치 50, 명령 타임아웃 5분: 50만 키 전체 패스 **447초**. 이어서 909,238개 전체 패스 **1,024초** |
| 이전 후 검증 | 양쪽 대량 시험 키 **909,238개**. 표본 값 일치, RIOT-X의 대량 키 전체 값 비교 종료 코드 0 |

**시간 해석:** 두 성공 패스 모두 이전 시도의 키가 대상에 있던 상태에서 **다시 실행한 시간**. 빈 대상에 대한 처리량, 운영 환경 SLA 또는 수십 GB 예상 시간으로 환산 불가.

## 정합성 판단

- `--mode live`는 [keyspace notifications](https://redis.github.io/riotx/replication/modes.html)를 이용. 변경 알림은 Pub/Sub 기반이므로 공식 문서도 **알림 유실 가능성과 정합성 미보장**을 명시.
- 이번 환경의 삭제 키 잔존은 실제로 재확인한 결과. 원인별 동작이나 모든 RIOT-X 버전으로 일반화하지 않음. **원본에 없는 키가 대상에 남을 수 있으므로** 원본 키만 순회하는 값 비교 통과만으로 전환 승인 불가.
- 대용량 이전 중 타임아웃이 나면 일부 키가 이전된 상태로 종료될 수 있음. 전체 키 수·값·TTL·삭제 상태를 별도 검증하고, 실패한 배치는 복구 후 다시 이전.
- 무손실 요구라면 [전략 가이드](../cache-for-redis-migration-strategies/index.md)의 백필·dual-write·최종 쓰기 제어 절차를 기준으로 설계.

## 참고 자료

- [Microsoft Learn: Azure Managed Redis 데이터 이전 선택지](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-self-service#step-2-migrate-your-data)
- [Redis: RIOT-X 데이터 복사와 live 모드](https://redis.github.io/riotx/replication/modes.html)
- [Redis: 데이터 구조별 이전 방식](https://redis.github.io/riotx/replication/types.html)
