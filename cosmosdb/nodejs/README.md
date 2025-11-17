# CosmosDB Node.js 최적화 가이드

이 디렉토리는 Azure Cosmos DB를 Node.js에서 효율적으로 사용하기 위한 가이드와 예제 코드를 포함합니다.

## 📚 문서 목록

### 핵심 최적화 가이드

#### 1. [Point Read 패턴](./point_read_pattern.md) ⭐️ **필독**
CosmosDB에서 가장 효율적인 읽기 방식인 Point Read 패턴에 대한 종합 가이드

**주요 내용:**
- Point Read vs Query 성능 비교 (RU 비용 90% 절감)
- 구현 패턴 및 Best Practices
- Partition Key 설계 전략
- Handler 패턴
- 실전 예제 (Express.js API)

**적용 효과:** RU 비용 90% 절감, 응답 속도 5-10배 개선

---

#### 2. [최적화 전략 종합 가이드](./optimization_strategy.md)
CosmosDB 성능 최적화를 위한 전략적 가이드

**주요 내용:**
- Point Read 최적화
- 연결 및 네트워크 최적화 (Direct Mode, Preferred Locations)
- Partition Key 설계 원칙
- 캐싱 전략 (Partition Key 캐싱, Redis 연동)
- 배치 처리 최적화
- 모니터링 및 측정

**포함 내용:** 체크리스트, 실전 사례, 성능 개선 수치

---

#### 3. [클라이언트 최적화](./client.md)
CosmosDB 클라이언트 설정 및 읽기 트래픽 분산

**주요 내용:**
- Preferred Locations를 통한 읽기 분산
- 다중 Deployment 전략
- 랜덤 라우팅을 통한 부하 분산

---

#### 4. [DNS 캐싱 및 스레드 풀 최적화](./query_thread_with_low_core.md)
Node.js에서 CosmosDB 연속 쿼리 시 DNS Lookup 병목 해결

**주요 내용:**
- DNS 캐싱 구현 (cacheable-lookup)
- UV_THREADPOOL_SIZE 조정
- NodeLocal DNSCache 활용

---

## 💻 예제 코드

### [examples/point_read_simple.js](./examples/point_read_simple.js)
Point Read 기본 사용법 예제

```javascript
// Point Read - 가장 효율적 (~1 RU)
const user = await getUserByPointRead('user123', 'user123');

// Query와 성능 비교
await comparePerformance('user123');
```

**포함 기능:**
- 단일 Point Read
- 일괄 조회 (Batch)
- 성능 비교 함수
- 존재 여부 확인

---

### [examples/cosmos_handler.js](./examples/cosmos_handler.js)
재사용 가능한 CosmosDB Handler 패턴

```javascript
const handler = new CosmosHandler(client, 'myDb', 'users');

// Point Read
const user = await handler.getById('user123', 'user123');

// 일괄 조회
const users = await handler.getByIds([...]);

// 캐싱 지원
const cachedHandler = new CachedCosmosHandler(client, 'myDb', 'users');
```

**포함 클래스:**
- `CosmosHandler`: 기본 CRUD 작업
- `CachedCosmosHandler`: Partition Key 캐싱 지원

---

## 🚀 빠른 시작

### 1. Point Read로 즉시 성능 개선

```javascript
// Before: Query 사용 (비효율적, ~5 RU)
const { resources } = await container.items
    .query('SELECT * FROM c WHERE c.id = @id')
    .fetchAll();

// After: Point Read 사용 (효율적, ~1 RU)
const { resource } = await container
    .item('user123', 'user123')
    .read();
```

### 2. Handler 패턴 적용

```javascript
import { CosmosHandler } from './examples/cosmos_handler.js';

const userHandler = new CosmosHandler(client, 'myDb', 'users', {
    enableLogging: true
});

// 간단한 API
const user = await userHandler.getById('user123', 'user123');
const users = await userHandler.getByIds([...]);
```

### 3. 성능 모니터링 추가

```javascript
const { resource, requestCharge } = await container.item(id, pk).read();
console.log(`RU Consumed: ${requestCharge}`);
```

---

## 📊 기대 효과

| 최적화 항목 | 개선 효과 |
|------------|----------|
| Query → Point Read 전환 | RU 비용 80-90% 절감 |
| 병렬 처리 도입 | 처리 시간 95% 단축 |
| DNS 캐싱 | CPU 사용률 30-50% 감소 |
| Redis 캐싱 | 자주 조회되는 데이터 0 RU |
| Direct Mode 활성화 | 응답 속도 10-20% 개선 |

**종합 효과:** 
- 월 비용 50-80% 절감
- 응답 시간 5-10배 개선
- 처리량 10-20배 증가

---

## ⚡️ 우선순위별 적용 가이드

### 🔥 즉시 적용 (Quick Wins)
1. ID 기반 Query를 Point Read로 전환
2. CosmosClient 싱글톤 패턴
3. Direct Mode 활성화
4. Preferred Locations 설정

### 📈 중기 개선
1. Handler 패턴으로 리팩토링
2. Partition Key 캐싱
3. 병렬 처리 도입
4. RU 모니터링 대시보드

### 🎯 장기 전략
1. Partition Key 재설계
2. Redis 캐싱 레이어
3. 지역별 읽기 분산
4. Auto-scale 최적화

---

## 🔗 참고 자료

### Microsoft 공식 문서
- [Azure Cosmos DB Best Practices](https://learn.microsoft.com/azure/cosmos-db/nosql/best-practice-dotnet)
- [Point Reads](https://learn.microsoft.com/azure/cosmos-db/sql/how-to-dotnet-read-item)
- [Partition Key Design](https://learn.microsoft.com/azure/cosmos-db/partitioning-overview)
- [Performance Tips](https://learn.microsoft.com/azure/cosmos-db/performance-tips)

### SDK 문서
- [CosmosDB SDK for JavaScript](https://learn.microsoft.com/javascript/api/overview/azure/cosmos-readme)
- [Connection Policy](https://learn.microsoft.com/javascript/api/@azure/cosmos/connectionpolicy)

---

## 💡 주요 개념 요약

### Point Read란?
ID와 Partition Key를 정확히 알고 있을 때 사용하는 가장 효율적인 읽기 방식
- **RU 비용:** ~1 RU (Query 대비 90% 절감)
- **응답 속도:** 5-10ms (Query 대비 5-10배 빠름)
- **사용 조건:** ID + Partition Key 필수

### Partition Key란?
CosmosDB에서 데이터를 논리적으로 분할하는 기준
- **좋은 PK:** 높은 카디널리티, 균등 분산, 쿼리 패턴 일치
- **나쁜 PK:** 모든 문서에 같은 값, 너무 세밀한 값

### Handler 패턴이란?
CosmosDB 작업을 추상화하여 재사용 가능한 계층을 만드는 패턴
- **장점:** 코드 재사용, 일관된 에러 처리, 쉬운 테스트
- **기능:** Point Read, CRUD, 캐싱, 로깅

---

## 🤝 기여 및 피드백

이 문서들은 실전 경험을 바탕으로 작성되었습니다. 
개선 사항이나 추가할 내용이 있다면 기여해 주세요!

---

**Last Updated:** 2024-11-17  
**Maintained by:** CosmosDB Optimization Team
