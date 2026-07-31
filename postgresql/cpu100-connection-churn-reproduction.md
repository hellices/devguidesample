# PostgreSQL CPU 100% 재현 및 원인 분석

- Date: 2026-07-31 | Region: koreacentral | Target: Azure Database for PostgreSQL Flexible Server (D4ds_v5)
- Scope: 운영 관측(CPU 100%, 세션 ~5,000, write-only 로그)과 동일 조건 재현 및 원인 가설 검증. 특정 재현 환경 실측값이며 프로덕션 확정 진단 아님.

## 배경

- 운영 서비스는 세션정보·로그를 PostgreSQL(Azure Flexible Server, **4 vCore/16GiB**)에 기록하는 write 중심 워크로드 (Python + psycopg 클라이언트, key-value/log/sorted-set 형태의 store 테이블 4종에 INSERT/UPSERT)
- 어느 시점 **DB CPU가 100%로 포화**되어 장애 발생 → **8 vCore로 증설하자 안정화**됐으나 원인은 미규명
- 이상한 점: 장애 당시 쿼리 로그에는 **INSERT/UPSERT만 평균 ~22 QPS** — CPU를 태울 만한 부하가 아님. 그런데 세션은 ~5,000개, 메모리는 50%대로 오히려 안정
- "적은 쿼리 + 많은 세션 + 안정적 메모리 + CPU 100%"의 조합이 어떻게 성립하는지 확인하기 위해, **동일 사양·스키마·데이터 규모의 재현 환경**에서 원인 후보를 하나씩 실측 검증한 기록

> **요약**
> - 재현 환경: 운영과 동일 스키마·데이터·사양 (D4ds, 4 vCore/16GiB)
> - 실측 결과: **커넥션 수립(backend fork + TLS 핸드셰이크) 비용 폭주(재시도 나선)**가 운영 관측 4종
>   (CPU 100% / 세션 ~5,000 / 메모리 50%대 안정 / 로그엔 INSERT ~20 QPS만)과 모두 일치하는 상태를 재현
> - 이를 최유력 가설로 두고, 원인 후보 전체를 검증 우선순위(§0)로 정리
> - 프로덕션 코드·연결 경로의 실제 확인 항목은 각 가설에 병기

---

## 0. 원인 후보 및 검증 우선순위

재현 실측 결과에 근거한 검증 우선순위:

| 순위 | 가설 | 근거 (재현 실험) | 운영에서 확인할 것 |
|:---:|------|----------------|------------------|
| **1** | **per-request connect + 재시도 나선** (psycopg 기본 사용, 요청/태스크마다 connect) | §3.1: 운영 규모 부하(200 tasks/s)로 CPU 99.2%, 세션 수천, 메모리 안정, INSERT 소량 성사 — 관측 4종과 모두 일치 | 코드에서 `psycopg2.connect(`가 핸들러/태스크/루프 안에 있는지. 재시도 로직에 backoff가 없는지 |
| **2** | **Pool thrashing** (풀은 있으나 minIdle 낮음/idleTimeout 짧음 + 버스트) | §3.3: 풀 존재 상태에서 CPU 96%, backend_start<10s 비율 96% | 풀 설정(minIdle, idleTimeout). `pg_stat_activity`에서 young 백엔드 비율 |
| **3** | **앱이 PgBouncer(6432)가 아닌 5432로 직결** | §3.5: 같은 폭풍이 5432=99.7% vs 6432=18.6% — 6432였다면 CPU 양상이 달랐을 것 | 앱 연결 문자열의 포트. `pg_stat_activity`의 client_addr |
| 4 | autovacuum/bloat 증폭 | §4: 가동 시 +25~30%p, 단독으론 100% 미도달 | offsets 테이블 bloat 비율, autovacuum 로그 |
| 5 | 핫로우 동시 경합 (offsets ON CONFLICT) | §4: 수백 active 시 CPU 96% — 나선 정착 후의 2차 양상일 가능성 | 장애 시점 active 세션 수와 wait_event |
| 6 | 논리복제/CDC (미검증) | 쿼리 로그의 `seq_counter`가 CDC 흔적일 가능성. 물리 replica는 무해 확인(§4) | `pg_replication_slots WHERE slot_type='logical'` |

기각된 가설은 §6 참고.

---

## 1. 운영 장애 관측

| # | 관측 | 값 |
|---|------|-----|
| O1 | CPU | 4 vCore에서 100% → 8 vCore 증설로 안정화 |
| O2 | PostgreSQL 세션 수 | ~5,000개 |
| O3 | 메모리 | 50%대로 안정 |
| O4 | 쿼리 로그 | **INSERT/UPSERT만** 존재 (SELECT 없음), 평균 ~22 QPS, 버스트 80~150 ops/s |
| O5 | 클라이언트 | **Python + psycopg** |
| O6 | 기타 | read replica 존재, PgBouncer 활성화 상태였음 |

## 2. 재현 환경

| 항목 | 값 |
|------|-----|
| 서버 | Azure Database for PostgreSQL Flexible Server (Korea Central) |
| SKU | **Standard_D4ds_v5 (4 vCore / 16 GiB)** — 운영 장애 당시와 동일 |
| 버전 | PostgreSQL 16.14 |
| 스토리지 | 256 GiB |
| PgBouncer | 내장, port 6432, transaction mode, `default_pool_size=50` |
| 스키마 | 운영 스키마 DDL(`schema.sql`) — store 4테이블, 월별 파티션 38개, 인덱스 198개 |
| 데이터 | **48M+ rows / ~74 GB** (운영 파티션별 통계 목표치 충족, bytea 1.2~1.8KB 페이로드로 TOAST 비중 재현) |
| 부하 도구 | Python 3.9 + psycopg2 (운영과 동일 스택), macOS 클라이언트에서 직접 실행 |

---

## 3. CPU 100% 재현 시나리오

> ※ 재현 환경에서의 결과. 운영 관측과의 일치 = 정황 근거. 프로덕션 실제 경로 여부는 §0 확인 항목으로 검증.

### 3.1 재시도 나선(retry spiral) — 20 QPS 수준 부하, CPU 99.2%

운영의 "부하는 겨우 20 QPS였는데 왜?"라는 의문에 대한 유력한 설명 후보. **재현 실험 중 작은 부하로 CPU 100%에 도달한 유일한 시나리오.**

**조건**
- 제공 부하: 태스크 200개/s (운영 버스트 150 ops/s와 같은 자릿수), 태스크당 INSERT 1건
- 클라이언트 동작: per-request `psycopg2.connect(connect_timeout=5)` → INSERT → `close()`, 연결 실패 시 즉시 2회 재시도 (지극히 평범한 앱 코드)
- 프로세스 5개 × 40 tasks/s, 프로세스당 in-flight 상한 1,500

**결과**

| 지표 | 값 | 운영 관측 대응 |
|------|-----|--------------|
| 서버 CPU | **99.2%** | O1 ✅ |
| 클라이언트 대기 커넥션 | **7,500개 포화** | O2 ✅ (세션 = 대기 행렬) |
| 메모리 | 39% 안정 | O3 ✅ (단명 세션은 누적 안 됨) |
| **성사된 INSERT** | **~2/s** (재시도 92,000회+, 포기 28,000+) | O4 ✅ (로그엔 성사분만 기록) |

**메커니즘 (수식)**: `동시 커넥션 = 시도율 × 연결 소요시간`
- 정상: 200/s × 0.1s = 20개
- 나선: 연결 지연 5s+ → 타임아웃 → 재시도로 시도율 3배 증폭 → 600/s × 8s = **수천 개**

**8 vCore 증설 즉효와의 정합성**: fork/TLS 처리 용량 2배 → 연결 지연 해소 → 나선의 고리(지연→재시도→지연) 차단 → 같은 20 QPS로 복귀. 운영의 "증설 즉시 안정화" 경과와 일치. 단, 이 경우 원인은 해소가 아니라 잠복.

### 3.2 커넥션 churn — 동시 커넥터 480, CPU 99.7%

**조건**: 동시 커넥터 480개(8프로세스×60스레드)가 `connect(TLS+fork) → INSERT 1건 → close` 반복. 직접 5432.

**결과**: CPU **99.4~99.7% 지속**(4분+), 메모리 40%대 안정, 연결 성사 ~125/s뿐, 연결 소요 평균 **3.4초**(정상 ~0.1초).
재현 환경에서 쿼리가 아니라 **연결 수립 비용만으로 4코어가 포화됨**을 처음 확인한 실험.

### 3.3 Pool thrashing — 풀 구성 상태에서 CPU 96%

"커넥션 풀이 있는데도 발생할 수 있는가?"에 대한 검증.

**조건**: HikariCP류 흔한 설정 시뮬레이션 — `minimumIdle=0`, 짧은 `idleTimeout` + 운영 트래픽의 버스트 패턴(4초 burst/12초 주기). 앱 인스턴스 60개 × pool max 20.

**결과**: CPU **94~97.7%** (10분+), 메모리 46% 안정, 연결 개폐 ~95/s(opened=evicted 대칭), 백엔드 341~398개 중 **96%가 backend_start 10초 미만**.
버스트마다 풀이 0→20 새 연결, 조용해지면 전부 반납 → 풀이 스스로 churn을 만든다.

**운영 진단 쿼리** (1분 확인):
```sql
SELECT count(*) AS total,
       count(*) FILTER (WHERE now()-backend_start < interval '10 s') AS young
FROM pg_stat_activity;
-- young/total 비율이 높으면 churn/thrashing 가능성이 높음
```

### 3.4 psycopg 연결 패턴 비교 — per-request vs 재사용

**조건**: 동일 워커 30개, 동일 UPSERT, 각 90초. (a) per-request connect vs (b) 연결 재사용.

| 패턴 | 처리량 | 서버 CPU | op당 CPU 비용 |
|------|-------:|---------:|:---:|
| `psycopg2.connect()` per-request | 101 ops/s | **93~96%** | **~7배** |
| 연결 재사용 (풀 동등) | 542 ops/s | 69~75% | 1x |

psycopg는 **기본 풀이 없다** — Python 앱에서 흔한 per-request connect 패턴이 §3.2의 churn과 동일한 부하를 만든다.

### 3.5 PgBouncer 경유 비교 — 5432 vs 6432

**조건**: 3.2와 완전히 동일한 480 커넥터 churn을 6432(내장 PgBouncer)로.

| 지표 | 직접 5432 | PgBouncer 6432 |
|------|----------|----------------|
| 서버 CPU | **99.7%** | **10~18.6%** |
| PG 백엔드 | 수백 (계속 fork) | **112개 고정** (재사용) |
| 연결 소요 | 3.4s | 1.4~1.9s |

**시사점**
- 재현 환경 기준, 6432 경유 시 같은 churn에서 CPU 100% 미도달 → 운영 앱의 5432 직결 가능성 시사 (실제 경로는 §0 순위 3으로 확인)
- 6432도 연결 지연(싱글스레드 PgBouncer의 TLS 병목)은 잔존 → 근본 대책은 앱 풀

### 3.6 인과 사슬

```
[평시] Python 앱(psycopg, per-request connect 또는 thrashing 풀) + ~22 QPS
[트리거] 순간 버스트/일시 지연으로 연결 소요시간 상승
[나선] 연결 지연 → connect_timeout → 재시도 → 시도율 증폭 → 지연 악화 → …
[정착] CPU 100% (fork+TLS 소진), 세션 수천(대기 행렬), INSERT는 ~20/s만 성사
[관측] 로그: INSERT만 소량 | 세션: ~5,000 | 메모리: 안정 | CPU: 100%
[해소] 8 vCore: 연결 처리 용량 2배 → 나선 붕괴 → 정상 복귀 (원인 존치)
```

---

## 4. 보조 발견

| 발견 | 실측 | 의미 |
|------|------|------|
| autovacuum 비용 | 가동 순간 동일 부하에서 CPU +25~30%p (시딩 직후 단독 96%) | 나선 발생 시 증폭기. offsets 테이블은 운영에서 2배 bloat 상태 |
| 동시 active 세션 경합 | 직접접속 355 active → CPU 96%, 처리량 1/3 붕괴 | 나선 정착 후의 2차 양상 (핫로우 `store_stream_offsets` ON CONFLICT 경합) |
| 세션 폭주 → 관리 불능 | 메모리 고갈 시 Azure 컨트롤플레인 API 전체 실패, stop/start만 복구 가능 (다운타임 ~40분) | 운영 재발 시 **장애 대응 조작이 안 되는 이중 장애** 위험 |
| 16GB의 세션 한계 | 오래 사는 백엔드는 ~2,000개에서 OOM (SSL 유무 무관) | "세션 5,000"은 오래 사는 백엔드가 아니라 단명 세션의 스냅샷일 가능성을 뒷받침 |

## 5. 권장 대책

| # | 조치 | 근거 |
|---|------|------|
| 1 | **앱에 커넥션 풀 도입** — psycopg2 `ThreadedConnectionPool` / psycopg3 `psycopg_pool`. 풀 사용 시 `minIdle=maxSize`로 고정해 thrashing 방지 | §3.4: 같은 하드웨어에서 5.4배 처리량, CPU는 더 낮음 |
| 2 | **연결 문자열 포트 5432 → 6432** (내장 PgBouncer) | §3.5: 같은 폭풍이 99.7% → 18.6% |
| 3 | **재시도에 exponential backoff + jitter** — 즉시 재시도가 나선의 증폭 계수 | §3.1: 즉시 재시도가 시도율 3배 증폭 |
| 4 | `log_connections=on` + 연결 rate/소요시간 알람 | 나선은 초기에 끊으면 수 초에 풀림 |
| 5 | offsets 핫로우 배치 flush + autovacuum 튜닝(fillfactor) | §4: 증폭 요인 제거 |
| 6 | in-memory/Redis/PG 3중 기록 제거 (아키텍처) | write 볼륨 자체 감축 |

### PgBouncer 사용 시 주의
transaction mode에서는 세션 상태 의존 기능(SET, prepared statements, advisory lock)이 트랜잭션 스코프로 제한됨. 이 워크로드(단발 INSERT/UPSERT)는 해당 없음.

---

## 6. 기각된 가설

원조건과 다른 조건에서만 성립했거나, 운영 증거에 의해 기각된 시나리오. 탐색 과정의 기록으로 남긴다.

<details>
<summary><b>기각 1) 기록된 쿼리 믹스 단독 부하</b></summary>

**조건**: 운영 1시간 쿼리 로그의 쿼리 믹스(INSERT/UPSERT/DELETE 8종)를 PgBouncer 경유로 1배~175배(3,900 QPS)까지 증폭. 풀 방식(연결 재사용) 클라이언트.

**결과**: 175배에서도 CPU **최대 49%**. 깨끗한 동일 스키마·동일 수량 DB에서 기록된 쿼리는 아무리 부어도 4 vCore를 포화시키지 못함.

**교훈**: 관건은 "무슨 쿼리를 얼마나"가 아니라 "어떻게 연결해서".
</details>

<details>
<summary><b>기각 2) 미기록 SELECT 트래픽 (운영 로그에 SELECT 부재로 기각)</b></summary>

**조건**: 세션 저장소형 read 믹스(kv point GET + sorted_set range + log tail + 30% write)를 ~810 QPS로 실행.

**결과**: CPU 22%. 이후 scope prefix 스캔(`LIKE 'ns:x%'`, 파티션 프루닝 불가)은 ~1,170 QPS에서 CPU 58~67%로 유력해 보였고, VACUUM과 겹치면 95.3%까지 도달했다.

**기각 사유**: 운영 측이 **장애 서버 로그에 SELECT가 전혀 없음**을 확인. prefix 스캔 시나리오는 조건 자체가 성립하지 않음. (단, `text_pattern_ops` 인덱스 4개가 스키마에 존재하므로 이 쿼리 패턴이 어딘가에 있다면 잠재 위험은 유효)
</details>

<details>
<summary><b>기각 3) 세션 누적에 의한 메모리 고갈 (운영 메모리 안정 관측과 불일치)</b></summary>

**조건**: (a) 스레드 기반 5,000 세션 시도, (b) psycopg2 ThreadedConnectionPool 50인스턴스×100.

**결과**: (a) ~1,900개에서 memory 39→89%, OOM으로 **서버 실제 다운** (restart API도 실패, stop/start로 40분 복구). (b) 2,716개에서 고착(mem 80%), +write 시 CPU 70.7% + 쿼리 OOM.

**정정 사유**: 운영은 **메모리가 50%대로 안정**이었다고 확인됨 → "RAM 잠식" 모델은 관측과 모순. 이 실험이 남긴 유효한 결론은 "16GB에 오래 사는 백엔드 5,000개는 물리적으로 불가"이며, 이것이 역으로 **세션 5,000 = 단명 세션 스냅샷** 가설(§3.1에서 재현 성립 확인)로 이어짐.
</details>

<details>
<summary><b>기각 4) idle 세션 대량 유지의 CPU 오버헤드</b></summary>

**조건**: 쿼리 없는 idle 홀더로 세션만 유지. D4ds(16GB)에서 ~2,000개(한계), E4ds(4c/32GB)로 올려 4,814개 + write 부하.

**결과**: idle 4,800개 유지 시 CPU **~11%**. +write 부하(~1,000 QPS)에도 max 40.7%. 4,800세션이 각자 1~5초 간격으로 write해도 14~40%.

**교훈**: idle 세션은 CPU 무해(스냅샷 오버헤드 미미). "세션이 많다" 자체가 아니라 "세션이 계속 만들어진다"가 문제.
</details>

<details>
<summary><b>기각 5) PostgreSQL 버전(13 vs 16) / SSL 강제 여부</b></summary>

**조건**: PG13.23 + `require_secure_transport=off` 서버를 별도 구축(D4ds), 동일 스키마/시드 후 비-SSL 세션 폭주.

**결과**: 비-SSL이어도 세션당 메모리 유사, ~2,970개에서 `could not fork: Cannot allocate memory`. CPU는 7%뿐이고 OOM 1,598건 — PG16과 유의미한 차이 없음.

**교훈**: 버전/SSL 설정은 무관. (단 TLS 핸드셰이크 자체는 churn 비용의 일부로 §3.2에서 유효)
</details>

<details>
<summary><b>기각 6) read replica의 primary 부하</b></summary>

**조건**: 운영에 replica가 있었으므로 D4ds primary에 replica 생성, 동일 write 믹스(~2,900 QPS)로 유무 비교.

**결과**: replica 없음 avg 26% / max 41% vs **replica 있음 avg 24% / max 34% — 차이 없음**. replica 자체는 8~15%로 WAL replay를 자기 부담.

**교훈**: 물리 복제(walsender)는 primary CPU에 무해. 단, **논리복제/CDC는 다름** — 쿼리 로그의 `seq_counter`가 CDC 흔적일 수 있으므로 운영에서 `SELECT * FROM pg_replication_slots WHERE slot_type='logical';` 확인 권장.
</details>

<details>
<summary><b>기각 7) bloat/autovacuum 단독 원인 (부분 기각 — 증폭 요인으로 재분류)</b></summary>

**조건**: 1시간 최대속도 UPSERT(18.3M ops, ~6,000 QPS)로 offsets/kv 핫로우에 dead tuple 누적(14k → 470k).

**결과**: autovacuum 가동 순간 동일 부하에서 CPU 35% → 62% (+25~30%p). 처리량 -19% 열화. 그러나 단독으로 100% 미도달.

**교훈**: bloat/autovacuum은 주원인이 아니라 **증폭기**. 운영 offsets가 2배 bloat였던 것은 상시 UPSERT의 결과이자 CPU 여유를 갉아먹는 배경 요인.
</details>

<details>
<summary><b>참고) PgBouncer 경유 churn/폭주 계열 — 서버는 보호되나 앱은 느려짐</b></summary>

- 6432 경유 connect/close 반복 250/s: CPU 22% (churn을 PgBouncer가 흡수)
- 6432 클라이언트 5,000개 유지 + write: 서버 backends 21~112개 고정, CPU ≤54%, mem 37~40%
- 6432 + 480 커넥터 폭풍(§3.5): CPU 18.6%지만 연결 소요 1.4~1.9s — 싱글스레드 PgBouncer의 TLS 병목

**교훈**: PgBouncer는 서버를 지키는 안전망이지 나선을 없애는 해법이 아님. 근본은 앱 풀.
</details>

---

## 부록 A. 실험 매트릭스

| 실험 | 조건 요약 | CPU | 판정 |
|------|----------|----:|------|
| run1~4 | 운영 쿼리 믹스 1x~175x, 풀 방식, 6432 | ≤49% | 기각 1 |
| bloat driver | 최대속도 UPSERT 1h, dead tuple 누적 | +25~30%p | 증폭기 |
| run7 | 직접 5432, 300 workers (풀 방식) | 96% | 경합 붕괴 (조건 변경) |
| E1 reads / E3 prefix | read 믹스 / prefix 스캔 | 22% / 58~67% | 기각 2 |
| prefix+VACUUM | 동시 실행 | 95.3% | 기각 2 (SELECT 없음) |
| 세션 5,000 (스레드/풀) | D4ds 16GB | OOM 다운 | 기각 3 |
| idle 4,800 (+write) | E4ds 32GB | 11~41% | 기각 4 |
| PG13 비-SSL | 세션 폭주 | 7% (OOM) | 기각 5 |
| **churn 480 (5432)** | **connect→INSERT→close 반복** | **99.7%** | **✅ 재현** |
| replica A/B | 동일 write 믹스 | 24% vs 26% | 기각 6 |
| **pool thrash** | **minIdle=0 + 버스트** | **96%** | **✅ 재현** |
| **psycopg A/B** | **per-request vs 재사용, 워커 30** | **96% vs 70%** | **✅ 재현** |
| **churn 480 (6432)** | 3.2와 동일, PgBouncer | 18.6% | 방어 실증 |
| **retry spiral** | **200 tasks/s + timeout/재시도** | **99.2%** | **✅ 최종 재현 (원조건)** |

## 부록 B. 재현 도구

- 부하 스크립트·스키마·사용법: [cpu100-connection-churn-reproduction/](./cpu100-connection-churn-reproduction/) (README 포함)
