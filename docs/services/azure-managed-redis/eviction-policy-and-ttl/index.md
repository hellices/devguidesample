---
title: Azure Managed Redis Eviction Policy와 TTL 설계 가이드
description: Azure Managed Redis의 eviction policy 설정과 기본값, allkeys-lru 등 주요 정책의 동작 원리, 일반 캐시·세션·영구 저장소별 권장 정책과 클라이언트 TTL의 의미를 정리합니다.
document_type: guide
services:
- azure-managed-redis
technologies:
- redis
- nodejs
- java
- spring-boot
tags:
- design
- optimize
- operate
status: current
verification_status: verified
sources_checked_at: 2026-10-24
official_sources:
- title: Memory management for Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/best-practices-memory-management
- title: How to configure Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/configure
- title: Configure data persistence for an Azure Managed Redis instance
  url: https://learn.microsoft.com/azure/redis/how-to-persistence
- title: Configure active geo-replication for Azure Managed Redis instances
  url: https://learn.microsoft.com/azure/redis/how-to-active-geo-replication
- title: Azure Managed Redis monitoring data reference
  url: https://learn.microsoft.com/azure/redis/monitor-cache-reference
- title: Azure Managed Redis architecture
  url: https://learn.microsoft.com/azure/redis/architecture
- title: az redisenterprise
  url: https://learn.microsoft.com/cli/azure/redisenterprise
- title: az redisenterprise database
  url: https://learn.microsoft.com/cli/azure/redisenterprise/database
last_verified: 2026-10-24
review_cycle_days: 180
applies_to:
- Azure Managed Redis (Redis 7.4)
related_cases:
- ../cluster-failover-recovery/index.md
related_guides:
- ../cluster-failover-recovery/clustering-policies-and-migration/index.md
---

# Azure Managed Redis Eviction Policy와 TTL 설계 가이드

Redis는 메모리가 가득 차면 **eviction policy**에 따라 키를 지우고, 키에 **TTL**이 있으면 그 시간이 지난 뒤 키를 지웁니다. 두 가지 모두 "키가 사라지는" 동작이지만 목적과 결과가 다릅니다. 이 가이드는 Azure Managed Redis에서 두 동작을 어떻게 설정하고 용도별로 어떻게 조합할지 정리합니다.

!!! warning "Azure Managed Redis의 기본 eviction policy는 `volatile-lru`입니다"
    `volatile-lru`는 **TTL이 있는 키만** 지웁니다. TTL을 걸지 않은 키로 메모리가 가득 차면 지울 키가 없어 쓰기 명령이 오류로 실패합니다. 순수 캐시로 사용한다면 정책을 `allkeys-lru`로 **직접 변경**합니다. `allkeys-lru`는 Redis 공식 문서가 캐시의 기본 선택으로 권장하는 정책입니다.

---

## 한눈에 보기 { #at-a-glance }

| 용도 | 권장 정책 | TTL | 함께 설정할 것 |
|---|---|---|---|
| 일반 캐시 (cache-aside, 원본 DB가 따로 있음) | **`allkeys-lru`** (접근 빈도가 안정적이면 `allkeys-lfu`) | 데이터 신선도 기준으로 설정 권장 | Used Memory Percentage 알림 |
| 세션 저장소 (세션 전용 인스턴스) | **`volatile-lru`** (기본값) 또는 `allkeys-lru` | **모든 세션 키에 필수** (세션 프레임워크가 설정) | Evicted Keys가 0보다 크면 알림, 메모리 여유 확보 |
| 세션 유실을 허용할 수 없는 상태 저장 (장바구니, 결제 진행 상태 등) | **`noeviction`** | 업무 규칙에 따른 만료만 | 영구 저장소와 같은 설정 |
| 영구 저장소 (Redis가 원본 데이터) | **`noeviction`** | 없음 또는 업무 규칙에 따른 만료만 | 데이터 지속성(RDB/AOF), 정기 내보내기, 쓰기 실패 처리 |
| 캐시와 영구 데이터를 한 인스턴스에 혼합 | **`volatile-lru`** | 캐시 키에만 설정, 영구 키에는 설정 안 함 | 가능하면 인스턴스 분리 |
| RediSearch(벡터·전문 검색) 사용 | **`noeviction`** (필수) | 문서 수명에 따라 | Enterprise 클러스터링 정책 필수 |

---

## 1. Eviction과 TTL의 차이 { #eviction-vs-ttl }

| 구분 | TTL(만료) | Eviction(축출) |
|---|---|---|
| 발생 시점 | 키마다 정한 시간이 지났을 때 | 메모리 한도에 도달했을 때 |
| 결정 주체 | 애플리케이션이 키를 쓸 때 정함 | 서버가 정책에 따라 선택 |
| 의도 | 데이터 수명·신선도 관리 | 메모리 부족 시 비상 공간 확보 |
| 서버 부하 | 평소에 조금씩 처리 | 메모리 압박 상황에서 몰려서 처리 |
| 관측 지표 | Expired Keys | Evicted Keys |

Microsoft Learn은 키에 만료 시간을 설정하라고 권장합니다. 만료는 메모리 압박이 생기기 전에 키를 미리 지우지만, 메모리 압박으로 인한 eviction은 서버 부하를 키울 수 있기 때문입니다. 즉, **TTL이 주된 정리 수단이고 eviction은 안전망**으로 보는 것이 좋습니다.

---

## 2. Azure Managed Redis에서의 eviction 설정 { #amr-settings }

### 2.1 지원 정책과 기본값

Azure Managed Redis는 다음 8개 정책을 지원하며 기본값은 `VolatileLRU`입니다.

`AllKeysLRU`, `AllKeysLFU`, `AllKeysRandom`, `VolatileLRU`, `VolatileLFU`, `VolatileRandom`, `VolatileTTL`, `NoEviction`

Redis 8.6에 추가된 `allkeys-lrm`·`volatile-lrm`(최근 수정 기준)은 Azure Managed Redis(Redis 7.4)에서 선택할 수 없습니다.

### 2.2 설정 방법

- **Azure Portal**: 캐시 리소스의 **Settings > Advanced settings**에서 **Eviction Policy**를 바꿉니다.
- **Azure CLI**: 생성 시 `az redisenterprise create --eviction-policy`, 생성 후 `az redisenterprise database update --eviction-policy`를 사용합니다.
- **Bicep/ARM**: `Microsoft.Cache/redisEnterprise/databases` 리소스의 `evictionPolicy` 속성을 지정합니다. 지정하지 않으면 `VolatileLRU`가 적용됩니다.

```bash
# 생성 후 정책 변경
az redisenterprise database update \
  --cluster-name <cache-name> \
  --resource-group <resource-group> \
  --eviction-policy AllKeysLRU

# 현재 정책 확인: 출력의 evictionPolicy 값
az redisenterprise database show \
  --cluster-name <cache-name> \
  --resource-group <resource-group> \
  --output json
```

Azure Managed Redis는 Redis Enterprise 기반이므로 `CONFIG SET`으로 `maxmemory-policy`, `maxmemory-samples`, `lfu-log-factor`, `lfu-decay-time` 같은 eviction 관련 값을 바꿀 수 없습니다. Redis Software가 지원하는 설정 목록에 이 값들이 없습니다. 정책은 위의 관리 경로로만 바꿉니다.

### 2.3 샤드 구조와 제약 사항 { #constraints }

![Azure Managed Redis 아키텍처. 클라이언트가 Load Balancer를 거쳐 두 Azure VM에 연결되고, 각 VM에는 Azure agent, Redis proxy, 여러 개의 Primary·Replica Redis Server 샤드가 있으며 VM 사이에 비동기 데이터 복제가 이루어진다.](images/managed-redis-architecture.png)

*그림: Azure Managed Redis 아키텍처. 출처: [Microsoft Learn – Azure Managed Redis architecture](https://learn.microsoft.com/azure/redis/architecture)*

Azure Managed Redis는 노드마다 여러 Redis 프로세스(샤드)를 실행합니다. 그래서 eviction도 **샤드 단위**로 일어납니다.

- **샤드 단위 eviction**: Redis Enterprise는 샤드마다 메모리를 따로 추적하고 그 샤드가 한도에 도달하면 eviction을 시작합니다. 해시 태그로 키를 한 샤드에 몰거나 큰 키가 특정 샤드에 쌓이면 **전체 사용률이 낮아도 일부 샤드에서 eviction이 발생**할 수 있습니다.
- **예약 메모리**: 메모리의 약 20%는 장애 조치 중 복제와 geo-replication 버퍼 같은 시스템 작업에 예약되어 있습니다. 데이터에 쓸 수 있는 메모리는 SKU 크기보다 작습니다.
- **RediSearch**: `NoEviction`만 사용할 수 있습니다.
- **Active geo-replication**: 그룹 안의 모든 캐시가 같은 eviction policy를 사용해야 하며, 그룹에 속한 캐시는 생성 후 정책을 바꿀 수 없습니다. 또한 메모리 한도에 가까워지면 geo-replication 동기화가 멈추므로 TTL이나 정책으로 메모리 압박을 줄여야 합니다.

---

## 3. 정책별 동작 { #policies }

아래 그림은 메모리 한도에 도달한 샤드에 쓰기 명령이 들어왔을 때 정책별로 어떻게 처리되는지 보여 줍니다.

[![쓰기 명령이 들어오면 샤드 메모리가 한도를 넘었는지 먼저 확인한다. 넘지 않았으면 그대로 저장한다. 넘었으면 noeviction은 OOM 오류로 쓰기를 거부하고, volatile 정책은 TTL 있는 키가 있으면 그중에서 삭제 후 저장하고 없으면 쓰기를 거부하며, allkeys 정책은 모든 키 중에서 삭제 후 저장한다.](images/eviction-flow.svg)](images/eviction-flow.svg)

| 정책 | 지우는 대상 | 선택 기준 | 주로 쓰는 경우 |
|---|---|---|---|
| `allkeys-lru` | 모든 키 | 가장 오래 사용하지 않은 키 | 일반 캐시. 일부 키에 접근이 몰리는 대부분의 워크로드 |
| `allkeys-lfu` | 모든 키 | 가장 적게 사용한 키 | 인기 키가 오래 안정적으로 유지되는 캐시 |
| `allkeys-random` | 모든 키 | 무작위 | 모든 키를 비슷한 빈도로 순환하며 읽는 경우 |
| `volatile-lru` | TTL 있는 키 | 가장 오래 사용하지 않은 키 | 캐시 키와 영구 키 혼합, 세션 저장소 (**Azure Managed Redis 기본값**) |
| `volatile-lfu` | TTL 있는 키 | 가장 적게 사용한 키 | 혼합 인스턴스에서 빈도 기반으로 지울 때 |
| `volatile-random` | TTL 있는 키 | 무작위 | 거의 쓰지 않음 |
| `volatile-ttl` | TTL 있는 키 | 남은 TTL이 가장 짧은 키 | 애플리케이션이 TTL로 "먼저 지워도 되는 키"를 표시할 때 |
| `noeviction` | 지우지 않음 | — | 영구 저장소, RediSearch |

`volatile-*` 정책은 **TTL이 있는 키가 하나도 없으면 `noeviction`처럼 동작**합니다.

### 3.1 allkeys-lru: Redis의 근사 LRU 알고리즘 { #allkeys-lru }

[![샤드의 키 공간에서 일부 키를 무작위로 샘플링해 유휴 시간 순으로 정렬된 후보 풀에 넣고, 유휴 시간이 가장 긴 키를 삭제한다. 메모리가 한도 아래로 내려갈 때까지 이 과정을 반복한다.](images/approximated-lru.svg)](images/approximated-lru.svg)

**동작 방식**

Redis는 정확한 LRU를 구현하지 않고 **근사(approximated) LRU**를 사용합니다.

1. 메모리 한도를 넘는 쓰기가 들어오면, 무작위로 소수의 키를 샘플링합니다.
2. 샘플 중 마지막 접근 이후 가장 오래된 키를 지웁니다.
3. Redis 3.0부터는 좋은 삭제 후보를 **후보 풀(pool)**로 유지해 샘플 간에 정보를 이어 갑니다. 그래서 적은 샘플로도 실제 LRU에 가깝게 동작합니다.

정확한 LRU는 모든 키를 접근 순서대로 관리해야 하므로 메모리를 더 씁니다. Redis 문서는 이 근사 방식이 애플리케이션 입장에서 사실상 실제 LRU와 동등하고, 특히 **접근이 소수 키에 몰리는(power law) 패턴에서는 차이가 거의 없다**고 설명합니다.

Redis Open Source에서는 `maxmemory-samples`(기본 5)를 10으로 올려 정확도를 높일 수 있지만, Azure Managed Redis에서는 이 값을 바꿀 수 없습니다.

**이점**

- **대부분의 캐시 워크로드에 맞습니다.** 전체 키 중 일부가 훨씬 자주 읽히는 경우(파레토 법칙)가 흔하므로 Redis 문서는 `allkeys-lru`를 좋은 기본 선택으로 권장합니다.
- **TTL 없이도 동작합니다.** 모든 키가 삭제 후보이므로 TTL을 빠뜨린 키 때문에 쓰기가 실패하지 않습니다.
- **메모리 효율이 좋습니다.** TTL 정보도 메모리를 쓰므로, TTL에 의존하지 않는 `allkeys-lru`가 상대적으로 효율적입니다.
- **메모리가 가득 차도 쓰기가 실패하지 않습니다.** 오래된 키를 지우고 새 데이터를 받습니다.

**주의할 점**

- 원본이 따로 없는 데이터도 지워질 수 있으므로 **다시 만들 수 있는 데이터에만** 사용합니다.
- 대량 일회성 조회(전체 스캔, 배치 읽기)가 있으면 최근 접근한 일회성 키가 오래 쓰던 인기 키를 밀어낼 수 있습니다. 이런 경우 `allkeys-lfu`를 검토합니다.
- eviction이 상시 발생한다면 메모리가 부족하다는 신호입니다. TTL과 SKU 크기를 함께 조정합니다.

### 3.2 allkeys-lfu: 접근 빈도 기반 { #allkeys-lfu }

Redis 4.0부터 제공되며, 키마다 접근 빈도를 추적해 **적게 쓰인 키**를 지웁니다.

- 키당 몇 비트만 쓰는 확률적 카운터(Morris counter)로 빈도를 추정합니다.
- 카운터는 시간이 지나면 감소(decay)합니다. 기본값은 약 100만 회 접근에서 포화되고 1분마다 감소합니다. 그래서 과거에 인기 있던 키도 접근이 끊기면 점차 삭제 후보가 됩니다.
- 후보 선택은 LRU와 같은 샘플링 방식을 사용합니다.

인기 키 집합이 비교적 안정적이고 일회성 대량 접근이 섞이는 캐시에서 `allkeys-lru`보다 적중률이 높을 수 있습니다. Azure Managed Redis에서는 `lfu-log-factor`, `lfu-decay-time`을 조정할 수 없으므로 기본 동작으로 비교합니다.

### 3.3 volatile-lru: Azure Managed Redis 기본값 { #volatile-lru }

TTL이 있는 키 중에서 가장 오래 사용하지 않은 키를 지웁니다. TTL이 없는 키는 **절대 지우지 않습니다**.

- 캐시 키(TTL 있음)와 지워지면 안 되는 키(TTL 없음)를 한 인스턴스에 둘 때 유용합니다. Redis 문서는 이런 경우에도 가능하면 인스턴스를 나누라고 권장합니다.
- 애플리케이션이 TTL을 거의 쓰지 않는다면 사실상 `noeviction`과 같습니다. 메모리가 가득 차면 쓰기 명령이 **out of memory 오류**로 실패합니다.

### 3.4 volatile-ttl과 random 계열

- **`volatile-ttl`**: 남은 TTL이 가장 짧은 키부터 지웁니다. 애플리케이션이 "덜 중요한 데이터에는 짧은 TTL"을 주는 식으로 삭제 순서를 직접 표시할 수 있을 때 씁니다.
- **`allkeys-random`**: 모든 키를 비슷한 빈도로 순환하며 읽는 패턴처럼 LRU·LFU가 의미 없는 경우에 씁니다.
- **`volatile-random`**: 실무에서 선택할 이유가 거의 없습니다.

### 3.5 noeviction: 지우지 않고 쓰기를 거부 { #noeviction }

메모리가 가득 차면 키를 지우지 않고 **새 데이터를 쓰는 명령을 오류로 거부**합니다. 읽기 명령은 정상 동작합니다. 데이터 유실보다 쓰기 실패가 나은 경우에 사용하며, 애플리케이션이 쓰기 오류를 처리하고 운영자가 메모리 사용률을 감시해야 합니다.

---

## 4. 용도별 권장 정책 { #by-workload }

### 4.1 일반 캐시 (cache-aside) { #general-cache }

원본 데이터가 DB 등에 따로 있고 Redis에는 복사본만 두는 경우입니다.

- **정책**: `allkeys-lru`. 인기 키가 안정적이고 일회성 대량 읽기가 섞이면 `allkeys-lfu`
- **TTL**: **데이터 신선도** 기준으로 설정합니다(예: 상품 정보 10분). TTL이 있으면 메모리 한도에 덜 도달합니다.
- **애플리케이션**: 캐시에 키가 없으면 원본에서 읽어 다시 채웁니다. eviction은 단지 캐시 미스로 나타납니다.

### 4.2 세션 저장소 { #session-store }

웹 애플리케이션의 로그인 세션처럼 **만료 시간이 본질적인 데이터**입니다. 세션 키가 eviction으로 지워지면 사용자는 **예고 없이 로그아웃**됩니다.

- **TTL**: 모든 세션 키에 필수입니다. 일반적인 세션 프레임워크는 TTL을 자동으로 걸고, 요청이 올 때마다 TTL을 다시 연장(sliding expiration)합니다.
    - Spring Session: 기본 비활성 시간 30분(1800초)
    - Node.js `connect-redis`: 쿠키 만료 시간 또는 `ttl` 옵션(기본 86400초) 사용. 사용자가 요청할 때마다 TTL을 재설정하며 `disableTouch`로 끌 수 있음
- **정책**: 기본값 `volatile-lru`로 충분합니다. 모든 세션 키에 TTL이 있으므로 `allkeys-lru`와 거의 같게 동작하고, 실수로 TTL 없이 들어간 다른 키는 보호합니다. `allkeys-lru`도 선택할 수 있지만 같은 인스턴스에 TTL 없는 키가 있다면 그 키도 지워질 수 있습니다.
- **운영 목표**: 세션 저장소에서는 **eviction이 일어나지 않게** 하는 것이 핵심입니다.
    - 동시 세션 수 × 세션 크기 × 여유분으로 메모리를 산정합니다.
    - Evicted Keys가 0보다 크면 알림을 받습니다.
    - 세션에 큰 객체를 넣지 않습니다.
- **세션 유실을 허용할 수 없다면**(장바구니, 다단계 결제 진행 상태 등) 그 데이터는 4.3의 영구 저장소 기준으로 다루거나 원본 DB에 저장합니다.

### 4.3 영구 저장소로 사용 { #primary-store }

Redis에만 원본이 있는 데이터(카운터, 순위표, 상태 저장 등)입니다.

- **정책**: `noeviction`. 다른 정책은 메모리가 차면 원본 데이터를 지웁니다.
- **TTL**: 업무상 만료가 필요한 키에만 사용합니다.
- **데이터 지속성**: RDB 또는 AOF 지속성을 켭니다. 다만 Microsoft Learn에 따르면 지속성은 노드 장애에서 **같은 캐시를 복구**하기 위한 기능입니다. 백업이나 특정 시점 복원(PITR)이 아니며, 손상된 데이터가 쓰이면 그대로 저장됩니다. 백업이 필요하면 정기 **내보내기(export)**를 함께 구성합니다.
    - 데이터 지속성은 고가용성(HA)이 켜진 캐시에서만 사용할 수 있고 active geo-replication과 함께 쓸 수 없습니다.
    - AOF는 데이터 손실을 줄이지만 처리량에 영향을 줄 수 있고, RDB는 성능 영향이 작지만 마지막 스냅숏 이후 데이터를 잃을 수 있습니다.
- **애플리케이션**: 메모리가 가득 차면 쓰기가 오류로 실패하므로 재시도·알림·대체 처리 로직을 둡니다.
- **운영**: Used Memory Percentage가 계속 75%를 넘으면 상위 SKU로 확장합니다(Microsoft Learn 권장).

### 4.4 캐시와 영구 데이터를 한 인스턴스에 둘 때 { #mixed }

- **정책**: `volatile-lru`(기본값)
- **규칙**: 캐시 키에는 **반드시** TTL을 걸고, 영구 키에는 TTL을 걸지 않습니다. 캐시 키에 TTL을 빠뜨리면 그 키는 영구 키처럼 메모리를 차지합니다.
- **권장**: Redis 문서는 가능하면 두 용도를 **별도 인스턴스로 분리**하라고 권장합니다. 정책, 지속성, 확장 기준이 서로 다르기 때문입니다.

---

## 5. 클라이언트에서 TTL을 건다는 의미 { #client-ttl }

[![클라이언트가 SET key v EX 600을 보내면 Redis 서버가 키와 만료 시각을 저장해 volatile 키가 된다. 이후 EXPIRE 재호출이나 세션 touch는 만료 시각을 연장하고, EX 없는 SET 덮어쓰기는 TTL을 제거해 영구 키로 만든다. 만료 시각이 지나면 접근할 때 삭제되거나 주기적 샘플링으로 삭제되고, 삭제는 복제본과 AOF에 DEL로 전파된다.](images/ttl-lifecycle.svg)](images/ttl-lifecycle.svg)

### 5.1 TTL은 서버에 저장되는 키 속성입니다

클라이언트가 TTL을 "건다"는 것은 `SET ... EX`, `EXPIRE` 같은 명령으로 **Redis 서버에 그 키의 만료 시각을 저장**하는 것입니다.

- 만료 시각은 절대 시각(밀리초 단위 Unix 시간)으로 저장됩니다. 클라이언트가 종료되거나 연결이 끊겨도 서버가 시간이 되면 키를 지웁니다.
- TTL은 **키 단위** 속성입니다. Hash나 List에 TTL을 걸면 키 전체가 함께 만료됩니다.
- Redis 용어로 TTL이 있는 키를 *volatile* 키라고 부릅니다. `volatile-*` 정책이 대상으로 삼는 키가 바로 이 키입니다.

### 5.2 TTL을 설정하는 방법

값을 쓰는 명령과 TTL을 **한 번에** 설정합니다. `SET` 후 `EXPIRE`를 따로 보내면 그 사이에 애플리케이션이 죽었을 때 TTL 없는 키가 남습니다.

```text
SET product:42 "{...}" EX 600      # 값과 TTL(600초)을 한 번에 설정
EXPIRE session:abc 1800            # 기존 키의 TTL을 설정·연장
TTL product:42                     # 남은 초. -1: TTL 없음, -2: 키 없음
```

```javascript
// node-redis 5.x
await client.set('product:42', json, { expiration: { type: 'EX', value: 600 } });
await client.expire('session:abc', 1800);
```

```java
// Lettuce
commands.set("product:42", json, SetArgs.Builder.ex(600));

// Jedis
jedis.set("product:42", json, SetParams.setParams().ex(600));

// Spring Data Redis
redisTemplate.opsForValue().set("product:42", json, Duration.ofMinutes(10));
```

```properties
# Spring Cache(@Cacheable)의 기본 TTL. 설정하지 않으면 캐시 항목에 TTL이 걸리지 않음
spring.cache.redis.time-to-live=10m
```

Spring Cache에서 `time-to-live`를 설정하지 않으면 캐시 항목이 TTL 없이 저장됩니다. 기본 정책 `volatile-lru`와 만나면 eviction 대상이 되지 않으므로 특히 주의합니다.

### 5.3 TTL이 유지되거나 사라지는 경우

| 동작 | TTL 변화 |
|---|---|
| `SET`으로 값을 덮어씀 | **TTL 제거** (`KEEPTTL` 옵션을 주면 유지) |
| `DEL`, `GETSET`, `*STORE` 명령 | 키 삭제·교체로 TTL 제거 |
| `INCR`, `LPUSH`, `HSET` 등 값 일부 변경 | **TTL 유지** |
| `EXPIRE`를 다시 호출 | 새 TTL로 갱신 (sliding expiration에 사용) |
| `PERSIST` | TTL 제거, 영구 키가 됨 |
| `RENAME` | TTL이 새 키 이름으로 이동 |
| `EXPIRE`에 0 이하 값 지정 | 즉시 삭제 |

가장 흔한 실수는 캐시를 갱신할 때 `SET`만 다시 호출해 **TTL이 사라지는 것**입니다. 갱신할 때도 `EX`를 함께 주거나 `KEEPTTL`을 사용합니다.

### 5.4 만료된 키가 실제로 지워지는 시점

Redis는 두 가지 방식으로 만료된 키를 지웁니다.

- **수동(passive) 만료**: 클라이언트가 만료된 키에 접근하면 그때 지우고 없는 키로 응답합니다.
- **능동(active) 만료**: 다시는 접근되지 않는 키를 위해, 주기적으로 TTL이 있는 키 일부를 무작위로 검사해 만료된 키를 지웁니다.

따라서 만료 시각이 지난 키가 **잠시 메모리에 남아 있을 수는 있지만 클라이언트에 반환되지는 않습니다**. 만료는 주 노드에서 처리되며 복제본과 AOF에는 `DEL`로 전달됩니다.

### 5.5 TTL 설계 팁

- **신선도 기준으로 정합니다.** 원본 데이터가 바뀐 뒤 얼마 동안 이전 값을 보여 줘도 되는지가 TTL의 기준입니다.
- **만료 시각을 분산합니다.** 같은 시점에 대량으로 캐시를 채우면서 같은 TTL을 주면 한꺼번에 만료되어 원본 DB에 부하가 몰릴 수 있습니다. TTL에 작은 무작위 값을 더하는 방식이 일반적으로 쓰입니다.
- **TTL도 메모리를 씁니다.** 키 수가 매우 많다면 만료 정보 자체의 메모리도 용량 산정에 포함합니다.

---

## 6. 검증과 모니터링 { #monitoring }

Azure Monitor에서 다음 지표를 확인합니다. Evicted Keys, Expired Keys, Cache Hits, Cache Misses는 초당 비율로 표시됩니다.

| 지표 | 확인할 내용 | 권장 알림 |
|---|---|---|
| Used Memory Percentage | 메모리 한도 대비 사용률 | 계속 75% 초과 시 확장 검토 |
| Evicted Keys | eviction 발생 여부 | 세션·영구 저장소는 0보다 크면 알림 |
| Expired Keys | TTL이 의도대로 동작하는지 | 급증·급감 시 TTL 설정 점검 |
| Cache Hits / Cache Misses | 캐시 적중률 | 적중률이 기대보다 낮으면 정책·TTL 점검 |

진단할 때는 다음 순서로 확인합니다.

1. **적중률이 낮고 Evicted Keys가 높다**: 메모리가 부족하거나 정책이 잘못된 키를 지우고 있습니다. 확장 또는 `allkeys-lru`/`allkeys-lfu` 전환을 검토합니다.
2. **Evicted Keys는 낮은데 Expired Keys가 높다**: TTL이 너무 짧거나 잘못된 키에 걸려 있을 수 있습니다.
3. **쓰기 명령이 out of memory 오류로 실패한다**: `noeviction`이거나 `volatile-*` 정책인데 TTL 있는 키가 부족한 상태입니다. 몇 개의 키를 골라 `TTL <key>`가 `-1`(TTL 없음)인지 확인합니다.
4. **전체 사용률은 낮은데 eviction이 발생한다**: 특정 샤드에 데이터가 몰렸을 가능성이 있습니다. 해시 태그 사용과 큰 키를 점검합니다. 키 하나의 실제 메모리는 `MEMORY USAGE <key>`로 확인합니다.

---

## 7. 정책 변경과 롤백

- 정책은 Portal이나 `az redisenterprise database update --eviction-policy`로 바꾸며, 이전 값으로 다시 바꾸면 롤백됩니다. 정책 변경 자체는 기존 키를 지우지 않고, 다음에 메모리 한도에 도달했을 때 어떤 키를 지울지만 바꿉니다.
- `noeviction`이나 `volatile-*`에서 `allkeys-*`로 바꾸면 **TTL 없는 키도 삭제 대상**이 됩니다. 영구 데이터가 섞여 있지 않은지 먼저 확인합니다.
- `allkeys-*`에서 `volatile-lru`로 바꾸기 전에는 캐시 키에 TTL이 걸려 있는지 확인합니다. 그렇지 않으면 메모리가 찼을 때 쓰기가 실패합니다.
- Active geo-replication 그룹의 캐시는 생성 후 정책을 바꿀 수 없으므로 생성 전에 정책을 확정합니다.

---

## 그림 원본

이 문서의 직접 작성한 그림은 Excalidraw 원본으로 [`samples/diagrams/`](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-managed-redis/eviction-policy-and-ttl/samples/diagrams)에 있습니다. 수정 방법은 해당 폴더의 README를 참고합니다.

## 관련 문서

- [Azure Managed Redis 클러스터링 정책별 연결과 마이그레이션 가이드](../cluster-failover-recovery/clustering-policies-and-migration/index.md): 클러스터링 정책과 샤드별 동작을 함께 확인합니다.
- [Azure Managed Redis Cluster Failover 장애 분석 및 복구 전략](../cluster-failover-recovery/index.md): OSS 정책에서 노드 교체 후 연결이 복구되지 않은 장애 사례입니다.

## 공식 참고 자료

**Microsoft Learn**

- [Memory management for Azure Managed Redis](https://learn.microsoft.com/azure/redis/best-practices-memory-management)
- [How to configure Azure Managed Redis](https://learn.microsoft.com/azure/redis/configure)
- [Configure data persistence for an Azure Managed Redis instance](https://learn.microsoft.com/azure/redis/how-to-persistence)
- [Configure active geo-replication for Azure Managed Redis instances](https://learn.microsoft.com/azure/redis/how-to-active-geo-replication)
- [Azure Managed Redis monitoring data reference](https://learn.microsoft.com/azure/redis/monitor-cache-reference)
- [Azure Managed Redis architecture](https://learn.microsoft.com/azure/redis/architecture)
- [az redisenterprise](https://learn.microsoft.com/cli/azure/redisenterprise), [az redisenterprise database](https://learn.microsoft.com/cli/azure/redisenterprise/database)

**Redis**

- [Key eviction](https://redis.io/docs/latest/develop/reference/eviction/): 정책 목록, 근사 LRU, LFU 설명
- [Redis Software eviction policy](https://redis.io/docs/latest/operate/rs/databases/memory-performance/eviction-policy/): 샤드 단위 eviction
- [Compatibility with Redis Open Source configuration settings](https://redis.io/docs/latest/operate/rs/references/compatibility/config-settings/): Redis Software에서 바꿀 수 있는 설정
- [EXPIRE](https://redis.io/docs/latest/commands/expire/): TTL 유지·제거 규칙과 만료 방식

**세션 프레임워크**

- [connect-redis](https://github.com/tj/connect-redis#ttl): Node.js 세션 TTL 동작
- [Spring Session](https://docs.spring.io/spring-session/reference/): Spring 세션 저장소
