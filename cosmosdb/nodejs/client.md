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

## 참고 자료
- [Cosmos DB Connection Policy](https://learn.microsoft.com/javascript/api/@azure/cosmos/connectionpolicy)


