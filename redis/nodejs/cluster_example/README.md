# Redis Cluster Example - Azure Managed Redis

Azure Managed Redis에서 **OSS Cluster(createCluster)** vs **Enterprise Cluster(createClient)** 연결 방식에 따른 Failover 동작 차이를 검증하기 위한 예제입니다.

관련 분석 문서: [`../cluster_failover_recovery.md`](../cluster_failover_recovery.md)

## 배경

Azure Managed Redis를 OSS Cluster 정책으로 운영 중, Planned Maintenance(Failover) 이후 클라이언트가 연결을 복구하지 못하는 장애가 발생했습니다. 이 예제를 통해 두 가지 연결 방식의 Failover 동작 차이를 실험할 수 있습니다.

## 구조

| 파일 | 설명 |
|------|------|
| `server.js` | Express 서버 진입점 |
| `redisClient.js` | Redis 클라이언트 생성 (OSS Cluster / Enterprise / Standalone 전환 가능) |
| `routes.js` | REST API 핸들러 (클러스터 정보, Failover 복구 테스트 등) |
| `healthCheck.js` | 주기적 Health Check Probe |

## 환경 변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `PROFILE` | 환경 프로필 (`DEVE`, `STAG`, `PROD` → Azure 인증) | 없음 (로컬 모드) |
| `REDIS_URL` | Redis 접속 URL | `rediss://redis-oss-policy.koreacentral.redis.azure.net:10000` |
| `REDIS_ACCESS_KEY` | Redis 접속 키 (Azure 모드 필수) | 없음 |
| `REDIS_MODE` | **연결 방식 선택**: `oss-cluster` / `enterprise` | Azure: `oss-cluster`, 로컬: `standalone` |
| `USE_CLUSTER` | 로컬에서 클러스터 모드 사용 (`true`/`false`) | `false` |
| `PORT` | 서버 포트 | `3000` |
| `HEALTH_CHECK_INTERVAL` | Health Check 주기 (ms) | `30000` |

## 실행

```bash
# 의존성 설치
npm install

# 로컬 Redis (standalone)
node server.js

# Azure - OSS Cluster 모드 (기존 문제 재현)
PROFILE=DEVE REDIS_MODE=oss-cluster node server.js

# Azure - Enterprise 모드 (권장 방안 검증)
PROFILE=DEVE REDIS_MODE=enterprise node server.js
```

## REST API

### 기본 API

| Endpoint | 설명 |
|----------|------|
| `GET /redis/status` | Redis 연결 상태 확인 (PING + latency) |
| `GET /redis/cluster-info` | 클러스터 정보 (CLUSTER INFO, NODES 등) |
| `GET /redis/cluster-slots` | 클러스터 슬롯 매핑 정보 |
| `GET /redis/test-keys?count=5&prefix=test` | Key 라우팅 테스트 (슬롯 분배 확인) |
| `GET /redis/client-list` | 연결된 CLIENT LIST |
| `GET /redis/health` | 수동 Health Check 실행 |

### Failover 검증 API

| Endpoint | 설명 |
|----------|------|
| `GET /redis/connection-mode` | 현재 연결 방식 정보 및 Failover 위험도 확인 |
| `GET /redis/monitor?duration=10&interval=1` | 토폴로지 변경 실시간 모니터링 |
| `GET /redis/failover-recovery?duration=30&interval=2` | **Failover 복구 테스트** - write/read를 반복하며 연결 복구 여부 관찰 |

## Failover 테스트 시나리오

### 1. OSS Cluster 모드에서 장애 재현

> ⚠️ `CLUSTER FAILOVER` 명령은 동일 노드 간 master/slave 역할만 교체하므로 실제 Planned Maintenance(노드 교체 → endpoint 무효화) 시나리오를 재현할 수 없습니다.
> 실제 재현을 위해서는 Azure의 **Planned Maintenance가 발생하는 시점**에 테스트하거나, Azure Support를 통해 maintenance를 요청해야 합니다. Azure Managed Redis는 수동 Reboot/Failover 트리거 기능을 제공하지 않습니다.

```bash
# 1) OSS Cluster 모드로 서버 시작
PROFILE=DEVE REDIS_MODE=oss-cluster node server.js

# 2) Failover 복구 테스트 시작 (충분한 시간 확보, 예: 300초)
curl "http://localhost:3000/redis/failover-recovery?duration=300&interval=2"

# 3) Azure Managed Redis는 수동 Reboot/Failover 기능을 제공하지 않음
#    실제 Planned Maintenance가 발생할 때까지 대기하거나,
#    Azure Support를 통해 maintenance를 요청해야 함
#    (실제 node가 교체되며 기존 shard endpoint가 무효화됨)

# 4) write/read 실패 → topology cache stale → 복구 불가 관찰
```

### 2. Enterprise 모드에서 안정성 확인

```bash
# 1) Enterprise 모드로 서버 시작
PROFILE=DEVE REDIS_MODE=enterprise node server.js

# 2) 동일한 Failover 복구 테스트 실행
curl "http://localhost:3000/redis/failover-recovery?duration=300&interval=2"

# 3) 동일하게 Planned Maintenance 발생 시 관찰

# 4) proxy가 자동으로 새 node로 라우팅 → 일시 끊김 후 빠른 복구 관찰
```

### 3. 연결 방식 비교

```bash
# 현재 연결 모드 및 Failover 위험도 확인
curl "http://localhost:3000/redis/connection-mode"
```
