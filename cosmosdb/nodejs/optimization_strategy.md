# CosmosDB 성능 최적화 전략 가이드

## 목차
1. [개요](#개요)
2. [Point Read 최적화](#1-point-read-최적화)
3. [연결 및 네트워크 최적화](#2-연결-및-네트워크-최적화)
4. [Partition Key 설계](#3-partition-key-설계)
5. [캐싱 전략](#4-캐싱-전략)
6. [배치 처리 최적화](#5-배치-처리-최적화)
7. [모니터링 및 측정](#6-모니터링-및-측정)

---

## 개요

CosmosDB의 성능을 최적화하는 것은 **비용 절감**과 **응답 속도 개선** 두 가지 목표를 동시에 달성하는 것입니다. 이 가이드는 실전에서 바로 적용 가능한 최적화 전략들을 제시합니다.

### 핵심 최적화 원칙
- **RU(Request Unit) 최소화**: 같은 작업을 더 적은 RU로 수행
- **응답 시간 단축**: 네트워크 및 쿼리 최적화
- **처리량 극대화**: 병렬 처리 및 배치 처리
- **안정성 확보**: 재시도, 에러 처리, 모니터링

---

## 1. Point Read 최적화

### 1.1 Point Read란?

Point Read는 **문서의 ID와 Partition Key를 정확히 알고 있을 때** 사용하는 가장 효율적인 읽기 방식입니다.

**효과:**
- RU 비용: Query 대비 약 **90% 절감** (10 RU → 1 RU)
- 응답 속도: 약 **5-10배 빠름**
- 예측 가능한 성능

### 1.2 구현 방법

```javascript
// ❌ 비효율적: Query 사용 (3-10 RU)
const querySpec = {
    query: 'SELECT * FROM c WHERE c.id = @id',
    parameters: [{ name: '@id', value: 'user123' }]
};
const { resources } = await container.items.query(querySpec).fetchAll();

// ✅ 효율적: Point Read (1 RU)
const { resource } = await container.item('user123', 'user123').read();
```

### 1.3 적용 체크리스트

- [ ] 모든 ID 기반 조회를 Point Read로 전환
- [ ] Partition Key를 알 수 없는 경우 캐싱 전략 수립
- [ ] Handler 패턴으로 Point Read 로직 추상화
- [ ] 성능 모니터링으로 Point Read 사용률 추적

**참고 문서:** [point_read_pattern.md](./point_read_pattern.md)

---

## 2. 연결 및 네트워크 최적화

### 2.1 Direct Mode vs Gateway Mode

| 구분 | Direct Mode | Gateway Mode |
|------|-------------|--------------|
| 성능 | 더 빠름 (10-20% 개선) | 보통 |
| 연결 | TCP 직접 연결 | HTTPS 경유 |
| 방화벽 | 추가 포트 필요 | 443 포트만 사용 |
| 권장 사용 | 프로덕션 환경 | 제한된 네트워크 환경 |

```javascript
// Direct Mode 설정 (권장)
const client = new CosmosClient({
    endpoint,
    key,
    connectionPolicy: {
        connectionMode: 'Direct'
    }
});
```

### 2.2 Preferred Locations를 통한 읽기 분산

여러 리전에 복제된 CosmosDB의 경우, 가장 가까운 리전에서 읽기를 수행하도록 설정:

```javascript
const client = new CosmosClient({
    endpoint,
    key,
    connectionPolicy: {
        preferredLocations: ['Korea Central', 'Japan East', 'Southeast Asia']
    }
});
```

**효과:**
- 네트워크 지연 시간 최소화
- 읽기 트래픽 분산
- 자동 Failover 지원

**참고 문서:** [client.md](./client.md)

### 2.3 연결 재사용

```javascript
// ❌ 나쁜 예: 매번 새 클라이언트 생성
function getClient() {
    return new CosmosClient({ endpoint, key });
}

// ✅ 좋은 예: 싱글톤 패턴
let cosmosClient = null;

function getClient() {
    if (!cosmosClient) {
        cosmosClient = new CosmosClient({ endpoint, key });
    }
    return cosmosClient;
}
```

### 2.4 DNS 캐싱

Node.js는 기본적으로 DNS 캐싱을 하지 않아 매 요청마다 DNS 조회가 발생할 수 있습니다.

```javascript
// cacheable-lookup 라이브러리 사용
import CacheableLookup from 'cacheable-lookup';
import http from 'http';

const cacheable = new CacheableLookup();
cacheable.install(http.globalAgent);
```

또는 환경 변수로 UV Thread Pool 확장:

```bash
UV_THREADPOOL_SIZE=64
```

**참고 문서:** [query_thread_with_low_core.md](./query_thread_with_low_core.md)

---

## 3. Partition Key 설계

### 3.1 Partition Key 선택 원칙

좋은 Partition Key는:
- ✅ **높은 카디널리티**: 많은 고유 값
- ✅ **균등 분산**: 데이터가 여러 파티션에 고르게 분산
- ✅ **쿼리 패턴 일치**: 자주 조회되는 필드

### 3.2 일반적인 패턴

#### 패턴 1: ID를 Partition Key로 사용
```javascript
{
    "id": "user123",
    "partitionKey": "user123", // ID와 동일
    "name": "User Name"
}
```

**장점:** Point Read가 간단  
**단점:** 관련 문서들이 서로 다른 파티션에 분산

#### 패턴 2: 엔티티 타입별 그룹화
```javascript
{
    "id": "order123",
    "customerId": "customer456", // Partition Key
    "items": [...]
}
```

**장점:** 고객별 모든 주문을 하나의 파티션에서 효율적으로 조회  
**단점:** 특정 고객의 주문이 많으면 Hot Partition 발생 가능

#### 패턴 3: Hierarchical Partition Keys (계층적 파티션 키)
```javascript
// Cosmos DB SDK v3.17.0+
const containerDefinition = {
    partitionKey: {
        paths: ['/tenantId', '/userId'],
        version: 2
    }
};
```

**장점:** 더 세밀한 파티션 분할  
**단점:** SDK 버전 요구사항

### 3.3 Anti-Patterns (피해야 할 패턴)

❌ **모든 문서에 같은 Partition Key 사용**
```javascript
// 모든 문서가 하나의 파티션에 집중 → 10GB 제한, 성능 저하
{ "id": "doc1", "partitionKey": "global" }
{ "id": "doc2", "partitionKey": "global" }
```

❌ **너무 세밀한 Partition Key**
```javascript
// 타임스탬프를 partition key로 사용 → 파티션 수만 증가
{ "id": "event1", "timestamp": "2024-01-01T12:34:56.789Z" }
```

---

## 4. 캐싱 전략

### 4.1 Partition Key 캐싱

ID만 알고 Partition Key를 모르는 경우, 한 번 조회 후 캐싱:

```javascript
class PartitionKeyCache {
    constructor(ttl = 300000) { // 5분
        this.cache = new Map();
        this.ttl = ttl;
    }

    set(id, partitionKey) {
        this.cache.set(id, {
            partitionKey,
            expires: Date.now() + this.ttl
        });
    }

    get(id) {
        const cached = this.cache.get(id);
        if (cached && cached.expires > Date.now()) {
            return cached.partitionKey;
        }
        this.cache.delete(id);
        return null;
    }
}

const pkCache = new PartitionKeyCache();

async function getUser(id) {
    let partitionKey = pkCache.get(id);
    
    if (partitionKey) {
        // Point Read
        return await container.item(id, partitionKey).read();
    } else {
        // Query (첫 조회)
        const user = await queryById(id);
        if (user) {
            pkCache.set(id, user.partitionKey);
        }
        return user;
    }
}
```

### 4.2 Read-Through Cache (Redis 활용)

자주 조회되는 문서는 Redis에 캐싱:

```javascript
async function getUserWithCache(id, partitionKey) {
    const cacheKey = `user:${id}`;
    
    // 1. Redis 확인
    const cached = await redis.get(cacheKey);
    if (cached) {
        return JSON.parse(cached);
    }
    
    // 2. CosmosDB Point Read
    const { resource } = await container.item(id, partitionKey).read();
    
    // 3. Redis에 캐싱 (TTL 5분)
    if (resource) {
        await redis.setex(cacheKey, 300, JSON.stringify(resource));
    }
    
    return resource;
}
```

**효과:**
- RU 비용 대폭 절감 (캐시 히트 시 0 RU)
- 응답 속도 향상 (Redis는 밀리초 단위)

---

## 5. 배치 처리 최적화

### 5.1 병렬 Point Read

여러 문서를 조회할 때 병렬 처리:

```javascript
async function batchGetUsers(userIds) {
    // ❌ 순차 처리 (느림)
    const users = [];
    for (const id of userIds) {
        const user = await container.item(id, id).read();
        users.push(user.resource);
    }
    
    // ✅ 병렬 처리 (빠름)
    const promises = userIds.map(id => 
        container.item(id, id).read()
    );
    const results = await Promise.all(promises);
    const users = results.map(r => r.resource);
    
    return users;
}
```

### 5.2 Bulk Operations

대량 생성/업데이트 시 Bulk API 사용:

```javascript
// Bulk Create (Transactional Batch)
const operations = items.map(item => ({
    operationType: 'Create',
    resourceBody: item
}));

const { result } = await container.items.batch(operations, partitionKey);
```

**주의사항:**
- Transactional Batch는 **같은 Partition Key** 내에서만 가능
- 최대 100개 작업, 2MB 제한

### 5.3 최적의 동시성 제어

```javascript
// p-limit 라이브러리 활용
import pLimit from 'p-limit';

const limit = pLimit(50); // 동시에 50개까지만 처리

async function processLargeDataset(items) {
    const promises = items.map(item => 
        limit(() => processItem(item))
    );
    return await Promise.all(promises);
}
```

---

## 6. 모니터링 및 측정

### 6.1 RU 소비량 추적

모든 작업에서 RU를 로깅:

```javascript
async function trackedQuery(querySpec) {
    const { resources, requestCharge } = await container.items
        .query(querySpec)
        .fetchAll();
    
    console.log(`Query consumed ${requestCharge} RU`);
    
    // Application Insights에 메트릭 전송
    telemetryClient.trackMetric({
        name: 'CosmosDB RU Consumed',
        value: requestCharge
    });
    
    return resources;
}
```

### 6.2 주요 모니터링 메트릭

| 메트릭 | 목표 | 설명 |
|--------|------|------|
| Point Read 비율 | >80% | 전체 읽기 중 Point Read 사용 비율 |
| 평균 RU/요청 | <5 RU | 읽기 작업당 평균 RU |
| P95 응답 시간 | <50ms | 95번째 백분위수 응답 시간 |
| 429 에러율 | <1% | Rate Limiting 발생 비율 |

### 6.3 Application Insights 연동

```javascript
import appInsights from 'applicationinsights';

appInsights.setup(process.env.APPLICATIONINSIGHTS_CONNECTION_STRING)
    .setAutoCollectDependencies(true)
    .start();

const client = appInsights.defaultClient;

async function monitoredPointRead(id, partitionKey) {
    const startTime = Date.now();
    
    try {
        const response = await container.item(id, partitionKey).read();
        
        client.trackDependency({
            target: 'CosmosDB',
            name: 'Point Read',
            data: `${id}/${partitionKey}`,
            duration: Date.now() - startTime,
            resultCode: 200,
            success: true
        });
        
        client.trackMetric({
            name: 'CosmosDB RU',
            value: response.requestCharge
        });
        
        return response.resource;
    } catch (error) {
        client.trackException({ exception: error });
        throw error;
    }
}
```

---

## 최적화 체크리스트

### 즉시 적용 가능 (Quick Wins)
- [ ] ID 기반 Query를 Point Read로 전환
- [ ] CosmosClient 싱글톤 패턴 적용
- [ ] Preferred Locations 설정
- [ ] Direct Mode 활성화
- [ ] 404 에러 명시적 처리

### 중기 개선 사항
- [ ] Partition Key 캐싱 구현
- [ ] 병렬 처리 도입 (Promise.all)
- [ ] DNS 캐싱 적용
- [ ] RU 모니터링 대시보드 구축
- [ ] Handler 패턴으로 리팩토링

### 장기 전략
- [ ] Partition Key 재설계 검토
- [ ] Redis 캐싱 레이어 추가
- [ ] Auto-scale 설정 최적화
- [ ] Hierarchical Partition Keys 도입
- [ ] 지역별 읽기 분산 전략

---

## 성능 개선 사례

### 사례 1: Query → Point Read 전환

**변경 전:**
```javascript
// RU: ~5 RU, 응답 시간: ~40ms
const { resources } = await container.items
    .query('SELECT * FROM c WHERE c.id = @id')
    .fetchAll();
```

**변경 후:**
```javascript
// RU: ~1 RU, 응답 시간: ~8ms
const { resource } = await container.item('user123', 'user123').read();
```

**개선 효과:**
- RU 비용: 80% 절감
- 응답 시간: 5배 개선
- 월 비용: $500 → $100

### 사례 2: 병렬 처리 도입

**변경 전:**
```javascript
// 순차 처리: 100개 x 10ms = 1000ms
for (const id of userIds) {
    await getUser(id);
}
```

**변경 후:**
```javascript
// 병렬 처리: ~50ms (네트워크 RTT)
await Promise.all(userIds.map(id => getUser(id)));
```

**개선 효과:**
- 처리 시간: 95% 단축
- 처리량: 20배 증가

---

## 참고 자료

### 내부 문서
- [Point Read 패턴](./point_read_pattern.md)
- [클라이언트 최적화](./client.md)
- [DNS 최적화](./query_thread_with_low_core.md)

### 공식 문서
- [Azure Cosmos DB Best Practices](https://learn.microsoft.com/azure/cosmos-db/nosql/best-practice-dotnet)
- [Request Unit Optimization](https://learn.microsoft.com/azure/cosmos-db/optimize-cost-reads-writes)
- [Partitioning Overview](https://learn.microsoft.com/azure/cosmos-db/partitioning-overview)
- [Performance Tips](https://learn.microsoft.com/azure/cosmos-db/performance-tips)

---

## 요약

CosmosDB 최적화의 핵심은:

1. **Point Read 최대 활용** - 가장 큰 효과
2. **적절한 Partition Key 설계** - 장기적 성능의 기반
3. **연결 재사용 및 병렬 처리** - 처리량 극대화
4. **캐싱 전략** - 불필요한 요청 제거
5. **지속적인 모니터링** - 개선 기회 식별

이러한 전략을 순차적으로 적용하면 **비용 50-80% 절감**, **응답 시간 5-10배 개선**을 달성할 수 있습니다.
