# CosmosDB Point Read 최적화 패턴

## 개요
CosmosDB에서 **Point Read**는 문서의 ID와 Partition Key를 정확히 알고 있을 때 사용하는 가장 효율적인 읽기 방식입니다. Query 방식 대비 **RU(Request Unit) 비용이 약 90% 낮고, 응답 속도가 5-10배 빠릅니다**.

> **참고**: JavaScript SDK는 Gateway Mode만 지원합니다. Direct Mode는 .NET, Java 등 다른 SDK에서만 사용 가능합니다.

---

## 1. Point Read vs Query 성능 비교

### Query 방식 (비효율적)
```javascript
const querySpec = {
    query: 'SELECT * FROM c WHERE c.id = @id',
    parameters: [{ name: '@id', value: 'user123' }]
};
const { resources } = await container.items.query(querySpec).fetchAll();
```

**문제점:**
- ❌ Index를 스캔하는 쿼리 엔진 실행
- ❌ 높은 RU 비용 (약 3-10 RU)
- ❌ Partition Key가 없으면 cross-partition query 발생 → 매우 비효율적

### Point Read 방식 (효율적)
```javascript
const { resource } = await container.item('user123', 'user123').read();
```

**장점:**
- ✅ 직접 문서 접근 (인덱스 스캔 없음)
- ✅ 낮은 RU 비용 (약 1 RU)
- ✅ 빠른 응답 속도 (5-10ms)
- ✅ 예측 가능한 성능

### 성능 비교표

| 방식 | RU 비용 | 응답 시간 | 사용 사례 |
|------|---------|-----------|-----------|
| Point Read | ~1 RU | 5-10ms | ID + Partition Key를 정확히 아는 경우 |
| Query (단일 파티션) | ~3-10 RU | 20-50ms | 조건 검색이 필요한 경우 |
| Cross-Partition Query | ~10-100+ RU | 100-500ms+ | 파티션 키를 모르는 경우 |

---

## 2. 기본 Point Read 패턴

### 패턴 1: ID를 Partition Key로 사용

```javascript
import { CosmosClient } from '@azure/cosmos';

const client = new CosmosClient({ endpoint, key });
const container = client.database('myDatabase').container('users');

async function getUserById(id) {
    try {
        // ID와 Partition Key가 동일한 경우
        const { resource } = await container.item(id, id).read();
        return resource;
    } catch (error) {
        if (error.code === 404) {
            return null; // 문서 없음
        }
        throw error;
    }
}
```

**적용 시나리오:**
- 사용자 프로필 조회 (userId로 직접 접근)
- 세션 데이터 조회 (sessionId로 직접 접근)
- 간단한 key-value 저장소 패턴

### 패턴 2: 복합 Partition Key 사용

```javascript
async function getOrder(orderId, customerId) {
    try {
        // customerId가 Partition Key인 경우
        const { resource } = await container.item(orderId, customerId).read();
        return resource;
    } catch (error) {
        if (error.code === 404) {
            return null;
        }
        throw error;
    }
}
```

**적용 시나리오:**
- 고객별 주문 조회
- 테넌트별 데이터 분리
- 계층적 데이터 구조

---

## 3. 고성능 시나리오별 패턴

### 시나리오 1: MySQL에서 Key를 가져와서 CosmosDB 조회

많은 경우 MySQL에 메타데이터가 있고, CosmosDB에 상세 데이터가 저장되어 있습니다.

```javascript
// MySQL에서 ID와 Partition Key 조회
async function getUserDetailsFromMySQL(userId) {
    const connection = await mysql.createConnection(mysqlConfig);
    const [rows] = await connection.execute(
        'SELECT cosmos_id, partition_key FROM user_index WHERE user_id = ?',
        [userId]
    );
    
    if (rows.length === 0) {
        return null;
    }
    
    const { cosmos_id, partition_key } = rows[0];
    
    // Point Read로 CosmosDB에서 상세 정보 조회
    const { resource } = await cosmosContainer.item(cosmos_id, partition_key).read();
    return resource;
}
```

**최적화 포인트:**
- MySQL 조회와 CosmosDB Point Read를 병렬 처리 가능한 경우 Promise.all 사용
- MySQL 조회 결과를 in-memory cache(Redis 등)에 저장하여 반복 조회 최소화

### 시나리오 2: 초고속 응답이 필요한 경우 (밀리세컨 단위)

API 응답 시간이 5ms 이하여야 하는 경우:

```javascript
import { createClient } from 'redis';

const redis = createClient();
await redis.connect();

async function getWithCache(id, partitionKey) {
    const cacheKey = `cosmos:${id}:${partitionKey}`;
    
    // 1. Redis 캐시 확인 (1-2ms)
    const cached = await redis.get(cacheKey);
    if (cached) {
        return JSON.parse(cached);
    }
    
    // 2. CosmosDB Point Read (5-10ms)
    const { resource } = await container.item(id, partitionKey).read();
    
    // 3. Redis에 캐싱 (TTL: 5분)
    if (resource) {
        await redis.setex(cacheKey, 300, JSON.stringify(resource));
    }
    
    return resource;
}
```

**적용 시나리오:**
- 실시간 대시보드 (초당 수천 건 조회)
- 모바일 앱 초기 로딩 (빠른 응답 필수)
- 결제 시스템 (낮은 지연시간 요구)

**예상 성능:**
- 캐시 히트: 1-2ms, 0 RU
- 캐시 미스: 5-10ms, 1 RU

### 시나리오 3: 대량 트래픽 환경 (초당 수만 건)

트래픽이 매우 높은 환경에서는 병렬 처리가 중요합니다.

```javascript
async function batchGetUsers(userIds) {
    // 병렬 Point Read (최대 동시성 제어)
    const batchSize = 50; // 동시에 50개씩 처리
    const results = [];
    
    for (let i = 0; i < userIds.length; i += batchSize) {
        const batch = userIds.slice(i, i + batchSize);
        const promises = batch.map(async (id) => {
            try {
                const { resource } = await container.item(id, id).read();
                return resource;
            } catch (error) {
                if (error.code === 404) return null;
                throw error;
            }
        });
        
        const batchResults = await Promise.all(promises);
        results.push(...batchResults.filter(r => r !== null));
    }
    
    return results;
}
```

**최적화 포인트:**
- 동시성 제어로 네트워크 병목 방지
- 429 에러 발생 시 재시도 로직 구현
- Connection Pool 재사용

### 시나리오 4: Partition Key를 모르는 경우 - Fallback 전략

```javascript
const partitionKeyCache = new Map();

async function getItemWithFallback(id) {
    // 1. 캐시에서 Partition Key 조회
    const cachedPK = partitionKeyCache.get(id);
    
    if (cachedPK) {
        try {
            const { resource } = await container.item(id, cachedPK).read();
            return resource;
        } catch (error) {
            if (error.code === 404) {
                // 캐시된 PK가 잘못된 경우
                partitionKeyCache.delete(id);
            } else {
                throw error;
            }
        }
    }
    
    // 2. Query로 조회 (첫 번째 조회 시에만)
    const querySpec = {
        query: 'SELECT * FROM c WHERE c.id = @id',
        parameters: [{ name: '@id', value: id }]
    };
    const { resources } = await container.items.query(querySpec).fetchAll();
    
    if (resources.length > 0) {
        const item = resources[0];
        // Partition Key 캐싱 (문서에서 추출)
        partitionKeyCache.set(id, item.partitionKey || item.id);
        return item;
    }
    
    return null;
}
```

**적용 시나리오:**
- 레거시 시스템 마이그레이션 중
- Partition Key 정보를 별도로 관리하지 않는 경우
- 점진적 최적화 (Query → Point Read 전환)

---

## 4. Partition Key 설계 전략

### 전략 1: ID 기반 (단순 패턴)

```javascript
// Container 정의
const containerDefinition = {
    id: 'users',
    partitionKey: { paths: ['/id'] }
};

// 사용
await container.item(userId, userId).read();
```

**장점:**
- Point Read가 매우 간단
- 구현 복잡도 낮음

**단점:**
- 관련 데이터를 함께 조회하기 어려움
- 파티션 수가 많아질 수 있음

### 전략 2: 논리적 그룹 (확장 가능 패턴)

```javascript
// Container 정의
const containerDefinition = {
    id: 'documents',
    partitionKey: { paths: ['/tenantId'] }
};

// 문서 구조
{
    "id": "doc123",
    "tenantId": "tenant456",  // Partition Key
    "data": { ... }
}

// 사용
await container.item('doc123', 'tenant456').read();
```

**장점:**
- 테넌트별 데이터 격리
- 같은 테넌트의 문서를 효율적으로 조회
- 트랜잭션 가능 (같은 파티션 내)

**단점:**
- Hot Partition 가능성 (큰 테넌트)
- Partition Key를 항상 알아야 함

### 전략 3: Hierarchical Partition Keys (최신 패턴)

```javascript
// Cosmos DB SDK v3.17.0 이상에서 지원
const containerDefinition = {
    id: 'telemetry',
    partitionKey: { 
        paths: ['/tenantId', '/deviceId'],
        version: 2  // Hierarchical Partition Key
    }
};

// 사용
await container.item('reading123', ['tenant1', 'device456']).read();
```

**장점:**
- 더 세밀한 파티션 분할
- Hot Partition 방지
- 유연한 쿼리 패턴

**단점:**
- SDK 버전 요구사항
- 복잡도 증가

---

## 5. 연결 최적화

### 클라이언트 재사용 (필수)

```javascript
// ❌ 나쁜 예: 매번 새 클라이언트 생성
function getClient() {
    return new CosmosClient({ endpoint, key });
}

// ✅ 좋은 예: 싱글톤 패턴
let cosmosClient = null;

function getClient() {
    if (!cosmosClient) {
        cosmosClient = new CosmosClient({ 
            endpoint: process.env.COSMOS_ENDPOINT,
            key: process.env.COSMOS_KEY,
            connectionPolicy: {
                requestTimeout: 10000,
                retryOptions: {
                    maxRetryAttemptCount: 3,
                    fixedRetryIntervalInMilliseconds: 100
                }
            }
        });
    }
    return cosmosClient;
}
```

### Preferred Locations 설정

```javascript
const client = new CosmosClient({
    endpoint,
    key,
    connectionPolicy: {
        // 가장 가까운 리전을 우선 사용
        preferredLocations: ['Korea Central', 'Japan East', 'Southeast Asia']
    }
});
```

**효과:**
- 네트워크 지연 시간 최소화
- 자동 failover 지원
- 읽기 트래픽 분산 (여러 deployment 사용 시)

---

## 6. 에러 처리 및 재시도 패턴

### 429 에러 처리 (Rate Limiting)

```javascript
async function pointReadWithRetry(id, partitionKey, maxRetries = 3) {
    for (let attempt = 0; attempt < maxRetries; attempt++) {
        try {
            const { resource } = await container.item(id, partitionKey).read();
            return resource;
        } catch (error) {
            if (error.code === 429) {
                // Rate limit 초과 - exponential backoff
                const delayMs = Math.pow(2, attempt) * 100;
                await new Promise(resolve => setTimeout(resolve, delayMs));
                continue;
            }
            if (error.code === 404) {
                return null;
            }
            throw error;
        }
    }
    throw new Error('Max retries exceeded');
}
```

### 타임아웃 처리

```javascript
async function pointReadWithTimeout(id, partitionKey, timeoutMs = 5000) {
    const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error('Timeout')), timeoutMs)
    );
    
    const readPromise = container.item(id, partitionKey).read();
    
    try {
        const { resource } = await Promise.race([readPromise, timeoutPromise]);
        return resource;
    } catch (error) {
        if (error.message === 'Timeout') {
            console.error(`Point Read timeout for ${id}`);
        }
        throw error;
    }
}
```

---

## 7. 모니터링 및 성능 측정

### RU 소비량 추적

```javascript
async function trackedPointRead(id, partitionKey) {
    const startTime = Date.now();
    
    try {
        const response = await container.item(id, partitionKey).read();
        const duration = Date.now() - startTime;
        const ru = response.requestCharge;
        
        console.log({
            operation: 'Point Read',
            id,
            duration,
            requestCharge: ru
        });
        
        return response.resource;
    } catch (error) {
        console.error('Point Read failed', { id, error: error.message });
        throw error;
    }
}
```

### Application Insights 연동

```javascript
import appInsights from 'applicationinsights';

appInsights.setup(process.env.APPLICATIONINSIGHTS_CONNECTION_STRING).start();
const telemetryClient = appInsights.defaultClient;

async function monitoredPointRead(id, partitionKey) {
    const startTime = Date.now();
    
    try {
        const response = await container.item(id, partitionKey).read();
        
        telemetryClient.trackDependency({
            target: 'CosmosDB',
            name: 'Point Read',
            data: `${id}/${partitionKey}`,
            duration: Date.now() - startTime,
            resultCode: 200,
            success: true
        });
        
        telemetryClient.trackMetric({
            name: 'CosmosDB RU Consumed',
            value: response.requestCharge
        });
        
        return response.resource;
    } catch (error) {
        telemetryClient.trackException({ exception: error });
        throw error;
    }
}
```

---

## 8. 실전 적용 체크리스트

### 즉시 적용 가능 (Quick Wins)
- [ ] ID 기반 Query를 Point Read로 전환
- [ ] CosmosClient 싱글톤 패턴 적용
- [ ] 404 에러 명시적 처리
- [ ] RU 소비량 로깅

### 중기 개선
- [ ] Partition Key 캐싱 구현
- [ ] Redis 캐시 레이어 추가
- [ ] 병렬 처리 도입 (Promise.all)
- [ ] Preferred Locations 설정
- [ ] 429 에러 재시도 로직

### 장기 전략
- [ ] Partition Key 재설계 검토
- [ ] Hierarchical Partition Keys 도입
- [ ] 자동화된 성능 모니터링
- [ ] 캐시 워밍 전략

---

## 9. 마이그레이션 가이드: Query → Point Read

### 1단계: 현재 Query 패턴 식별

```javascript
// Before: Query 사용
async function getUserOld(userId) {
    const querySpec = {
        query: 'SELECT * FROM c WHERE c.id = @id',
        parameters: [{ name: '@id', value: userId }]
    };
    const { resources } = await container.items.query(querySpec).fetchAll();
    return resources[0];
}
```

### 2단계: Partition Key 확보 방안 수립

```javascript
// Option A: ID가 Partition Key인 경우
const partitionKey = userId;

// Option B: 별도 필드가 Partition Key인 경우
// MySQL 등에서 조회하거나 캐시 활용

// Option C: 문서에 포함된 경우
// 첫 조회 후 캐싱
```

### 3단계: Point Read로 전환

```javascript
// After: Point Read 사용
async function getUserNew(userId) {
    try {
        const { resource } = await container.item(userId, userId).read();
        return resource;
    } catch (error) {
        if (error.code === 404) {
            return null;
        }
        throw error;
    }
}
```

### 4단계: 성능 검증

```javascript
// 성능 비교 함수
async function comparePerformance(userId) {
    // Query 방식
    const queryStart = Date.now();
    const userByQuery = await getUserOld(userId);
    const queryTime = Date.now() - queryStart;
    const queryRU = /* response에서 추출 */;
    
    // Point Read 방식
    const pointReadStart = Date.now();
    const userByPointRead = await getUserNew(userId);
    const pointReadTime = Date.now() - pointReadStart;
    const pointReadRU = /* response에서 추출 */;
    
    console.log({
        query: { time: queryTime, ru: queryRU },
        pointRead: { time: pointReadTime, ru: pointReadRU },
        improvement: {
            timeReduction: ((queryTime - pointReadTime) / queryTime * 100).toFixed(2) + '%',
            ruReduction: ((queryRU - pointReadRU) / queryRU * 100).toFixed(2) + '%'
        }
    });
}
```

---

## 참고 자료

- [Azure Cosmos DB Point Reads](https://learn.microsoft.com/azure/cosmos-db/sql/how-to-dotnet-read-item)
- [Optimize Request Units](https://learn.microsoft.com/azure/cosmos-db/optimize-cost-reads-writes)
- [Partition Key Design](https://learn.microsoft.com/azure/cosmos-db/partitioning-overview)
- [CosmosDB SDK for JavaScript](https://learn.microsoft.com/javascript/api/overview/azure/cosmos-readme)
