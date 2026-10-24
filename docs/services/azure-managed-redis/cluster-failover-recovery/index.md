---
services:
- azure-managed-redis
official_sources:
- title: Choose a clustering policy for Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/choose-clustering-policy
- title: Azure Managed Redis architecture
  url: https://learn.microsoft.com/azure/redis/architecture
- title: Failover and patching for Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/failover
- title: Connection resilience with Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/best-practices-connection
- title: 'Quickstart: Connect to Azure Managed Redis in a Node.js app'
  url: https://learn.microsoft.com/azure/redis/nodejs-get-started
- title: node-redis Clustering
  url: https://github.com/redis/node-redis/blob/master/docs/clustering.md
- title: node-redis v5 to v6 migration guide
  url: https://github.com/redis/node-redis/blob/redis@6.0.0/docs/v5-to-v6.md
document_type: case
status: resolved
verification_status: verified
sources_checked_at: 2026-10-24
title: Azure Managed Redis Cluster Failover 분석
description: Azure Managed Redis cluster failover 장애의 분석과 복구 전략을 기록합니다.
technologies:
- nodejs
- redis
tags:
- operate
- diagnose
occurred_at: 2026-02-22
related_guides:
- clustering-policies-and-migration/index.md
- ../eviction-policy-and-ttl/index.md
redirect_from:
- cases/azure-managed-redis/cluster-failover-recovery/index.md
---

# Azure Managed Redis Cluster Failover 장애 분석 및 복구 전략

## 문제 정의

Azure Managed Redis를 **OSS Cluster 정책**으로 운영 중, **Planned Maintenance(Failover)** 이후 클라이언트가 연결을 복구하지 못해 애플리케이션 재기동 시점까지 장애가 지속되는 현상이 발생했습니다.

!!! tip "정책별 연결 방식과 마이그레이션"
    세 가지 클러스터링 정책의 차이, Node.js·Java 라이브러리별 연결 방식, Azure Cache for Redis에서 옮길 때의 판단 기준은 [클러스터링 정책별 연결과 마이그레이션 가이드](clustering-policies-and-migration/index.md)에 정리했습니다.

---

## Azure Managed Redis 클러스터링 구성 방식

Azure Managed Redis는 클러스터링 구성 방식을 크게 세 가지로 구분합니다.

[![세 가지 클러스터링 정책의 연결 모델. OSS 정책은 클라이언트가 10000 포트 엔드포인트에서 토폴로지를 조회한 뒤 85XX 포트의 각 샤드에 직접 연결한다. Enterprise 정책은 클라이언트가 10000 포트의 Redis proxy에만 연결하고 proxy가 샤드로 라우팅한다. Non-clustered 정책은 10000 포트 엔드포인트 뒤에 샤딩되지 않은 Redis 프로세스 하나가 있다.](images/clustering-policies.svg)](images/clustering-policies.svg)

### 1. Non-clustered

- 데이터를 샤딩하지 않는 단일 인스턴스 구성
- 별도의 클러스터 관리 불필요

### 2. Clustered - OSS API (default)

- Redis OSS API 기반 클러스터
- 클라이언트가 초기에는 **gateway(10000 포트)** 에 연결
- **MOVED/ASK 응답**을 통해 각 shard node(예: 8500~8599 포트)에 **직접 연결**
- 클라이언트가 **slot → node 매핑 정보를 캐시 및 관리**

### 3. Clustered - Enterprise API (Proxy 기반)

- **단일 엔드포인트**(기본 포트 10000)를 제공
- 클라이언트는 **proxy 계층**을 통해 Redis 클러스터에 접근
- 클러스터 **topology 관리는 Azure 서비스에서 수행**
- 클라이언트는 단일 연결만 관리하면 됨

> 기존 소스에서 `createCluster` 구성을 사용한 점으로 보아, **Enterprise 정책이 아닌 OSS Cluster 정책으로 생성**되었을 가능성이 높습니다.  
> ⚠️ 클러스터 정책은 **생성 후 변경이 불가**합니다.

Azure CLI와 ARM의 기본 클러스터링 정책은 OSS(`OSSCluster`)이므로, 정책을 지정하지 않고 만든 캐시는 OSS 정책이 됩니다. 정책별 비교와 생성 시 정책을 명시하는 방법은 [가이드](clustering-policies-and-migration/index.md#policy-comparison)를 참고합니다.

---

## 기존 코드 (문제 발생 부분)

```javascript
redisClient = createCluster({
    rootNodes: [{ url: `rediss://${redisUrl.hostname}:${redisUrl.port}` }],
    defaults: {
        credentialsProvider: provider,
        socket: {
            tls: true,
            servername: redisUrl.hostname,
            connectTimeout: 1000,
            reconnectStrategy,
        },
    },
});
```

이 경우 Redis cluster(sharding) 정보에 대한 관리를 **클라이언트에서 수행**하게 됩니다.

---

## 장애 증상

### 타임라인

| 시각 | 이벤트 |
|------|--------|
| 2026-02-15 10:18:53 | Azure Planned Maintenance 시작 → Failover |
| Maintenance 중 | 기존 node(8503 포트) 연결 끊김, reconnect 실패 |
| 재기동 시점 | 애플리케이션 재기동 후 8500 포트로 정상 연결 |

### Failover 과정에서의 문제 흐름

1. **Planned Maintenance** 과정에서 기존 Redis node가 교체됨
2. 기존 node에 연결되어 있던 **TCP 연결이 종료**됨 (로그 상 기존 연결은 **8503 포트**로 확인)
3. Redis client(`createCluster`)는 기존에 인지하고 있던 endpoint(**8503 포트**)에 대해 `reconnectStrategy`를 기반으로 재연결 시도
4. 해당 endpoint는 **node 교체 이후 더 이상 유효하지 않음**
5. 이 과정에서 **MOVED/ASK 응답을 정상적으로 수신하지 못해** cluster topology(rediscover)가 갱신되지 않았을 가능성
6. 결과적으로 클라이언트 레벨에서 **연결 복구가 이루어지지 않고**, 애플리케이션 재기동 시점까지 **장애 상태가 유지**된 것으로 추정

> 참고: 재기동 후 **8500 포트**로 연결된 것을 확인할 수 있으며, 8503 포트로 식별되던 기존 Redis node에 대한 연결은 Maintenance 이후 더 이상 유효하지 않았을 가능성이 있습니다.

### 원인 분석 보강 { #root-cause }

이후 Microsoft Learn 문서와 `@redis/client` 5.11.0 구현을 확인해 위 추정을 다음과 같이 보강했습니다(2026-10-24 확인).

[![장애 진행 과정. Maintenance 전에는 createCluster의 slot 맵이 노드 A의 8503 포트를 가리키고 정상 연결된다. Maintenance 중 노드 A가 제거되고 샤드가 새 노드 B의 8500 포트로 이동하지만, slot 맵은 갱신되지 않아 8503 재연결을 반복하다 실패하고 MOVED 응답도 받지 못한다. 재기동하거나 연결을 재생성하면 10000 포트에서 토폴로지를 다시 조회해 노드 B에 정상 연결된다.](images/failover-incident.svg)](images/failover-incident.svg)

**Azure 측 동작**

Microsoft Learn의 Failover 문서에 따르면 패치 작업은 다음 순서로 진행됩니다.

1. 새 VM을 만듭니다.
2. 기존 노드를 하나씩 클러스터에서 제거하면서 샤드를 새 VM으로 옮깁니다.
3. 교체된 VM을 삭제합니다.

OSS 정책에서는 클라이언트가 샤드 주소(IP:85XX)에 직접 연결하므로 이 과정에서 **연결 대상 주소 자체가 바뀔 수 있습니다**.

**클라이언트 측 동작** (`@redis/client` 5.11.0 구현 기준)

1. `createCluster`는 노드마다 별도 클라이언트를 만들고, 각 노드 클라이언트는 `reconnectStrategy`에 따라 **원래 주소로** 재연결합니다.
2. slot 맵을 다시 읽는 `rediscover`는 `MOVED`·`ASK` 응답이나 maintenance 이벤트를 받을 때만 실행됩니다.
3. 사라진 노드(8503)로는 연결 자체가 실패하므로 `MOVED` 응답을 받을 기회가 없습니다. 그래서 slot 맵이 갱신되지 않고 해당 slot의 명령이 계속 실패했습니다.
4. 재기동하면 `rootNodes`(10000 포트)에서 토폴로지를 새로 읽기 때문에 새 노드(8500)에 정상 연결됐습니다.

이 동작은 node-redis 6.0.0에서 재연결을 계기로 토폴로지를 다시 읽는 기능으로 보완됐습니다(방안 2 참고).

**악화 요인**

- `connectTimeout: 1000`은 Microsoft Learn 권장값(5초)보다 짧습니다. Failover 직후처럼 부하가 높은 상황에서 재연결 실패를 늘릴 수 있습니다.

---

## 대응 방안

### 방안 1: Enterprise Cluster 전환 (권장)

Enterprise Cluster 전환 및 `createCluster` → `createClient` 방식으로 연동할 경우, 운영 중 topology 관리 이슈를 **구조적으로 회피**할 수 있어 가장 확실한 대응 방안입니다.

```javascript
// Enterprise Cluster - proxy 기반 단일 엔드포인트 연결
const { createClient } = require('@redis/client');

const redisClient = createClient({
    url: `rediss://${redisUrl.hostname}:${redisUrl.port}`,
    password: accessKey,
    socket: {
        tls: true,
        servername: redisUrl.hostname,
        connectTimeout: 1000,
        reconnectStrategy,
    },
});
```

**장점**:
- 클라이언트가 cluster topology를 관리할 필요 없음
- Failover 시 proxy 계층이 자동으로 라우팅
- 단일 엔드포인트로 운영 복잡도 감소

**제약**:
- ⚠️ 클러스터 정책은 생성 시 설정으로 **변경 불가**, Redis **재생성 필요**

---

### 방안 2: OSS Cluster 유지 + 클라이언트의 토폴로지 갱신 기능 사용 { #option-topology-refresh }

OSS 정책을 유지한다면 노드가 사라졌을 때 클라이언트가 스스로 토폴로지를 다시 읽어야 합니다. 직접 갱신 로직을 만들기보다 각 클라이언트 라이브러리가 공식으로 제공하는 기능을 사용합니다. 애플리케이션에서 `CLUSTER SLOTS`를 직접 호출해도 node-redis 내부 slot 맵은 바뀌지 않으므로 기존 예제의 주기 호출은 효과가 없습니다.

**node-redis 6.0.0 이상으로 업그레이드 (권장)**

node-redis 6.0.0([redis/node-redis#3223](https://github.com/redis/node-redis/pull/3223))에는 이 장애에 해당하는 상황을 처리하는 `createCluster` 옵션 `topologyRefreshOnReconnectionAttemptStrategy`가 추가됐습니다. [공식 문서](https://github.com/redis/node-redis/blob/master/docs/clustering.md)와 6.x 구현에 따르면 다음과 같이 동작합니다.

- 한 번 연결됐던 노드 client가 재연결을 시작하면, 기본 5000ms 뒤에 백그라운드에서 클러스터 토폴로지를 다시 읽습니다.
- 토폴로지는 재연결 중인 노드를 제외한 다른 노드에서 읽고, 새 토폴로지에 없는 노드의 연결은 정리합니다.
- 이번 사례처럼 8503 노드가 사라져도 다른 샤드를 통해 새 노드(8500)를 찾아 slot 맵을 갱신합니다.

```javascript
const cluster = createCluster({
  rootNodes: [{ url: `rediss://${host}:10000` }],
  defaults: { /* TLS, 인증, reconnectStrategy 등: 가이드의 Node.js 절 참고 */ },
  // node-redis 6.0.0+. 기본값이 5000이므로 생략해도 같다. false 또는 0이면 꺼진다
  topologyRefreshOnReconnectionAttemptStrategy: 5_000,
});
```

6.0.0으로 올릴 때는 [v5 → v6 마이그레이션 가이드](https://github.com/redis/node-redis/blob/redis@6.0.0/docs/v5-to-v6.md)의 다음 변경을 함께 확인합니다.

- Node.js 20 이상이 필요합니다.
- 기본 프로토콜이 RESP3로 바뀌어 일부 명령의 반환 형식이 달라집니다.
- `commandOptions.timeout` 기본값이 5000ms가 됩니다. 이 값은 전송 전 queue 대기 시간을 제한합니다.
- RESP3에서는 `maintNotifications`가 `"auto"`가 되어 maintenance 알림을 구독합니다. 다만 [Smart client handoffs](https://redis.io/docs/latest/develop/clients/sch/) 지원 서버는 Redis Cloud와 Redis Software로 안내되어 있고 Azure Managed Redis는 목록에 없으므로, 이 기능에 의존하지 않습니다.

**node-redis 5.x를 유지해야 한다면**

- node-redis 5.x에는 노드 연결 실패를 계기로 토폴로지를 다시 읽는 기능이 없습니다. node-redis가 공식 제공하는 재생성 예제도 없습니다.
- Microsoft Learn의 [Failover and patching for Azure Managed Redis](https://learn.microsoft.com/azure/redis/failover)와 [Azure Node.js 모범 사례](https://github.com/Azure/AzureCacheForRedis/blob/main/Redis-BestPractices-Node-js.md)는 연결 오류가 일정 시간(예: 30초) 이상 지속되면 **연결 객체를 새로 만들라**고 권장합니다. 새 클러스터 client는 `10000` 포트에서 최신 토폴로지를 다시 읽습니다.
- 다만 재생성 중 처리 중인 요청의 정리, 연결 시도와 토폴로지 조회의 시간 제한까지 안전하게 직접 구현하기는 까다롭습니다. 가능하면 6.0.0 업그레이드나 방안 1을 우선 검토합니다.
- 다른 클라이언트를 쓸 수 있다면 ioredis의 공식 옵션 [`slotsRefreshInterval`](https://github.com/redis/ioredis#cluster)(기본 비활성)로 주기적 토폴로지 갱신을 켤 수 있습니다.

`defaults`에 넣을 TLS·인증과 `nodeAddressMap`까지 포함한 전체 설정 예는 [가이드의 Node.js 절](clustering-policies-and-migration/index.md#nodejs)에 있습니다. 요청 실패는 아래 **Failover Plan 권장**의 대체 경로나 Circuit Breaker로 처리합니다.

**보완 포인트**:
- 기존 코드의 `connectTimeout: 1000`을 제거하고 node-redis 기본값을 사용합니다. `connectTimeout`은 기본 5000ms로 Microsoft Learn 권장값과 같고, `reconnectStrategy`는 기본으로 지수 백오프(최대 2000ms)에 0~200ms 지터를 더합니다.
- Health Check에서 cluster 상태 모니터링

### 같은 상황을 Java에서 겪는다면

| 라이브러리 | 대응 |
|---|---|
| Lettuce | `enablePeriodicRefresh`와 `enableAllAdaptiveRefreshTriggers`를 명시합니다([Lettuce](clustering-policies-and-migration/index.md#lettuce)). 주기적 갱신이 있으면 사라진 노드도 다음 갱신 주기에 토폴로지에서 제외됩니다. |
| Jedis | 연속 연결 실패 시 slot 캐시를 다시 읽지만, `topologyRefreshPeriod`로 주기적 갱신도 설정해 둡니다([Jedis](clustering-policies-and-migration/index.md#jedis)). |
| Spring Boot | 기본 Lettuce를 유지하고 `spring.data.redis.lettuce.cluster.refresh.*`를 설정합니다([Spring Boot](clustering-policies-and-migration/index.md#spring-boot)). |
| Redisson | `scanInterval`을 짧게(Azure 기준 예시 1000ms) 유지합니다. |
| 공통 | 오류가 일정 시간 이상 지속되면 클라이언트를 재생성하는 안전장치를 둡니다. |

---

## 참고

### @redis/client 5.11.0 - Smart Client Handoffs

`@redis/client` **5.11.0 release note**를 보면 **Smart Client Handoffs for Enterprise OSS API**에 대한 소개가 있습니다.

- 해당 기능은 현재 Enterprise Redis에 대해 **점진적으로 도입 중**인 기능
- 클라이언트 업데이트만으로 즉시 문제 해결을 보장하지는 않음
- 향후 유지보수 관점에서는 도움이 될 가능성 있음
- Smart client handoffs 지원 서버 목록(Redis Cloud, Redis Software)에 Azure Managed Redis는 없으므로, 방안 2의 토폴로지 갱신 기능과 별개로 봅니다

### Failover Plan 권장

Redis를 세션 또는 캐시로 사용하는 아키텍처에서는 장애 발생 시 **단일 장애 지점(SPOF)** 이 되지 않도록, 애플리케이션 레벨에서 다음을 사전에 수립할 것을 권장합니다:

- **내장 세션 처리**: Redis 장애 시 인메모리 세션으로 대체
- **대체 경로(Fallback)**: 캐시 미스 시 원본 데이터소스에서 직접 조회
- **Circuit Breaker**: 반복 장애 시 Redis 호출 차단 후 일정 시간 뒤 재시도

```javascript
// Circuit Breaker 패턴 예시
let redisAvailable = true;
let failureCount = 0;
const FAILURE_THRESHOLD = 5;
const RECOVERY_TIMEOUT = 30000;

async function safeRedisGet(key) {
    if (!redisAvailable) {
        return null; // fallback: 캐시 미사용
    }
    try {
        const value = await redisClient.get(key);
        failureCount = 0;
        return value;
    } catch (err) {
        failureCount++;
        if (failureCount >= FAILURE_THRESHOLD) {
            redisAvailable = false;
            console.warn('Redis circuit breaker OPEN - falling back');
            setTimeout(() => {
                redisAvailable = true;
                failureCount = 0;
                console.info('Redis circuit breaker CLOSED - retrying');
            }, RECOVERY_TIMEOUT);
        }
        return null;
    }
}
```

---

## 코드 샘플

이 이슈를 검증하기 위한 예제 코드는 [`cluster_example/`](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-managed-redis/cluster-failover-recovery/samples/nodejs-cluster/cluster_example) 디렉토리에 포함되어 있습니다.

- OSS Cluster(`createCluster`) vs Enterprise(`createClient`) 연결 방식 비교
- Cluster topology 조회 및 모니터링
- Failover 시뮬레이션 및 복구 테스트
- Health Check Probe

그림의 Excalidraw 원본은 [`samples/diagrams/`](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-managed-redis/cluster-failover-recovery/samples/diagrams)에 있습니다.

---

## 관련 문서

- [Azure Managed Redis 클러스터링 정책별 연결과 마이그레이션 가이드](clustering-policies-and-migration/index.md): 정책 선택, Node.js·Java 연결 방식, Azure Cache for Redis 마이그레이션을 다룹니다.
- [Azure Managed Redis Eviction Policy와 TTL 설계 가이드](../eviction-policy-and-ttl/index.md): 메모리 한도에서의 키 삭제 정책과 TTL 설계를 다룹니다.

---

## 참고 자료

- [Choose a clustering policy for Azure Managed Redis](https://learn.microsoft.com/azure/redis/choose-clustering-policy)
- [Failover and patching for Azure Managed Redis](https://learn.microsoft.com/azure/redis/failover)
- [Azure Managed Redis - Clustering](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-how-to-premium-clustering)
- [Azure Managed Redis - Best Practices for Connection Resilience](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-best-practices-connection)
- [node-redis Cluster Guide](https://github.com/redis/node-redis/blob/master/docs/clustering.md)
- [@redis/client 5.11.0 Release Notes](https://github.com/redis/node-redis/releases/tag/%40redis%2Fclient%405.11.0)
- [node-redis v5 to v6 migration guide](https://github.com/redis/node-redis/blob/redis@6.0.0/docs/v5-to-v6.md)
- [redis/node-redis#3223: cluster topology refresh after node reconnects](https://github.com/redis/node-redis/pull/3223)
- [Smart client handoffs](https://redis.io/docs/latest/develop/clients/sch/)
