# CosmosDB Point Read 최적화 패턴

## 개요
CosmosDB에서 **Point Read**는 문서의 ID와 Partition Key를 정확히 알고 있을 때 사용하는 가장 효율적인 읽기 방식입니다. Query 방식 대비 **RU(Request Unit) 비용이 약 10배 낮고, 응답 속도도 빠릅니다**.

---

## 1. Point Read vs Query 비교

### Query 방식 (비효율적)
```javascript
const querySpec = {
    query: 'SELECT * FROM c WHERE c.id = @id',
    parameters: [{ name: '@id', value: 'user123' }]
};
const { resources } = await container.items.query(querySpec).fetchAll();
const item = resources[0];
```

**문제점:**
- ❌ Index를 스캔하는 쿼리 엔진 실행
- ❌ 높은 RU 비용 (약 3-10 RU)
- ❌ Partition Key가 없으면 cross-partition query 발생 → 매우 비효율적

### Point Read 방식 (효율적)
```javascript
const { resource: item } = await container.item('user123', 'partitionKeyValue').read();
```

**장점:**
- ✅ 직접 문서 접근 (인덱스 스캔 없음)
- ✅ 낮은 RU 비용 (약 1 RU)
- ✅ 빠른 응답 속도
- ✅ 예측 가능한 성능

### 성능 비교

| 방식 | RU 비용 | 응답 시간 | 사용 사례 |
|------|---------|-----------|-----------|
| Point Read | ~1 RU | 5-10ms | ID + Partition Key를 정확히 아는 경우 |
| Query (단일 파티션) | ~3-10 RU | 20-50ms | 조건 검색이 필요한 경우 |
| Cross-Partition Query | ~10-100+ RU | 100-500ms+ | 파티션 키를 모르는 경우 |

---

## 2. Point Read 구현 패턴

### 기본 구현
```javascript
import { CosmosClient } from '@azure/cosmos';

const client = new CosmosClient({ endpoint, key });
const database = client.database('myDatabase');
const container = database.container('myContainer');

// Point Read
async function getItemById(id, partitionKey) {
    try {
        const { resource: item } = await container
            .item(id, partitionKey)
            .read();
        return item;
    } catch (error) {
        if (error.code === 404) {
            return null; // 문서 없음
        }
        throw error;
    }
}

// 사용 예시
const user = await getItemById('user123', 'user123'); // id가 partition key인 경우
const order = await getItemById('order456', 'customer789'); // partition key가 다른 경우
```

### Partition Key 설계 전략

Point Read를 효과적으로 사용하려면 **Partition Key 설계가 중요**합니다.

#### 패턴 1: ID를 Partition Key로 사용
```javascript
// Container 생성 시
const containerDefinition = {
    id: 'users',
    partitionKey: { paths: ['/id'] }
};

// Point Read
const user = await container.item('user123', 'user123').read();
```

**장점:** Point Read 구현이 간단  
**단점:** 파티션이 너무 많이 생성될 수 있음 (hot partition 문제는 없음)

#### 패턴 2: 논리적 그룹을 Partition Key로 사용
```javascript
// Container 생성 시
const containerDefinition = {
    id: 'orders',
    partitionKey: { paths: ['/customerId'] }
};

// 문서 구조
{
    "id": "order123",
    "customerId": "customer456", // Partition Key
    "items": [...]
}

// Point Read
const order = await container.item('order123', 'customer456').read();
```

**장점:** 관련 데이터를 같은 파티션에 배치 (효율적인 트랜잭션)  
**단점:** Partition Key를 항상 알아야 함

#### 패턴 3: 복합 Partition Key 활용 (Hierarchical Partition Keys)
```javascript
// Cosmos DB v3.17.0+에서 지원
const containerDefinition = {
    id: 'telemetry',
    partitionKey: { 
        paths: ['/tenantId', '/deviceId'],
        version: 2 
    }
};

// Point Read
const telemetry = await container
    .item('reading123', ['tenant1', 'device456'])
    .read();
```

---

## 3. Point Read Handler 패턴

실제 프로젝트에서는 Point Read 로직을 재사용 가능한 핸들러로 추상화하는 것이 좋습니다.

### 기본 Handler 구현
```javascript
class CosmosHandler {
    constructor(client, databaseId, containerId) {
        this.container = client
            .database(databaseId)
            .container(containerId);
    }

    /**
     * Point Read로 단일 문서 조회
     * @param {string} id - 문서 ID
     * @param {string|Array} partitionKey - Partition Key 값
     * @returns {Promise<Object|null>} 문서 또는 null
     */
    async getById(id, partitionKey) {
        try {
            const { resource } = await this.container
                .item(id, partitionKey)
                .read();
            return resource;
        } catch (error) {
            if (error.code === 404) {
                return null;
            }
            throw error;
        }
    }

    /**
     * 여러 문서를 Point Read로 일괄 조회
     * @param {Array<{id: string, partitionKey: string|Array}>} items
     * @returns {Promise<Array>} 조회된 문서 배열
     */
    async getByIds(items) {
        const promises = items.map(({ id, partitionKey }) => 
            this.getById(id, partitionKey)
        );
        const results = await Promise.all(promises);
        return results.filter(item => item !== null);
    }

    /**
     * Point Read로 문서 존재 여부 확인
     * @param {string} id
     * @param {string|Array} partitionKey
     * @returns {Promise<boolean>}
     */
    async exists(id, partitionKey) {
        const item = await this.getById(id, partitionKey);
        return item !== null;
    }

    /**
     * Query 사용 (Point Read를 사용할 수 없는 경우)
     * @param {Object} querySpec
     * @param {string|Array} partitionKey - 선택적, 없으면 cross-partition query
     * @returns {Promise<Array>}
     */
    async query(querySpec, partitionKey = undefined) {
        const options = partitionKey ? { partitionKey } : {};
        const { resources } = await this.container.items
            .query(querySpec, options)
            .fetchAll();
        return resources;
    }
}
```

### 사용 예시
```javascript
// Handler 초기화
const cosmosClient = new CosmosClient({ endpoint, key });
const userHandler = new CosmosHandler(cosmosClient, 'myDatabase', 'users');

// Point Read - 단일 조회
const user = await userHandler.getById('user123', 'user123');
if (user) {
    console.log('User found:', user.name);
}

// Point Read - 일괄 조회
const users = await userHandler.getByIds([
    { id: 'user123', partitionKey: 'user123' },
    { id: 'user456', partitionKey: 'user456' },
    { id: 'user789', partitionKey: 'user789' }
]);
console.log(`Found ${users.length} users`);

// 존재 여부 확인
const exists = await userHandler.exists('user123', 'user123');

// Query 사용 (필요한 경우만)
const activeUsers = await userHandler.query({
    query: 'SELECT * FROM c WHERE c.status = @status',
    parameters: [{ name: '@status', value: 'active' }]
}, 'user123'); // 특정 파티션 내에서만 검색
```

---

## 4. Query에서 Point Read로 전환하는 패턴

### 전환 전략

#### 1단계: ID 기반 Query 식별
```javascript
// Before: Query 사용
const querySpec = {
    query: 'SELECT * FROM c WHERE c.id = @id',
    parameters: [{ name: '@id', value: userId }]
};
const { resources } = await container.items.query(querySpec).fetchAll();
const user = resources[0];
```

#### 2단계: Partition Key 추출 로직 추가
```javascript
// Partition Key 결정 로직
function getPartitionKey(id, type) {
    switch(type) {
        case 'user':
            return id; // user는 id가 partition key
        case 'order':
            // order는 customerId가 partition key
            // 별도 조회나 캐시가 필요할 수 있음
            return getCustomerIdFromCache(id);
        default:
            throw new Error('Unknown type');
    }
}
```

#### 3단계: Point Read로 전환
```javascript
// After: Point Read 사용
const partitionKey = getPartitionKey(userId, 'user');
const { resource: user } = await container.item(userId, partitionKey).read();
```

### 하이브리드 접근법

Partition Key를 모르는 경우를 대비한 Fallback 패턴:

```javascript
async function getUser(userId, partitionKey = null) {
    if (partitionKey) {
        // Point Read 사용 (효율적)
        try {
            const { resource } = await container.item(userId, partitionKey).read();
            return resource;
        } catch (error) {
            if (error.code === 404) return null;
            throw error;
        }
    } else {
        // Partition Key를 모르는 경우 Query 사용 (비효율적)
        console.warn('Using Query instead of Point Read - consider caching partition keys');
        const querySpec = {
            query: 'SELECT * FROM c WHERE c.id = @id',
            parameters: [{ name: '@id', value: userId }]
        };
        const { resources } = await container.items.query(querySpec).fetchAll();
        return resources[0] || null;
    }
}

// 사용
const user1 = await getUser('user123', 'user123'); // Point Read - 빠름
const user2 = await getUser('user456'); // Query - 느림
```

---

## 5. Point Read 최적화 전략

### 전략 1: Partition Key 캐싱
ID로 Partition Key를 자주 조회해야 하는 경우 캐싱을 활용:

```javascript
class CachedCosmosHandler extends CosmosHandler {
    constructor(client, databaseId, containerId, cacheOptions = {}) {
        super(client, databaseId, containerId);
        this.cache = new Map();
        this.cacheTTL = cacheOptions.ttl || 300000; // 5분 기본값
    }

    async getById(id, partitionKey = null) {
        // Partition Key가 제공되면 Point Read
        if (partitionKey) {
            const item = await super.getById(id, partitionKey);
            // 캐시에 저장
            if (item) {
                this.cachePartitionKey(id, partitionKey);
            }
            return item;
        }

        // 캐시에서 Partition Key 조회
        const cachedPartitionKey = this.getCachedPartitionKey(id);
        if (cachedPartitionKey) {
            return await super.getById(id, cachedPartitionKey);
        }

        // Fallback: Query 사용
        const querySpec = {
            query: 'SELECT * FROM c WHERE c.id = @id',
            parameters: [{ name: '@id', value: id }]
        };
        const results = await this.query(querySpec);
        if (results.length > 0) {
            const item = results[0];
            // Partition Key 추출 및 캐싱
            const pk = this.extractPartitionKey(item);
            this.cachePartitionKey(id, pk);
            return item;
        }
        return null;
    }

    cachePartitionKey(id, partitionKey) {
        this.cache.set(id, {
            partitionKey,
            expires: Date.now() + this.cacheTTL
        });
    }

    getCachedPartitionKey(id) {
        const cached = this.cache.get(id);
        if (cached && cached.expires > Date.now()) {
            return cached.partitionKey;
        }
        this.cache.delete(id);
        return null;
    }

    extractPartitionKey(item) {
        // Container의 partition key 정의에 따라 추출
        // 예: '/userId' -> item.userId
        return item.id; // 간단한 예시
    }
}
```

### 전략 2: Batch Point Read
여러 문서를 효율적으로 조회:

```javascript
async function batchPointRead(items) {
    // 병렬 처리로 여러 Point Read 동시 실행
    const promises = items.map(async ({ id, partitionKey }) => {
        try {
            const { resource } = await container.item(id, partitionKey).read();
            return { success: true, data: resource };
        } catch (error) {
            if (error.code === 404) {
                return { success: false, id, error: 'Not Found' };
            }
            return { success: false, id, error: error.message };
        }
    });

    const results = await Promise.all(promises);
    
    return {
        successful: results.filter(r => r.success).map(r => r.data),
        failed: results.filter(r => !r.success)
    };
}

// 사용
const result = await batchPointRead([
    { id: 'user1', partitionKey: 'user1' },
    { id: 'user2', partitionKey: 'user2' },
    { id: 'user3', partitionKey: 'user3' }
]);

console.log(`성공: ${result.successful.length}, 실패: ${result.failed.length}`);
```

### 전략 3: Read-Through Cache Pattern
```javascript
class ReadThroughCosmosHandler extends CosmosHandler {
    constructor(client, databaseId, containerId, redisClient) {
        super(client, databaseId, containerId);
        this.redis = redisClient;
        this.cacheTTL = 300; // 5분
    }

    async getById(id, partitionKey) {
        // 1. Redis 캐시 확인
        const cacheKey = `cosmos:${this.container.id}:${id}:${partitionKey}`;
        const cached = await this.redis.get(cacheKey);
        
        if (cached) {
            return JSON.parse(cached);
        }

        // 2. CosmosDB Point Read
        const item = await super.getById(id, partitionKey);
        
        if (item) {
            // 3. Redis에 캐싱
            await this.redis.setex(
                cacheKey, 
                this.cacheTTL, 
                JSON.stringify(item)
            );
        }

        return item;
    }
}
```

---

## 6. 실전 예시: Express.js API

### Point Read 기반 REST API
```javascript
import express from 'express';
import { CosmosClient } from '@azure/cosmos';

const app = express();
const client = new CosmosClient({ endpoint, key });
const userHandler = new CosmosHandler(client, 'myDatabase', 'users');

// GET /users/:id - Point Read 사용
app.get('/users/:id', async (req, res) => {
    try {
        const userId = req.params.id;
        
        // Point Read (id가 partition key라고 가정)
        const user = await userHandler.getById(userId, userId);
        
        if (!user) {
            return res.status(404).json({ error: 'User not found' });
        }
        
        res.json(user);
    } catch (error) {
        console.error('Error fetching user:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// POST /users/batch - 여러 사용자 조회
app.post('/users/batch', async (req, res) => {
    try {
        const { userIds } = req.body; // ['user1', 'user2', 'user3']
        
        const items = userIds.map(id => ({ id, partitionKey: id }));
        const users = await userHandler.getByIds(items);
        
        res.json({ 
            count: users.length,
            users 
        });
    } catch (error) {
        console.error('Error in batch fetch:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// GET /orders/:orderId/customer/:customerId - 복합 키 Point Read
app.get('/orders/:orderId/customer/:customerId', async (req, res) => {
    try {
        const { orderId, customerId } = req.params;
        
        // customerId가 partition key
        const orderHandler = new CosmosHandler(client, 'myDatabase', 'orders');
        const order = await orderHandler.getById(orderId, customerId);
        
        if (!order) {
            return res.status(404).json({ error: 'Order not found' });
        }
        
        res.json(order);
    } catch (error) {
        console.error('Error fetching order:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

app.listen(3000, () => {
    console.log('Server running on port 3000');
});
```

---

## 7. 모범 사례 (Best Practices)

### ✅ 권장사항

1. **항상 Point Read 우선 고려**
   - ID와 Partition Key를 알 수 있으면 Point Read 사용
   - Query는 마지막 수단으로만 사용

2. **Partition Key 설계 시 고려사항**
   - 자주 조회되는 패턴에 맞춰 설계
   - Point Read를 최대한 활용할 수 있는 구조
   - Hot Partition 방지

3. **에러 처리**
   - 404 에러를 명시적으로 처리 (문서 없음)
   - 다른 에러는 재시도 또는 로깅

4. **캐싱 전략**
   - 자주 조회되는 데이터는 캐싱
   - Partition Key 정보도 캐싱 고려

5. **모니터링**
   - RU 소비량 모니터링
   - Point Read vs Query 비율 추적
   - 평균 응답 시간 측정

### ❌ 피해야 할 사항

1. **ID만으로 Query 실행**
   ```javascript
   // ❌ 나쁜 예
   const { resources } = await container.items
       .query('SELECT * FROM c WHERE c.id = "user123"')
       .fetchAll();
   
   // ✅ 좋은 예
   const { resource } = await container.item('user123', 'user123').read();
   ```

2. **Cross-Partition Query 남발**
   ```javascript
   // ❌ 나쁜 예 - 모든 파티션 스캔
   const { resources } = await container.items
       .query('SELECT * FROM c WHERE c.id = @id')
       .fetchAll();
   
   // ✅ 좋은 예 - Partition Key 지정
   const { resources } = await container.items
       .query(querySpec, { partitionKey: 'user123' })
       .fetchAll();
   ```

3. **불필요한 필드 조회**
   ```javascript
   // Point Read는 전체 문서를 반환하므로
   // 필요한 필드만 사용하도록 애플리케이션 레벨에서 처리
   const user = await getById('user123', 'user123');
   const { id, name, email } = user; // 필요한 필드만 추출
   ```

---

## 8. 성능 측정 및 모니터링

### RU 소비량 확인
```javascript
async function measureRU(operation) {
    const startTime = Date.now();
    
    const response = await operation();
    
    const endTime = Date.now();
    const requestCharge = response.requestCharge || response.headers['x-ms-request-charge'];
    
    console.log({
        duration: endTime - startTime,
        requestCharge: requestCharge,
        cost: `${requestCharge} RU`
    });
    
    return response;
}

// Point Read 측정
await measureRU(() => container.item('user123', 'user123').read());
// 예상 결과: { duration: 8, requestCharge: 1, cost: '1 RU' }

// Query 측정
await measureRU(() => container.items.query({
    query: 'SELECT * FROM c WHERE c.id = @id',
    parameters: [{ name: '@id', value: 'user123' }]
}).fetchAll());
// 예상 결과: { duration: 45, requestCharge: 2.83, cost: '2.83 RU' }
```

### Application Insights 연동
```javascript
import { DefaultAzureCredential } from '@azure/identity';
import appInsights from 'applicationinsights';

appInsights.setup(process.env.APPLICATIONINSIGHTS_CONNECTION_STRING)
    .setAutoCollectRequests(true)
    .setAutoCollectDependencies(true)
    .start();

const client = appInsights.defaultClient;

async function trackedPointRead(id, partitionKey) {
    const startTime = Date.now();
    
    try {
        const response = await container.item(id, partitionKey).read();
        
        client.trackDependency({
            target: 'CosmosDB',
            name: 'Point Read',
            data: `${id}/${partitionKey}`,
            duration: Date.now() - startTime,
            resultCode: 200,
            success: true,
            dependencyTypeName: 'Azure Cosmos DB'
        });
        
        client.trackMetric({
            name: 'CosmosDB RU Consumed',
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

## 참고 자료

- [Azure Cosmos DB Point Reads](https://learn.microsoft.com/azure/cosmos-db/sql/how-to-dotnet-read-item)
- [Optimize Request Units](https://learn.microsoft.com/azure/cosmos-db/optimize-cost-reads-writes)
- [Partition Key Design](https://learn.microsoft.com/azure/cosmos-db/partitioning-overview)
- [CosmosDB SDK for JavaScript](https://learn.microsoft.com/javascript/api/overview/azure/cosmos-readme)
