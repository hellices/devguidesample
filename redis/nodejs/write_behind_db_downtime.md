# DB Downtime 대응 전략: Write-Behind 패턴

## 문제 정의

DB Version Upgrade 또는 Cutover 작업 시 불가피하게 발생하는 **DB Downtime** 동안, 애플리케이션의 쓰기 요청이 실패하고 데이터 정합성이 깨지는 문제가 발생합니다.

특히 **Recent History**와 같이 실시간 쓰기가 지속되는 업무에서는:

- DB down 시 쓰기 요청 전량 실패
- Pod 재기동 시에도 동기화되지 않은 데이터 복구 불가
- 수작업 정합성 맞추기가 현실적으로 어려움

이 문서에서는 **Write-Behind 패턴**을 적용하여 DB Downtime 동안에도 서비스를 유지하고, 복구 후 데이터 정합성을 자동으로 보장하는 **세 가지 방안**을 제시합니다.

---

## Write-Behind 패턴이란?

Write-Behind(Write-Back)는 데이터를 **캐시 또는 버퍼에 먼저 기록**하고, **비동기적으로 원본 데이터 저장소에 반영**하는 캐싱 패턴입니다.

본 문서의 세 가지 방안은 구현 방식에 따라 두 가지로 분류됩니다:

### 앱 레벨 Write-Behind (방안 1, 2)

앱 코드에서 DB 쓰기 실패를 감지하고, 직접 큐에 적재한 뒤 복구 후 flush합니다.

```
[정상]  App → Write → DB (성공) → Redis Cache 갱신
[장애]  App → Write → DB (실패) → Fallback Queue에 적재 → Redis Cache 갱신
[복구]  Flush Worker → Queue에서 소비 → DB 반영
```

### 네이티브 Write-Behind (방안 3)

앱이 **항상 캐시에만 쓰고**, 캐시 미들웨어가 **자동으로 DB에 비동기 동기화**합니다. 큐잉, 배치, 재시도, 중복 제거가 프레임워크에 내장되어 있습니다.

```
App → Write → Cache (끝) → 미들웨어가 자동으로 DB 동기화
App → Read  → Cache (항상)
```

> **참고**: Redis는 네이티브 Write-Behind를 지원하지 않습니다. 자세한 이유는 [부록 B](#부록-b-redis가-write-behind를-포기한-이유)를 참고하세요. 방안 3에서는 이를 지원하는 Hazelcast를 사용합니다.

### 관련 공식 레퍼런스

| 패턴 | 문서 | 역할 |
|------|------|------|
| Cache-Aside | [Microsoft Learn](https://learn.microsoft.com/azure/architecture/patterns/cache-aside) | 읽기 경로 — DB down 시 캐시에서 제공 |
| Circuit Breaker | [Microsoft Learn](https://learn.microsoft.com/azure/architecture/patterns/circuit-breaker) | DB 장애 감지 및 자동 모드 전환 |
| Queue-Based Load Leveling | [Microsoft Learn](https://learn.microsoft.com/azure/architecture/patterns/queue-based-load-leveling) | 쓰기 버퍼링 — 큐를 통한 비동기 처리 |
| Caching Guidance | [Microsoft Learn](https://learn.microsoft.com/azure/architecture/best-practices/caching) | Write-Through/Write-Behind 전략 가이드 |

---

## DB Down 시 읽기(Read) 동작

Write-Behind 적용과 무관하게, **기존 Cache-Aside 구조에서 DB down 시 읽기가 어떻게 동작하는지** 먼저 이해해야 합니다.

### 읽기 흐름

```
App → Read 요청
  ├─ Redis Cache Hit  → 즉시 반환 ✅
  └─ Redis Cache Miss → DB 조회 시도
                          ├─ DB 정상 → 조회 후 Redis 캐싱 → 반환 ✅
                          └─ DB Down  → 조회 실패 ❌
```

### DB Down 시 읽기 가능 여부

| 데이터 상태 | DB Down 시 읽기 | 이유 |
|------------|----------------|------|
| DB down **이후** Write-Behind로 쓴 데이터 | ✅ 가능 | Write 시 Redis Cache에 동시 갱신 |
| DB down **이전** 최근 조회/갱신된 데이터 | ✅ 가능 | 이미 Redis에 캐싱 (TTL 내) |
| Redis에 **한 번도 캐싱된 적 없는** 데이터 | ❌ 불가 | Redis에 없고, DB 조회도 불가 |

### 읽기 경로 코드 (기존 Cache-Aside — 변경 없음)

Write-Behind를 적용해도 **읽기 경로는 기존 코드 그대로** 사용합니다.

```javascript
async function getRecentHistory(userId) {
    // 1. Redis Cache 확인
    const cached = await redis.get(`history:${userId}`);
    if (cached) {
        return JSON.parse(cached);  // Cache Hit → 즉시 반환
    }

    // 2. Cache Miss → DB 조회
    try {
        const [rows] = await db.query(
            'SELECT * FROM recent_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 20',
            [userId]
        );
        // 3. 조회 결과 Redis에 캐싱
        if (rows.length > 0) {
            await redis.set(`history:${userId}`, JSON.stringify(rows), 'EX', 3600);
        }
        return rows;
    } catch (err) {
        // DB Down → 읽기 실패 (Cache Miss인 데이터만 해당)
        console.error(`[read] DB unavailable, cache miss for user ${userId}`);
        return [];  // 또는 에러 반환
    }
}
```

### 핵심 포인트

Write-Behind에서 **Write 시 Redis Cache를 항상 갱신**하므로, DB down 이후 새로 쓰인 데이터도 읽기가 가능합니다. 이것이 단순 Cache-Aside와의 차이점입니다.

```javascript
// Write 경로에서 캐시를 항상 갱신하는 부분 (아래 방안 1, 2 공통)
await redis.set(`history:${userId}`, JSON.stringify(data), 'EX', 3600);
// → DB 성공/실패 무관하게 실행되므로, 바로 직후 Read 시에도 Cache Hit
```

> Recent History 특성상 **최근 데이터가 조회 대상**이므로, 대부분 Redis에 존재하여 실질적으로 읽기에 문제가 없습니다.

---

## 방안 1: Redis를 Write Buffer로 활용 (최소 코드 변경)

기존에 Redis를 읽기 캐시로 사용 중인 환경에서 **코드 변경을 최소화**하면서 Write-Behind를 적용하는 방안입니다. AOF(Append-Only File)를 활성화하면 Redis 장애 시에도 데이터가 디스크에서 복구되므로, **계획된 DB Downtime 대응으로는 충분한 안정성**을 확보할 수 있습니다.

### 아키텍처

```
[정상 상태]
App → Write → DB (성공) → Redis Cache 갱신
App → Read  → Redis (Hit) → 반환
              Redis (Miss) → DB 조회 → Redis 캐싱

[DB Down 상태]
App → Write → DB (실패) → Redis List에 pending write 적재 → Redis Cache 갱신
App → Read  → Redis (Hit) → 반환 (정상 서비스 유지)

[DB 복구 후]
Flush Worker → Redis List에서 pending write 순차 소비 → DB 반영
```

### 구현

#### Write 경로 — DB 실패 시 Redis List에 적재

```javascript
const PENDING_QUEUE = 'pending_writes';

async function saveRecentHistory(userId, data) {
    const payload = { userId, data, timestamp: Date.now() };

    try {
        await db.query(
            'INSERT INTO recent_history (user_id, data, created_at) VALUES (?, ?, NOW())',
            [userId, JSON.stringify(data)]
        );
    } catch (err) {
        // DB down → Redis List에 write 요청 적재
        await redis.rpush(PENDING_QUEUE, JSON.stringify({
            query: 'INSERT INTO recent_history (user_id, data, created_at) VALUES (?, ?, NOW())',
            params: [userId, JSON.stringify(data)],
            ...payload
        }));
        console.warn(`[write-behind] DB write failed, queued to Redis: ${err.message}`);
    }

    // 캐시는 DB 성공/실패 무관하게 갱신 (읽기 보장)
    await redis.set(`history:${userId}`, JSON.stringify(data), 'EX', 3600);
}
```

#### Flush Worker — DB 복구 후 순차 반영

```javascript
async function flushPendingWrites() {
    while (true) {
        const item = await redis.lpop(PENDING_QUEUE);
        if (!item) break;

        const { query, params } = JSON.parse(item);
        try {
            await db.query(query, params);
        } catch (err) {
            // DB 아직 복구 안 됨 → 다시 queue 앞에 넣기
            await redis.lpush(PENDING_QUEUE, item);
            console.warn(`[flush-worker] DB still unavailable, re-queued`);
            break;
        }
    }
}

// 5초 주기로 실행 (DB 복구 감지 겸용)
setInterval(flushPendingWrites, 5000);
```

#### 모니터링 — Pending 건수 확인

```javascript
async function getPendingCount() {
    return await redis.llen(PENDING_QUEUE);
}

// Health Check에 포함
app.get('/health', async (req, res) => {
    const pendingCount = await getPendingCount();
    res.json({
        status: pendingCount > 0 ? 'degraded' : 'healthy',
        pendingWrites: pendingCount
    });
});
```

### 특징

| 항목 | 내용 |
|------|------|
| **코드 변경량** | Write 경로 try-catch ~5줄, Flush worker ~15줄 |
| **인프라 변경** | 없음 (기존 Redis 그대로 사용) |
| **새 SDK** | 없음 |
| **읽기** | 기존 Cache-Aside 그대로 동작 |
| **데이터 보호** | AOF 활성화 시 디스크에 영속 저장 |

### AOF 활성화 (필수)

AOF를 활성화하면 모든 write 명령이 **디스크에 기록**되므로, Redis 프로세스 재시작이나 장애 발생 시에도 데이터가 복구됩니다.

- Azure Managed Redis에서 **Data Persistence** 설정으로 AOF 활성화 가능
- `appendfsync always` 설정 시 **매 명령마다 fsync** → 유실 0에 근접
- `appendfsync everysec` (기본값) 설정 시 최대 ~1초 유실 가능
- DB upgrade는 **계획된 작업**이므로 Redis가 동시에 장애날 확률은 극히 낮음

> AOF가 활성화된 Redis는 in-memory만 사용하는 것이 아니라 **디스크에 영속 저장**하므로, 계획된 DB Downtime 대응으로는 충분한 신뢰성을 갖습니다.

### 모니터링

- **`pending_writes` 길이**: `LLEN pending_writes` 기반 알림 설정
- pending 건수가 지속 증가하면 DB 복구 지연 또는 Flush Worker 이상 의심

---

## 방안 2: Azure Service Bus를 Write Buffer로 활용 (In-Memory 비의존)

Redis의 **in-memory 구조 자체를 신뢰할 수 없는 환경** (예: AOF 활성화가 불가하거나, Redis 인프라 자체의 안정성이 보장되지 않는 경우)에서는 **Azure Service Bus**를 write buffer로 사용합니다. Redis는 읽기 캐시 전용으로 유지합니다.

### 아키텍처

```
[DB Down 상태]
App → Write → Service Bus Queue (디스크 영속 저장) + Redis Cache 갱신
App → Read  → Redis (Hit) → 반환

[DB 복구 후]
Consumer Worker → Service Bus에서 메시지 수신 → DB 반영 → Complete (메시지 삭제)
                  실패 시 → 메시지 유지 (PeekLock) → 재시도 or Dead Letter Queue
```

### 왜 Service Bus인가

| 비교 항목 | Redis List | Azure Service Bus |
|-----------|-----------|-------------------|
| 저장 방식 | In-memory | **디스크 영속 저장** |
| 장애 시 데이터 | 유실 가능 | **유실 0** |
| 처리 보장 | At-most-once | **At-least-once (PeekLock)** |
| 실패 처리 | 수동 재삽입 | **Dead Letter Queue 자동 이동** |
| 순서 보장 | FIFO (단일 consumer) | **Session 기반 FIFO** |
| 메시지 TTL | 별도 관리 | **자동 만료 설정** |

### 구현

#### 의존성 설치

```bash
npm install @azure/service-bus
```

#### Service Bus Client 초기화

```javascript
const { ServiceBusClient } = require('@azure/service-bus');

const sbClient = new ServiceBusClient(process.env.SERVICEBUS_CONNECTION_STRING);
const sender = sbClient.createSender('pending-db-writes');
const receiver = sbClient.createReceiver('pending-db-writes', {
    receiveMode: 'peekLock'  // Complete 전까지 메시지 유지
});
```

#### Write 경로 — DB 실패 시 Service Bus에 전송

```javascript
async function saveRecentHistory(userId, data) {
    const payload = { userId, data, timestamp: Date.now() };

    try {
        await db.query(
            'INSERT INTO recent_history (user_id, data, created_at) VALUES (?, ?, NOW())',
            [userId, JSON.stringify(data)]
        );
    } catch (err) {
        // DB down → Service Bus에 메시지 전송 (디스크 영속 저장)
        await sender.sendMessages({
            body: {
                query: 'INSERT INTO recent_history (user_id, data, created_at) VALUES (?, ?, NOW())',
                params: [userId, JSON.stringify(data)],
                ...payload
            },
            sessionId: userId,  // 동일 사용자의 순서 보장
            contentType: 'application/json'
        });
        console.warn(`[write-behind] DB write failed, sent to Service Bus: ${err.message}`);
    }

    // 캐시는 DB 성공/실패 무관하게 갱신
    await redis.set(`history:${userId}`, JSON.stringify(data), 'EX', 3600);
}
```

#### Flush Consumer — DB 복구 후 순차 반영

```javascript
async function startFlushConsumer() {
    const processMessage = async (message) => {
        const { query, params } = message.body;
        try {
            await db.query(query, params);
            await receiver.completeMessage(message);  // 처리 완료 → 메시지 삭제
        } catch (err) {
            // DB 아직 복구 안 됨 → 메시지 유지 (lock 해제 후 재시도)
            await receiver.abandonMessage(message);
            console.warn(`[flush-consumer] DB still unavailable: ${err.message}`);
        }
    };

    const processError = async (args) => {
        console.error(`[flush-consumer] Error: ${args.error.message}`);
    };

    receiver.subscribe({
        processMessage,
        processError
    });
}

startFlushConsumer();
```

#### Dead Letter Queue 처리

최대 재시도 초과 시 자동으로 Dead Letter Queue(DLQ)에 이동합니다. 이후 수동 확인 및 재처리가 가능합니다.

```javascript
const dlqReceiver = sbClient.createReceiver('pending-db-writes', {
    subQueueType: 'deadLetter'
});

async function processDLQ() {
    const messages = await dlqReceiver.receiveMessages(10, { maxWaitTimeInMs: 5000 });
    for (const msg of messages) {
        console.error(`[DLQ] Failed message:`, msg.body);
        // 수동 검토 후 재처리 또는 로깅
        await dlqReceiver.completeMessage(msg);
    }
}
```

### 특징

| 항목 | 내용 |
|------|------|
| **데이터 유실** | 0 (디스크 영속 + PeekLock) |
| **순서 보장** | Session 기반 FIFO |
| **실패 처리** | 자동 재시도 + Dead Letter Queue |
| **인프라 추가** | Azure Service Bus 리소스 생성 필요 |
| **SDK 추가** | `@azure/service-bus` |

---

## 방안 3: Hazelcast 네이티브 Write-Behind (IMDG 도입)

Redis 대신 **Hazelcast**를 캐시 + Write-Behind 레이어로 도입하는 방안입니다. 앱은 Hazelcast에만 쓰고, Hazelcast가 DB 동기화를 자동으로 처리합니다.

Hazelcast는 **Apache 2.0 라이선스**의 오픈소스 In-Memory Data Grid(IMDG)이며, Community Edition에서 Write-Behind를 지원합니다.

### 아키텍처

```
[정상/DB Down 상태 공통]
App → Write → Hazelcast.put() → 캐시 즉시 반영
                                 └→ Write-Behind 큐 → batch flush → DB
                                    (DB down 시 큐에 쌓이고, 복구 후 자동 flush)

App → Read  → Hazelcast.get() → 캐시 Hit → 반환
                                 캐시 Miss → MapLoader가 DB에서 자동 로드
```

### 왜 Hazelcast인가

Redis에서 실패한 Write-Behind의 핵심 난제를 Hazelcast는 아키텍처 수준에서 해결합니다:

| 난제 | Redis (실패) | Hazelcast (해결) |
|------|------------|------------------|
| 코드 실행 안정성 | 프로세스 내 Python 실행 → 크래시 | JVM 위 관리 코드, 인터페이스 구현체로 격리 |
| 큐 내구성 | Gears 큐가 replication 대상 아님 → 유실 | 큐가 파티션 데이터의 일부로 자동 복제 |
| 쓰기 순서 | 샤드별 독립 → 순서 보장 불가 | 파티션별 순서 보장 |
| 중복 제거 | at-least-once만 | **Coalescing**: 같은 키 N번 → 1번 flush |
| 스레드 모델 | 싱글 스레드 → flush가 블로킹 | 멀티 스레드 → flush 전용 스레드풀 |

### 구현

#### MapStore 구현 (Java — DB 쓰기 로직만 정의)

```java
public class HistoryMapStore implements MapStore<String, String> {

    @Override
    public void store(String key, String value) {
        // 단건 DB 쓰기
        db.query("INSERT INTO recent_history (user_id, data) VALUES (?, ?)",
                 key, value);
    }

    @Override
    public void storeAll(Map<String, String> map) {
        // 배치 DB 쓰기
        db.batchInsert(map);
    }

    @Override
    public String load(String key) {
        // Read-Through: 캐시 미스 시 DB에서 자동 로드
        return db.query("SELECT data FROM recent_history WHERE user_id = ?", key);
    }

    @Override
    public void delete(String key) {
        db.query("DELETE FROM recent_history WHERE user_id = ?", key);
    }

    // storeAll, loadAll, deleteAll, loadAllKeys도 구현
}
```

#### Write-Behind 설정

```java
MapStoreConfig mapStoreConfig = new MapStoreConfig();
mapStoreConfig.setImplementation(new HistoryMapStore());
mapStoreConfig.setWriteDelaySeconds(5);      // 5초 후 batch flush
mapStoreConfig.setWriteBatchSize(100);       // 100개씩 묶어서 쓰기
mapStoreConfig.setWriteCoalescing(true);     // 같은 키 중복 제거

MapConfig mapConfig = new MapConfig("recent-history");
mapConfig.setMapStoreConfig(mapStoreConfig);
mapConfig.setBackupCount(1);                 // 1개 백업 (큐 포함 복제)

Config config = new Config();
config.addMapConfig(mapConfig);
HazelcastInstance hz = Hazelcast.newHazelcastInstance(config);
```

#### Node.js 앱에서 Hazelcast 클라이언트 사용

```javascript
const { Client } = require('hazelcast-client');

const hzClient = await Client.newHazelcastClient({
    clusterName: 'dev',
    network: { clusterMembers: ['hazelcast-service:5701'] }
});

const historyMap = await hzClient.getMap('recent-history');

// Write — Hazelcast에만 쓰면 끝. DB 동기화는 자동
async function saveRecentHistory(userId, data) {
    await historyMap.put(userId, JSON.stringify(data));
}

// Read — 캐시 Hit 또는 MapLoader가 DB에서 자동 로드
async function getRecentHistory(userId) {
    const cached = await historyMap.get(userId);
    return cached ? JSON.parse(cached) : null;
}
```

### 특징

| 항목 | 내용 |
|------|------|
| **Write-Behind** | 네이티브 내장 (큐잉, 배치, 재시도, Coalescing 자동) |
| **Read-Through** | MapLoader로 캐시 미스 시 DB 자동 조회 |
| **큐 내구성** | 파티션 복제본에 포함 — 노드 장애 시 백업이 인수 |
| **인프라 추가** | Hazelcast 클러스터 (AKS 또는 VM) 배포 필요 |
| **앱 코드 변경** | 캐시 레이어 교체 (Redis → Hazelcast Client) |
| **라이선스** | Apache 2.0 (Community Edition) |
| **운영 부담** | JVM 클러스터 관리 필요 |

### 배포 — AKS에 Hazelcast 클러스터 배포

```bash
helm repo add hazelcast https://hazelcast-charts.s3.amazonaws.com/
helm install hazelcast hazelcast/hazelcast \
  --set cluster.memberCount=3 \
  --set hazelcast.yaml.hazelcast.map.recent-history.map-store.enabled=true
```

---

## 방안 비교

| 기준 | 방안 1 (Redis + AOF) | 방안 2 (Service Bus) | 방안 3 (Hazelcast) |
|------|---------------------|---------------------|--------------------|
| 접근 방식 | 앱 레벨 Write-Behind | 앱 레벨 Write-Behind | **네이티브 Write-Behind** |
| 코드 변경량 | **최소** (~20줄) | 중간 (~50줄 + SDK) | 대규모 (캐시 레이어 교체) |
| 인프라 변경 | **없음** (AOF 설정만) | Service Bus 생성 | Hazelcast 클러스터 배포 |
| 데이터 보호 | AOF 디스크 영속 | 디스크 영속 (유실 0) | 파티션 복제 (유실 0) |
| 순서 보장 | 단일 consumer FIFO | Session 기반 FIFO | **파티션 기반 자동 보장** |
| 중복 제거 | 없음 | 없음 | **Coalescing 내장** |
| 실패 재처리 | 수동 재삽입 | DLQ 자동 분리 | **자동 재시도 + 백업 인수** |
| 비용 | 추가 비용 없음 | Service Bus 비용 | Hazelcast 클러스터 비용 |
| 운영 부담 | 낮음 | 낮음 | 높음 (JVM 클러스터) |
| 라이선스 | - | Azure 서비스 | Apache 2.0 (무료) |

### 선택 기준

- **코드 변경 최소화**, 기존 Redis 유지 → **방안 1 (Redis + AOF)**
- **데이터 유실 0 보장**, DLQ 기반 실패 관리 필요 → **방안 2 (Service Bus)**
- **네이티브 Write-Behind**, 큐 내구성/중복 제거/자동 재시도까지 프레임워크에 위임 → **방안 3 (Hazelcast)**

---

## 운영 체크리스트

### DB Upgrade 전

- [ ] Redis AOF 활성화 확인 (방안 1 사용 시)
- [ ] Hazelcast 클러스터 배포 및 MapStore 검증 (방안 3 사용 시)
- [ ] `pending_writes` / Service Bus Queue / Hazelcast 모니터링 대시보드 설정
- [ ] Flush Worker/Consumer 배포 확인 (방안 1, 2)
- [ ] 예상 Downtime × Write TPS로 필요 버퍼 용량 산정

### DB Upgrade 중

- [ ] `pending_writes` 길이 / Service Bus Active Message Count / Hazelcast Write-Behind 큐 크기 모니터링
- [ ] 읽기 서비스 정상 동작 확인 (Cache Hit Rate)
- [ ] Health Check endpoint에서 `degraded` 상태 확인

### DB 복구 후

- [ ] Flush Worker/Consumer가 pending write를 순차 반영 중인지 확인 (방안 1, 2)
- [ ] Hazelcast Write-Behind 큐가 자동 drain 중인지 확인 (방안 3)
- [ ] pending 건수가 0으로 감소하는지 모니터링
- [ ] DLQ 메시지 존재 여부 확인 (방안 2)
- [ ] 정합성 검증: DB 데이터와 캐시 데이터 일치 확인

---

## 참고 자료

- [Azure Architecture - Cache-Aside Pattern](https://learn.microsoft.com/azure/architecture/patterns/cache-aside)
- [Azure Architecture - Circuit Breaker Pattern](https://learn.microsoft.com/azure/architecture/patterns/circuit-breaker)
- [Azure Architecture - Queue-Based Load Leveling Pattern](https://learn.microsoft.com/azure/architecture/patterns/queue-based-load-leveling)
- [Azure Architecture - Caching Guidance](https://learn.microsoft.com/azure/architecture/best-practices/caching)
- [Azure Service Bus - Overview](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-messaging-overview)
- [Azure Service Bus - Dead Letter Queue](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-dead-letter-queues)
- [Azure Managed Redis - Data Persistence](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-how-to-premium-persistence)
- [RedisGears v1 - Deprecated](https://redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/deprecated-features/gears-v1/)
- [Redis Data Integration (RDI)](https://redis.io/docs/latest/integrate/redis-data-integration/)
- [RDI - When to use](https://redis.io/docs/latest/integrate/redis-data-integration/when-to-use/)
- [Hazelcast - MapStore / Write-Behind](https://docs.hazelcast.com/hazelcast/latest/data-structures/working-with-external-data)
- [Hazelcast Helm Chart](https://github.com/hazelcast/charts)

---

## 부록 A: 네이티브 Write-Behind 솔루션 현황

### 네이티브 Write-Behind란?

앱이 캐시에만 쓰면, 캐시 미들웨어가 자동으로 DB에 비동기 동기화하는 패턴입니다. 큐잉, 배치, 재시도, 코드 격리가 프레임워크에 내장되어 있습니다.

### Redis 에코시스템

| 기능 | 상태 | Write-Behind | 비고 |
|------|------|-------------|------|
| **RedisGears v1** (Python) | ❌ Deprecated | rgsync 라이브러리로 지원했음 | Redis Enterprise 전용 모듈 (RSAL/SSPL) |
| **Triggers and Functions** (JavaScript) | ❌ Deprecated | 지원 안 함 | "preview has ended, will not be promoted to GA" |
| **Redis Data Integration (RDI)** | ✅ GA | ❌ Ingest만 (DB→Redis) | CDC 기반, Debezium 사용. Write-Behind 방향 미지원 |

Redis는 Write-Behind를 공식적으로 **지원하지 않으며, 로드맵에도 없습니다**. RDI 문서에서 명시적으로 "When NOT to use RDI: The app must write data to the Redis cache, which then updates the source database (write-behind/write-through patterns)"라고 기술하고 있습니다.

### Azure 서비스

| Azure 서비스 | Write-Behind | 비고 |
|-------------|-------------|------|
| Azure Managed Redis | ❌ | RedisGears 모듈 미지원 (실증 완료: `Unsupported module type` 에러) |
| Azure Cache for Redis | ❌ | Redis OSS 기반, Gears 없음 |
| Cosmos DB Integrated Cache | ❌ | Read-Through만 지원 |
| Dapr (Container Apps) | ❌ | State Store에 Write-Behind 없음 |
| NCache (Marketplace) | ⚠️ 서드파티 | Write-Behind 지원하나 Enterprise 라이선스 필요, VM 자체 관리 |

**Azure 퍼스트파티 서비스 중 네이티브 Write-Behind를 제공하는 서비스는 없습니다.**

### Azure Managed Redis에서 RedisGears 사용 불가 실증

```bash
# RedisGears 모듈로 생성 시도
az redisenterprise create \
  --name test-redisgears \
  --resource-group rg-redisgears-test \
  --location koreacentral \
  --sku Balanced_B1

az redisenterprise database create \
  --cluster-name test-redisgears \
  --resource-group rg-redisgears-test \
  --modules name="RedisGears"
# 결과: (BadRequest) Unsupported module type

# 대조군: RedisBloom 모듈은 정상 수락
az redisenterprise database create \
  --cluster-name test-redisgears \
  --resource-group rg-redisgears-test \
  --modules name="RedisBloom"
# 결과: (Conflict) The cluster is not yet running — 모듈 자체는 수락됨
```

Azure Managed Redis가 지원하는 모듈은 **RediSearch, RedisBloom, RedisTimeSeries, RedisJSON** 4개뿐입니다. Microsoft 문서에서도 "Currently, you can't manually load any modules into Azure Managed Redis"라고 명시하고 있습니다.

### IMDG(In-Memory Data Grid) 솔루션

Redis 외에 네이티브 Write-Behind를 지원하는 솔루션은 IMDG 계열입니다:

| 솔루션 | 라이선스 | Write-Behind 방식 | Node.js 지원 | Azure 관리형 |
|--------|---------|-------------------|-------------|-------------|
| **Hazelcast** | Apache 2.0 (CE) | MapStore 인터페이스, write-behind 내장 | ⚠️ 제한적 | ❌ 자체 호스팅 |
| **Apache Ignite** | Apache 2.0 | CacheStoreAdapter, writeBehindEnabled | ⚠️ 제한적 | ❌ 자체 호스팅 |
| **NCache** | 상용 (Enterprise) | WriteThruProviderBase | ⚠️ Enterprise만 | ⚠️ Marketplace |
| **Oracle Coherence** | 상용 | CacheStore 인터페이스 | ❌ | ❌ |

### IMDG가 Write-Behind를 안정적으로 제공할 수 있는 이유

Redis와 달리 IMDG는 처음부터 **"코드와 데이터를 함께 관리하는 플랫폼"**으로 설계되어, Write-Behind의 핵심 난제를 아키텍처 수준에서 해결합니다:

| 난제 | Redis (실패한 접근) | IMDG (해결 방식) |
|------|-------------------|-----------------|
| **코드 실행 안정성** | Redis 프로세스 안에 Python 인터프리터 내장 → 사용자 코드 버그가 전체 노드 크래시 유발 | JVM/.NET CLR 위에서 관리. 사용자 코드는 제한된 인터페이스 구현체 (MapStore 등)로 격리 |
| **큐 내구성** | Gears 내부 큐가 Redis replication과 별개 → 노드 장애 시 미처리 데이터 유실 | Write-Behind 큐가 파티션 데이터의 일부로 자동 복제. 프라이머리 장애 시 백업 노드가 큐 포함 인수 |
| **쓰기 순서** | 샤드별 독립 실행, 교차 순서 보장 불가 | 파티션별 순서 보장 (같은 키 → 같은 파티션 → 같은 큐) |
| **중복 제거** | at-least-once만, 중복 발생 | Coalescing 내장: 같은 키를 N번 갱신해도 마지막 값 1번만 DB에 flush |
| **스레드 모델** | 싱글 스레드 이벤트 루프 → Write-Behind 처리가 메인 루프 블로킹 | 멀티 스레드 → flush 전용 스레드풀에서 독립 처리 |

Hazelcast Write-Behind 사용 예시 (Java):

```java
// 사용자가 구현하는 건 DB 쓰기 로직만
public class OrderMapStore implements MapStore<String, Order> {
    public void store(String key, Order value) {
        db.insert(value);
    }
    public void storeAll(Map<String, Order> map) {
        db.batchInsert(map.values());
    }
}

// 설정만으로 Write-Behind 활성화
MapStoreConfig config = new MapStoreConfig();
config.setImplementation(new OrderMapStore());
config.setWriteDelaySeconds(5);      // 5초 후 batch flush
config.setWriteBatchSize(100);       // 100개씩 묶어서 쓰기
config.setWriteCoalescing(true);     // 같은 키 중복 제거
```

### IMDG 도입 시 고려사항

IMDG의 Write-Behind는 원래 **평상시 DB 쓰기 레이턴시 최적화**를 위해 설계되었습니다. DB 다운타임 시에도 큐에 쌓아두고 복구 후 자동 flush하므로 대응이 가능하지만, 도입 비용과 운영 부담을 함께 고려해야 합니다.

| 고려 항목 | 내용 |
|----------|------|
| 인프라 | JVM 기반 클러스터 배포/운영 (AKS 또는 VM) |
| 코드 변경 | 캐시 레이어 교체 (Redis Client → Hazelcast Client) |
| MapStore 구현 | Java로 DB 쓰기 로직 구현 필요 |
| 평상시 이점 | DB 쓰기 레이턴시 감소, Read-Through 자동 캐싱, Coalescing으로 DB 부하 감소 |
| 적합한 경우 | DB 다운타임 대응 + 평상시 쓰기 성능 개선이 함께 필요한 경우 |

---

## 부록 B: Redis가 Write-Behind를 포기한 이유

### 연대기

| 시기 | 기능 | 상태 | 비고 |
|------|------|------|------|
| ~2019 | RedisGears v1 (Python) | ❌ Deprecated | rgsync으로 Write-Behind 지원 |
| 2023 | Triggers and Functions (JavaScript) | ❌ Deprecated | GA 없이 종료. "feature preview has ended and it will not be promoted to GA" |
| 2024~ | Redis Data Integration (RDI) | ✅ GA | DB→Redis 단방향(Ingest)만 지원. Write-Behind 방향 없음 |

### 포기 이유

**1. 프로세스 내 코드 실행의 안정성 문제**

RedisGears v1은 Redis C 프로세스 안에 Python 인터프리터를 임베드하여 사용자 코드를 실행했습니다. 사용자 코드의 버그가 Redis 프로세스 전체를 크래시시킬 수 있었고, 실제로 GitHub에 다수의 크래시 리포트가 보고되었습니다. 이는 관리형 서비스(Redis Cloud, Azure Managed Redis)에서는 치명적인 문제입니다.

**2. 싱글 스레드 아키텍처의 한계**

Redis는 싱글 스레드 이벤트 루프 기반입니다. Write-Behind 큐 처리(DB flush)가 메인 이벤트 루프를 블로킹하면 모든 읽기/쓰기가 멈춥니다. IMDG(Hazelcast, Ignite)는 멀티 스레드 기반이라 flush를 별도 스레드풀에서 처리할 수 있지만, Redis는 구조적으로 불가능합니다.

**3. 큐 복제 불가**

Redis의 replication은 Redis 데이터(key-value)만 복제합니다. Gears 모듈 내부의 Write-Behind 큐는 replication 대상이 아니므로, 프라이머리 노드 장애 시 아직 flush되지 않은 쓰기 데이터가 유실됩니다. IMDG에서는 Write-Behind 큐가 파티션 데이터의 일부로 자동 복제되지만, Redis의 모듈 아키텍처에서는 이를 보장할 수 없습니다.

**4. 전략적 포지셔닝 전환**

Redis는 **"빠른 읽기 캐시"**로 포지셔닝을 확정했습니다. RDI의 공식 아키텍처 권장은:

```
앱 → DB에 쓴다 (DB = system of record)
DB → CDC(Debezium) → Redis에 자동 반영 (읽기 캐시)
앱 → Redis에서 읽는다
```

Write-Behind는 이 모델의 정반대입니다. Redis를 쓰기 경로에 넣으면 Redis가 "캐시"가 아니라 "중간 데이터베이스"가 되며, 이는 Redis가 원하는 제품 정체성이 아닙니다.

### 결론

Redis는 "캐시 안에서 코드를 실행"하는 접근 자체가 안정성과 복잡도 면에서 잘못된 방향이라 판단하고, "DB가 쓰기 주체, Redis는 읽기 캐시"라는 단순한 아키텍처(RDI/CDC)로 전략을 전환했습니다. 따라서 Redis 환경에서 네이티브 Write-Behind는 사용할 수 없으며, **앱 레벨 구현(방안 1, 2)** 또는 **Hazelcast 같은 IMDG 도입(방안 3)**으로 대응해야 합니다.
