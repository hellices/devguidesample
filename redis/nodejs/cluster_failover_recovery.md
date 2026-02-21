# Azure Managed Redis Cluster Failover 장애 분석 및 복구 전략

## 문제 정의

Azure Managed Redis를 **OSS Cluster 정책**으로 운영 중, **Planned Maintenance(Failover)** 이후 클라이언트가 연결을 복구하지 못해 애플리케이션 재기동 시점까지 장애가 지속되는 현상이 발생했습니다.

---

## Azure Managed Redis 클러스터링 구성 방식

Azure Managed Redis는 클러스터링 구성 방식을 크게 세 가지로 구분합니다.

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

### 방안 2: OSS Cluster 유지 + Topology Refresh 보강

OSS Cluster를 유지할 경우에는 클라이언트 레벨에서 **topology refresh 및 reconnect 전략을 보완**합니다.

```javascript
const { createCluster } = require('@redis/client');

const redisClient = createCluster({
    rootNodes: [{ url: `rediss://${redisUrl.hostname}:${redisUrl.port}` }],
    defaults: {
        password: accessKey,
        socket: {
            tls: true,
            servername: redisUrl.hostname,
            connectTimeout: 1000,
            reconnectStrategy: (retries) => {
                if (retries === 0) return 0;
                const delay = Math.min(2 ** (retries - 1) * 50, 5000);
                return delay;
            },
        },
    },
    // Topology Refresh 설정
    minimumMasterNodesUsingSlots: 1,
    useReplicas: true,
    nodeAddressMap: undefined,
});

// 주기적 topology refresh 직접 구현
async function refreshTopology() {
    try {
        // CLUSTER SLOTS 또는 CLUSTER SHARDS로 최신 topology 조회
        const slotsRaw = await redisClient.sendCommand(
            undefined, true, ['CLUSTER', 'SLOTS']
        );
        console.log('[topology-refresh] Cluster slots refreshed successfully');
    } catch (err) {
        console.error('[topology-refresh] Failed to refresh topology:', err.message);
    }
}

// 30초마다 topology 갱신 시도
setInterval(refreshTopology, 30000);
```

**보완 포인트**:
- `reconnectStrategy`에서 최대 재시도 횟수 제한 및 exponential backoff 적용
- 주기적 topology refresh로 node 변경 감지
- Health Check에서 cluster 상태 모니터링

---

## 참고

### @redis/client 5.11.0 - Smart Client Handoffs

`@redis/client` **5.11.0 release note**를 보면 **Smart Client Handoffs for Enterprise OSS API**에 대한 소개가 있습니다.

- 해당 기능은 현재 Enterprise Redis에 대해 **점진적으로 도입 중**인 기능
- 클라이언트 업데이트만으로 즉시 문제 해결을 보장하지는 않음
- 향후 유지보수 관점에서는 도움이 될 가능성 있음

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

이 이슈를 검증하기 위한 예제 코드는 [`cluster_example/`](cluster_example/) 디렉토리에 포함되어 있습니다.

- OSS Cluster(`createCluster`) vs Enterprise(`createClient`) 연결 방식 비교
- Cluster topology 조회 및 모니터링
- Failover 시뮬레이션 및 복구 테스트
- Health Check Probe

---

## 참고 자료

- [Azure Managed Redis - Clustering](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-how-to-premium-clustering)
- [Azure Managed Redis - Best Practices for Connection Resilience](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-best-practices-connection)
- [node-redis Cluster Guide](https://github.com/redis/node-redis/blob/master/docs/clustering.md)
- [@redis/client 5.11.0 Release Notes](https://github.com/redis/node-redis/releases/tag/%40redis%2Fclient%405.11.0)
