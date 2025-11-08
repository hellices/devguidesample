# CosmosDB Client 최적화 방안

## 개요
CosmosDB 클라이언트의 성능 최적화를 위한 읽기 트래픽 분산 전략 문서입니다.

---

## 1. Preferred Locations를 통한 읽기 트래픽 분산

### 개념
CosmosDB SDK의 `preferredLocations` 옵션을 사용하여 **읽기 요청을 여러 리전에 분산**시킵니다.

### 동작 방식
- **읽기 전용**: `preferredLocations`는 읽기 작업에만 적용됩니다
- **쓰기**: 모든 쓰기 작업은 자동으로 현재 쓰기 지역(Write Region)으로 전송됩니다
- **우선순위**: SDK는 `preferredLocations` 목록의 **첫 번째 리전**에서 읽기를 시도합니다
- **자동 Failover**: 첫 번째 리전이 응답하지 않으면 자동으로 다음 리전으로 시도합니다

### 구현 코드
```javascript
import { CosmosClient } from '@azure/cosmos';
import { DefaultAzureCredential } from '@azure/identity';

let cosmosClient;

const preferredLocations = process.env.COSMOS_PREFERRED_LOCATIONS 
    ? process.env.COSMOS_PREFERRED_LOCATIONS.split(',').map(region => region.trim())
    : ['West US', 'East US', 'North Europe'];

const credential = new DefaultAzureCredential();
cosmosClient = new CosmosClient({ 
    endpoint: process.env.COSMOS_ENDPOINT, 
    aadCredentials: credential, 
    connectionPolicy: { preferredLocations }
});
```

---

## 2. 환경변수를 통한 Deployment별 읽기 분산

### 전략
`preferredLocations`는 첫 번째 리전에서 우선 읽기를 수행하는 Fallback 전략이므로, 여러 Deployment를 생성하고 각각 다른 우선순위를 설정하면 읽기 트래픽을 여러 리전에 분산할 수 있습니다.

### Kubernetes Deployment 예시
```yaml
# Deployment A - West US 우선
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-a
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: api-a
        image: api:latest
        env:
        - name: COSMOS_PREFERRED_LOCATIONS
          value: "West US,East US,North Europe"

---
# Deployment B - East US 우선
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-b
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: api
        image: api:latest
        env:
        - name: COSMOS_PREFERRED_LOCATIONS
          value: "East US,West US,North Europe"
```

### 동작 원리
1. **Deployment A (api-a)**: West US 리전에서 읽기 수행
2. **Deployment B (api-b)**: East US 리전에서 읽기 수행
3. **로드밸런서**가 트래픽을 두 Deployment에 분산
4. **결과**: West US와 East US에 읽기 트래픽이 **균등하게 분산**

### 효과
✅ Fallback 전략의 한계를 극복하여 읽기 트래픽을 여러 리전에 분산  
✅ 단일 리전 과부하 방지  
✅ 코드 변경 없이 환경변수만으로 제어  
✅ SDK의 자동 Failover 기능 유지  

---

## 3. 다중 클라이언트를 통한 랜덤 라우팅 전략

### 문제점
Section 1의 `preferredLocations` 방식은 첫 번째 리전에서 우선적으로 읽기를 수행하고, 장애 시에만 다음 리전으로 **순차적으로 failover**를 수행합니다. 이로 인해:
- ❌ 정상 상황에서는 첫 번째 리전에 부하가 집중됨
- ❌ Replica를 균등하게 활용하지 못함
- ❌ 특정 리전의 부하가 높아질 때 대응이 어려움

### 해결 방안
여러 개의 CosmosDB 클라이언트를 생성하되, 각 클라이언트마다 다른 우선순위의 `preferredLocations`를 설정합니다. 그런 다음 요청마다 **랜덤하게 클라이언트를 선택**하여 읽기 트래픽을 모든 Replica에 고르게 분산시킵니다.

### 구현 코드

#### 3.1. 다중 클라이언트 생성
```javascript
import { CosmosClient } from '@azure/cosmos';
import { DefaultAzureCredential } from '@azure/identity';

// 사용할 리전 목록
const regions = process.env.COSMOS_PREFERRED_LOCATIONS 
    ? process.env.COSMOS_PREFERRED_LOCATIONS.split(',').map(region => region.trim())
    : ['West US', 'East US', 'North Europe'];

const credential = new DefaultAzureCredential();
const endpoint = process.env.COSMOS_ENDPOINT;

// 각 리전을 우선순위로 하는 클라이언트 배열 생성
const cosmosClients = regions.map((region, index) => {
    // 현재 리전을 첫 번째로, 나머지를 순환 배치
    const preferredLocations = [
        region,
        ...regions.slice(index + 1),
        ...regions.slice(0, index)
    ];
    
    return new CosmosClient({
        endpoint,
        aadCredentials: credential,
        connectionPolicy: { preferredLocations }
    });
});

// 랜덤 클라이언트 선택 함수
function getRandomClient() {
    const randomIndex = Math.floor(Math.random() * cosmosClients.length);
    return cosmosClients[randomIndex];
}
```

#### 3.2. 라우팅 래퍼 함수
```javascript
// 읽기 요청용 랜덤 라우팅
async function queryWithRandomRouting(databaseId, containerId, querySpec) {
    const client = getRandomClient();
    const container = client.database(databaseId).container(containerId);
    const { resources } = await container.items.query(querySpec).fetchAll();
    return resources;
}

// 쓰기 요청은 첫 번째 클라이언트 사용 (모든 클라이언트가 동일한 Write Region으로 전송)
async function createItemWithRouting(databaseId, containerId, item) {
    const client = cosmosClients[0]; // 쓰기는 항상 첫 번째 클라이언트 사용
    const container = client.database(databaseId).container(containerId);
    const { resource } = await container.items.create(item);
    return resource;
}
```

#### 3.3. 실제 사용 예시
```javascript
// Express.js 예시
import express from 'express';

const app = express();

app.get('/users/:id', async (req, res) => {
    try {
        const querySpec = {
            query: 'SELECT * FROM c WHERE c.id = @id',
            parameters: [{ name: '@id', value: req.params.id }]
        };
        
        // 랜덤하게 선택된 클라이언트로 읽기 수행
        const users = await queryWithRandomRouting('mydb', 'users', querySpec);
        res.json(users[0]);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.post('/users', async (req, res) => {
    try {
        // 쓰기는 첫 번째 클라이언트로 수행
        const newUser = await createItemWithRouting('mydb', 'users', req.body);
        res.status(201).json(newUser);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});
```

### 동작 원리
1. **클라이언트 생성**: 3개 리전이 있다면 3개의 클라이언트를 생성
   - Client 1: `preferredLocations: ['West US', 'East US', 'North Europe']`
   - Client 2: `preferredLocations: ['East US', 'North Europe', 'West US']`
   - Client 3: `preferredLocations: ['North Europe', 'West US', 'East US']`
2. **랜덤 라우팅**: 각 읽기 요청마다 클라이언트를 랜덤하게 선택
3. **부하 분산**: 통계적으로 모든 리전에 읽기 트래픽이 균등하게 분산
4. **자동 Failover**: 각 클라이언트는 여전히 SDK의 Failover 기능 활용

### 효과
✅ 모든 Replica에 읽기 트래픽 균등 분산  
✅ 특정 리전 부하 집중 문제 해결  
✅ SDK의 자동 Failover 기능 유지  
✅ 코드 레벨에서 간단하게 구현 가능  
✅ Deployment 분리 없이 단일 애플리케이션에서 구현 가능  

### 주의사항
⚠️ **연결 수 증가**: 클라이언트 수만큼 연결이 생성되므로 리소스 사용량 고려 필요  
⚠️ **메모리 사용**: 각 클라이언트가 독립적인 캐시와 메타데이터를 유지  
⚠️ **쓰기 처리**: 쓰기는 모든 클라이언트에서 동일한 Write Region으로 전송되므로 첫 번째 클라이언트 사용 권장  

---

## 참고 자료
- [Cosmos DB Connection Policy](https://learn.microsoft.com/javascript/api/@azure/cosmos/connectionpolicy)


