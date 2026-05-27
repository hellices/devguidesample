# Azure MySQL 무중단 업그레이드: Blue/Green 전략 구현 (AKS + Node.js mysql2 PoolCluster)

## 개요

AWS RDS는 [Blue/Green Deployments](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/blue-green-deployments.html)를 통해 별도의 Green 환경을 자동 프로비저닝하고 DNS 전환으로 무중단 MySQL 버전 업그레이드를 지원합니다.  
Azure MySQL Flexible Server는 **MySQL binlog 복제(SQL 스레드 기반)** 를 활용하며, Custom Private DNS Zone의 CNAME 교체 + Session Kill 패턴을 결합하여 **무중단 버전 업그레이드**를 달성할 수 있습니다.

| | AWS RDS | Azure (이 문서) |
|---|---|---|
| Green 환경 | Blue/Green 자동 프로비저닝 | MySQL Flexible Server (VNet Integration) 수동 구성 |
| 데이터 동기화 | 자동 복제 | **MySQL binlog 복제** (`CHANGE REPLICATION SOURCE TO`, IO/SQL 스레드) |
| 트래픽 전환 | RDS Endpoint DNS 자동 전환 | Custom DNS Zone **CNAME 교체** (TTL=5s) |
| 기존 커넥션 처리 | 자동 drain | **Session Kill** → PoolCluster 자동 재연결 |
| 앱 재배포 | 불필요 | 불필요 (`DB_HOST` 불변) |
| Rollback | Switchback | CNAME 원복 + `super_read_only` 해제 |

이 문서는 해당 아키텍처의 **설계 제안**과 AKS + Node.js(mysql2 PoolCluster) 환경에서의 **실제 동작 검증** 결과를 담고 있습니다.

---

## 핵심 원리

### 커트오버 흐름

```
[old-db]  super_read_only = ON
    │
    └─> [new-db]  SHOW REPLICA STATUS: Seconds_Behind_Source = 0 대기
                    │
                    └─> STOP REPLICA; RESET REPLICA ALL  (standalone 스스로 실행, instant)
                             │
                             └─> CNAME 교체: primary → new-db FQDN (TTL=5s)
                                          │
                                          └─> old-db 세션 KILL
                                                    │
                                                    └─> PoolCluster 재연결
                                                              │
                                                              └─> new-db 연결 성공
```

**포인트:**
- `super_read_only = ON` 이후 new-db의 `Seconds_Behind_Source = 0` 이 되는 시점이 커트오버에 안전한 시점
- `STOP REPLICA` 전에 CNAME을 바꾸면 new-db가 아직 복제 중이었다가 old-db의 write를 받을 수 있음 — 순서 중요
- `STOP REPLICA; RESET REPLICA ALL` 은 SQL 명령 1개, **instant** (제관형 API 호출 보다 ~64s 단우)

### DNS 커넥션 재연결 동작

```
Session Kill 수신
  └─> mysql2 pool: 해당 커넥션 폐기
      └─> 다음 쿼리: 신규 커넥션 획득 시도
          └─> FQDN 재조회 (CNAME TTL=5s → new-db FQDN → VNet IP)
              └─> new-db 연결 성공
```

**mysql2 poolCluster의 재연결은 반드시 새 커넥션 생성을 통해서만 발생**합니다.  
이미 열린 커넥션은 DNS가 바뀌어도 기존 IP를 유지하므로, Session Kill이 필수 단계입니다.

### DNS 체인 구조

```
primary.db.{prefix}.internal   (앱 접속 FQDN — 코드/Secret 불변)
  ↓ CNAME TTL=5s  ← 컷오버 시 이 값만 변경
{prefix}-old-db.mysql.database.azure.com
  ↓ Azure DNS → Private DNS Zone mysql.database.azure.com
    A record: {prefix}-old-db → VNet Integration IP (10.2.0.x)
    (VNet Integration: 서버 NIC가 VNet 내 mysql-subnet에 직접 위치)
```

**장점:**
- 앱 코드/Secret에서 DB_HOST 불변 (`primary.db.{prefix}.internal`)
- VNet Integration으로 old-db과 new-db가 동일 VNet 안에 위치 → SQL binlog 복제 네트워크 접근 가능
- TLS: `rejectUnauthorized:true` 만 유지 — mysql2는 hostname 검증 미적용 (실증). custom FQDN 사용 시에도 접속 영향 없음. `servername` 불필요

---

## 코드 변경 사항 (2건)

프로덕션 코드(`urecaDbHandler.js`)에 실제로 추가한 변경입니다.

### 1. `makeConfig()` — 커넥션 안정성 옵션 추가

```diff
 const rtn = {
     ...props,
     ssl: sslConfig,
+    connectTimeout: 10000,        // 기본값 무한대 → 신규 DB 연결 hang 방지
+    enableKeepAlive: true,        // TCP keepalive로 idle 커넥션 조기 감지
+    keepAliveInitialDelay: 10000, // keepalive probe 시작 시간 (ms)
 };
```

### 2. `tsAbWrapper` — rollback 에러 분리

Session Kill 발생 시 `rollbackAsync()`도 동일 커넥션에서 실행되므로 2차 에러가 원래 에러를 덮어씁니다.  
DB는 세션 종료 시 서버 측에서 자동 rollback하므로 클라이언트 rollback 실패는 `warn` 로깅만 하고 무시합니다.

```diff
     } catch (err) {
-        await conn.rollbackAsync();
-        throw err;
+        try {
+            await conn.rollbackAsync();
+        } catch (rollbackErr) {
+            logger.w('tsAbWrapper.rollback', { code: rollbackErr.code, message: rollbackErr.message });
+        }
+        throw err;
     }
```

---

## 인프라/설정 변경 사항 (1건)

### `DB_HOST` — Custom Internal FQDN 사용

앱 Secret의 `DB_HOST`를 Azure MySQL FQDN 대신 **Custom Private DNS Zone의 CNAME** 으로 설정합니다.

```
DB_HOST=primary.db.{prefix}.internal     # 코드/Secret 불변
```

커트오버 후에도 `DB_HOST`는 변경하지 않습니다.

---

## 실증 확인 사항

코드 변경은 아니지만, 이 시나리오의 전제가 되는 동작을 시뮬레이션에서 실증 확인했습니다.

### `ssl.servername` 불필요 — Custom FQDN 접속 가능

원본 코드에 `servername` 설정은 **원래 없습니다**. 시뮬레이션에서 mysql2가 TLS hostname 검증을 수행하지 않음을 실증했습니다.

- `servername: 'wrong.example.com'`으로 설정해도 접속 성공 → **hostname 검증 미적용**
- `rejectUnauthorized: true`는 CA 체인 검증만 수행
- 따라서 `DB_HOST`를 Custom FQDN(`primary.db.{prefix}.internal`)으로 설정해도 TLS 접속에 영향 없음
- old/new DB 모두 동일 wildcard cert(`*.mysql.database.azure.com`) → 인증서 교체 불필요

### `removeNodeErrorCount` — 프로덕션 미설정 유지

원본 코드에 `removeNodeErrorCount`는 **원래 없습니다** (PoolCluster 기본값 사용). 시뮬레이션에서 이 설정의 위험성을 확인했습니다.

| 값 | 동작 | 시뮬레이션 결과 |
|----|------|--------|
| **1** | 에러 1회 시 노드 즉시 제거 | 50-pod 동시 connection storm에서 **노드 영구 사망**, 재기동 불가 |
| **5** (시뮬레이션 사용) | 5회 연속 에러 시 노드 제거 | 일시적 ECONNREFUSED 허용, storm 이후 정상 복구 |
| **미설정** (프로덕션 현행) | PoolCluster 기본 동작 | 일시 장애에도 노드 유지 — **그대로 유지 권장** |

---

## DNS Cutover 절차 (상세)

### Phase 0. 사전 확인

<details>
<summary>명령어 보기</summary>

```bash
# Pod DNS TTL 확인 (CoreDNS는 upstream TTL 그대로 전달)
kubectl exec -it <pod> -- cat /etc/resolv.conf

# 현재 FQDN CNAME 체인 확인
kubectl exec -it <pod> -- nslookup primary.db.<prefix>.internal
# → canonical name = <prefix>-old-db.mysql.database.azure.com
# → Address: <old-PE-IP>
```

</details>

### Phase 1. 사전 준비

<details>
<summary>명령어 보기</summary>

```bash
# 1. old-db write 차단
# 방법 A: super_read_only (자체 관리형 MySQL)
mysql -h <old-db> -e "SET GLOBAL super_read_only = ON;"

# 방법 B: REVOKE + ACCOUNT LOCK (Azure MySQL Flexible Server)
# ⚠ Azure MySQL은 SUPER 권한을 부여하지 않아 super_read_only 설정 불가
# 대안: 앱 유저의 write 권한을 제거하고 계정을 잠금
mysql -h <old-db> -e "
  REVOKE INSERT, UPDATE, DELETE ON simdb.* FROM 'appuser'@'%';
  ALTER USER 'appuser'@'%' ACCOUNT LOCK;
  FLUSH PRIVILEGES;"

# 2. new-db 복제 지연 = 0 확인 (SQL 스레드 기반)
mysql -h <new-db> -e "SHOW REPLICA STATUS\G"
# → Replica_IO_Running: Yes
# → Replica_SQL_Running: Yes
# → Seconds_Behind_Source: 0   ← 이 값이 0 이면 커트오버 안전
# (write 차단 이후 old-db 에 추가 write 없으므로 수초 내 0 수렴)

# 3. new-db → standalone 승격 (SQL 명령, instant)
mysql -h <new-db> -e "STOP REPLICA; RESET REPLICA ALL;"
# → 복제 IO/SQL 스레드 즉시 중단. new-db 는 read/write standalone 서버가 됨
# ⚠ CNAME 변경 전 실행 — 변경 후에는 already standalone
```

</details>

### Phase 2. DNS Cutover (CNAME 변경)

<details>
<summary>명령어 보기</summary>

```bash
# Custom DNS Zone CNAME: old-db FQDN → new-db FQDN
az network private-dns record-set cname set-record \
  --resource-group <rg> \
  --zone-name db.<prefix>.internal \
  --record-set-name primary \
  --cname <prefix>-new-db.mysql.database.azure.com

# Pod에서 DNS 전파 확인 (CNAME TTL=5s이므로 최대 5초 대기)
kubectl exec -it <pod> -- nslookup primary.db.<prefix>.internal
# → canonical name = <prefix>-new-db.mysql.database.azure.com  ← 변경 확인
```

</details>

### Phase 3. 기존 DB 세션 Kill

> **Azure MySQL Flexible Server**에서는 `KILL CONNECTION` 대신 내장 프로시저 `mysql.az_kill(id)` 를 사용합니다.
> 일반 `KILL` 문은 SUPER 권한이 필요하여 Azure 에서 실행 불가합니다.

<details>
<summary>SQL 보기</summary>

```sql
-- Azure MySQL: mysql.az_kill() 사용
-- 앱 세션 목록 조회 후 루프로 kill
SELECT id FROM information_schema.processlist WHERE user = '<app-user>';
-- → 각 id에 대해: CALL mysql.az_kill(<id>);

-- 자체 관리형 MySQL: KILL CONNECTION 사용
-- 기존 DB에서 실행
-- 1. 진행 중인 쿼리 확인 (완료 대기)
SELECT id, user, host, db, command, time, state, info
FROM information_schema.processlist
WHERE command != 'Sleep' AND user = '<app-user>';

-- 2. app 세션 일괄 kill (Sleep 포함)
SELECT CONCAT('KILL ', id, ';')
FROM information_schema.processlist
WHERE user = '<app-user>';
-- 출력된 KILL 문을 복사하여 실행

-- 또는 프로시저로 일괄 처리
DELIMITER $$
CREATE PROCEDURE kill_app_sessions()
BEGIN
  DECLARE done INT DEFAULT FALSE;
  DECLARE v_id BIGINT;
  DECLARE cur CURSOR FOR
    SELECT id FROM information_schema.processlist
    WHERE user = '<app-user>' AND command = 'Sleep';
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;
  OPEN cur;
  loop_label: LOOP
    FETCH cur INTO v_id;
    IF done THEN LEAVE loop_label; END IF;
    KILL CONNECTION v_id;
  END LOOP;
  CLOSE cur;
END$$
DELIMITER ;

CALL kill_app_sessions();
```

</details>

### Phase 4. 안정화 및 확인

<details>
<summary>명령어 보기</summary>

```bash
# 신규 DB에서 app 커넥션 수렴 확인
mysql -h <new-db> -e "SHOW PROCESSLIST;" | grep '<app-user>'

# 에러 로그 확인 (PROTOCOL_CONNECTION_LOST / ER_CONNECTION_KILLED 후 정상 재연결 여부)
kubectl logs -l app=<app-label> --since=2m | grep -E "reconnected|DOWNTIME|RECOVERED|CONNECTION_LOST"

# write 발생 여부 확인 (rollback 대비)
mysql -h <new-db> -e "
  SELECT COUNT(*) as active_writes
  FROM information_schema.innodb_trx
  WHERE trx_started > NOW() - INTERVAL 5 MINUTE;"
```

</details>

> **Phase 5 (재배포) 불필요** — `DB_HOST=primary.db.<prefix>.internal` 은 CNAME 교체 후에도 동일.

<details>
<summary>Rollback 절차 보기</summary>

> Rollback 가능 조건: new-db에 write가 발생하지 않은 시점(= super_read_only ON 오류로만 발생). new-db에 이미 데이터가 작성된 경우는 데이터 동기화 후 교체해야 하며, 데이터 팀 개입이 필요합니다.

```bash
# Custom DNS Zone CNAME 원복
az network private-dns record-set cname set-record \
  --resource-group <rg> \
  --zone-name db.<prefix>.internal \
  --record-set-name primary \
  --cname <prefix>-old-db.mysql.database.azure.com

# old-db super_read_only 해제
mysql -h <old-db> -e "SET GLOBAL super_read_only = OFF;"
```

| write 발생 여부 | Rollback 방법 |
|----------------|--------------|
| 없음 | CNAME 원복 + `SET GLOBAL super_read_only = OFF` → 안전 |
| 있음 | 신규 DB → 기존 DB 데이터 동기화 필요 → 위험, 데이터 팀 개입 필요 |

</details>

---

## 시뮬레이션 (`simulation/`)

<details>
<summary>시뮬레이션 구성, 설계 결정, 실행 순서 보기</summary>

### 목적

AKS Pod + MySQL Flexible Server × 2 환경에서 **Custom DNS Zone CNAME cutover 시 안정화 시간 및 시나리오 무결성** 검증.

### 구성

```
Custom Private DNS Zone: db.{prefix}.internal  (VNet linked)

앱 접속 FQDN: primary.db.{prefix}.internal  (DB_HOST, 코드/Secret 불변)
  ↓ CNAME TTL=5s  ← Cutover 시 이 값만 변경
{prefix}-old-db.mysql.database.azure.com
  ↓ Private DNS Zone mysql.database.azure.com (VNet Integration)
    A record: {prefix}-old-db → VNet IP (10.2.0.x)

Cutover:
  CNAME 변경: primary → {prefix}-new-db.mysql.database.azure.com
  기존 열린 커넥션: Session Kill → 재연결 시 CNAME 재조회 → new-db 로 수렴
```

> **검증 시나리오**: MySQL binlog 복제 (v8.0→v8.4) + `STOP REPLICA; RESET REPLICA ALL` 실시간 승격 + Custom DNS CNAME 커트오버 + Session Kill  
> 핵심 검증: 버전 업그레이드 포함 무중단 전환 — 인프라 타이밍 및 app 재연결 시간

### 주요 설계 결정

| 항목 | 내용 | 이유 |
|------|------|------|
| DNS Zone (앱 접속) | `db.{prefix}.internal` Custom Private DNS Zone | `DB_HOST` 불변, CNAME 교체만으로 컷오버 |
| DNS Zone (DB 해석) | `mysql.database.azure.com` | VNet Integration 자동 A record 등록 → VNet IP 해석 |
| DNS Zone Group | **미사용** (VNet Integration 방식) | VNet Integration으로 DNS 자동 관리 — PE/Zone Group 불필요 |
| CNAME TTL | **5s** | 커트오버 후 DNS 전파 최대 5초 이내 |
| DB SKU | GeneralPurpose 이상 권장 | 빠른 응답속도 필요 시 |
| 데이터 동기화 | **MySQL binlog 복제** (v8.0→v8.4) | `CHANGE REPLICATION SOURCE TO` + `START REPLICA`. IO/SQL 스레드 별도 실행 — `SHOW REPLICA STATUS` 으로 lag 실시간 모니터링 가능 |
| new-db 승격 | `STOP REPLICA; RESET REPLICA ALL` | SQL 명령 1개, **instant** (제관형 API ~64s 마이그레이션 없음) |
| TLS | `rejectUnauthorized: true` | CA 체인 검증만 수행. hostname 검증 미적용 (실증) — `servername` 불필요 |
| `removeNodeErrorCount` | 시뮬레이션: **1** / 프로덕션: **미적용** | 시뮬레이션에서 빠른 재연결 측정. 프로덕션은 일시 장애에도 노드 제거 리스크 |
| `server_name` 컬럼 | `@@hostname` INSERT | cutover 후 어느 DB 에 write 됐는지 확인 |

### 실행 순서

```powershell
# 터미널 A: 인프라 배포 (~15분, old-db만 생성)
.\scripts\01-deploy-infra.ps1 -ResourceGroup "rg-dbsim" -Password "YourP@ss1"

# 터미널 A: old-db 초기화 + K8s 배포
.\scripts\02-setup-db.ps1

# 터미널 A: new-db 생성(standalone v8.4, VNet Integration) + SQL binlog 복제 설정
.\scripts\02b-setup-replication.ps1

# 터미널 A: 이미지 빌드/푸시 + Deployment rollout
.\scripts\03-build-push.ps1

# 터미널 B: CRUD 로그 실시간 스트리밍 (cutover 전 켜두기)
.\scripts\04-watch-logs.ps1

# 터미널 A: Cutover 실행 (SHOW REPLICA STATUS lag=0 → STOP REPLICA → CNAME → session kill)
.\scripts\05-cutover.ps1
```

### 기대 로그 패턴 (04-watch-logs)

```
[06:07:01.000] ops=175/s  p50=8ms  p99=42ms  total=12450  err=0

[06:07:02.950] ⚠️  DOWNTIME START  op=opInsert  code=PROTOCOL_CONNECTION_LOST
[06:07:05.100] ✅ RECOVERED  reconnected to DB server: {new-hostname}
```

</details>

### 실험 결과

> 동일 환경에서 5회 반복 커트오버 측정 후 평균치를 기재합니다.

#### 환경

| 항목 | 값 |
|------|-----|
| Resource Group | `rg-dbsim-v3` (Korea Central) |
| AKS | **50 Pods** (`crud-worker`), 5 workers/pod, ~250 sessions |
| old-db sessions | **250** |
| old-db | MySQL 8.0.21, GeneralPurpose (VNet Integration) |
| new-db | MySQL 8.4.x-azure, Standalone (VNet Integration) |
| CNAME TTL | 5s |
| Write 차단 방식 | `REVOKE` + `ACCOUNT LOCK` |
| Session Kill | `mysql.az_kill(id)` |
| `removeNodeErrorCount` | 5 |

#### 개별 실행 결과 (5회)

| 항목 | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 |
|------|-------|-------|-------|-------|-------|
| 총 소요시간 | 37s | 32s | 28.2s | 31.1s | 30.0s |
| Write 차단 → Lag=0 | 10s | 5s | 1.2s | 5.5s | 1.8s |
| CNAME 전파 | <1s | <1s | 1.6s | 1.4s | 1.6s |
| Session Kill | 250/R1 | 250/R1 | 250/R1 | 250/R1 | 250/R1 |
| 앱 에러 | 3 | 4 | 4 | 3 | 5 |
| 전환 후 ops/s | ~37 | ~45 | 49 | 43 | 23 |

#### 측정 요약 (5회 평균)

| 측정값 | 결과 |
|--------|------|
| `STOP REPLICA; RESET REPLICA ALL` | instant (< 1s) |
| Write 차단 → `Lag=0s` 수렴 | **~5s** (1~10s 범위) |
| CNAME 전파 (Pod 내 CoreDNS) | **~1s** (TTL=5s, 캐시 상태에 따라 편차 가능) |
| Session Kill → new-db 수렴 | ~12s |
| **총 커트오버 소요시간** | **~32s** (28~37s 범위) |
| **앱 에러** | **~4건** (즉시 복구, 이후 증가 없음) |
| 전환 후 ops/s | ~39/s (전환 전과 동일 수준으로 복구) |
| write split (old-db에 INSERT) | 없음 |
| Phase 5 재배포 | 불필요 |

#### 설계 고찰: Session Kill vs. Graceful Drain

| 방식 | 장점 | 단점 |
|------|------|------|
| **Session Kill (현재 방식)** | 앱 코드 변경 없이 강제 재연결. `DB_HOST` 불변 | Kill 시점 진행 중 트랜잭션 롤백 |
| **앱 측 graceful drain** | 진행 중 트랜잭션 완료 후 재연결. 에러 0건 가능 | drain 로직 추가 필요. write 차단 후 대기 시간 증가 |
| **K8s Rolling Update** | 배포 프로세스와 통합 가능 | 재배포 필요. Pod 롤링 수십 초~수분 추가 |

Session Kill은 **앱 코드 변경 없이 수 ms 재연결을 달성하는 가장 단순한 방법**입니다.

#### 핵심 결론

1. **Session Kill 1라운드에 250개 전체 kill 성공** — `mysql.az_kill()` 활용, 50-pod 규모에서도 추가 라운드 불필요 (5회 전수 동일)
2. **앱 에러 평균 ~4건 (즉시 복구)** — `PROTOCOL_CONNECTION_LOST` → PoolCluster 자동 재연결, 이후 err 증가 없음
3. **Replication lag 수렴 평균 ~5s** — write 차단 후 잔여 binlog 소화 (1~10s 범위). 프로덕션 피크에서는 수십 초 가능
4. **CNAME 전파 평균 ~1s** — CoreDNS 캐시 잔여 TTL에 의존 (캐시 상태에 따라 편차 가능)
5. **총 커트오버 소요시간 평균 ~32s** — 28~37s 범위 (5회 측정)
6. **`STOP REPLICA; RESET REPLICA ALL` instant** — 관리형 API ~64s 없음
7. **앱 재배포 불필요** — `DB_HOST=primary.db.{prefix}.internal` 불변, CNAME만 교체
8. **VNet Integration** — old/new DB가 동일 VNet → SQL binlog 복제 직접 통신 (Private Endpoint 불필요)

---

### ⚠️ 프로덕션 적용 시 유의사항

시뮬레이션에서 발견한 실제 운영 환경 적용 시 주의점입니다.

#### 1. Azure MySQL Flexible Server 제약사항

Azure MySQL은 `SUPER` 권한을 부여하지 않습니다. 아래 명령은 직접 실행 불가하며, Azure 전용 대안을 사용해야 합니다.

| 일반 MySQL | Azure MySQL 대안 |
|---|---|
| `SET GLOBAL super_read_only = ON` | `REVOKE` + `ACCOUNT LOCK` |
| `KILL CONNECTION <id>` | `CALL mysql.az_kill(<id>)` |
| `CHANGE REPLICATION SOURCE TO ...` | `CALL mysql.az_replication_change_master(host, user, pass, port, file, pos, '')` |
| `START REPLICA` | `CALL mysql.az_replication_start` |
| `STOP REPLICA` | `CALL mysql.az_replication_stop` |

**Write 차단 (Phase 1) — Azure 방식:**

```sql
-- super_read_only 대신: 앱 유저의 write 권한 제거 + 계정 잠금
REVOKE INSERT, UPDATE, DELETE ON <db>.* FROM '<app-user>'@'%';
ALTER USER '<app-user>'@'%' ACCOUNT LOCK;
FLUSH PRIVILEGES;

-- 확인
SELECT account_locked FROM mysql.user WHERE user = '<app-user>';  -- Y
SHOW GRANTS FOR '<app-user>'@'%';  -- SELECT only
```

**Session Kill (Phase 3) — Azure 방식:**

```sql
-- 세션 목록 조회
SELECT id FROM information_schema.processlist WHERE user = '<app-user>';

-- 각 id에 대해 kill (루프 또는 스크립트)
CALL mysql.az_kill(<id>);

-- kill 후 확인: 0이어야 함
SELECT COUNT(*) FROM information_schema.processlist WHERE user = '<app-user>';
```

**Replication 설정 — Azure 방식:**

```sql
-- old-db의 binlog position 확보
SHOW MASTER STATUS;  -- File, Position 기록

-- new-db에서 replication 설정
CALL mysql.az_replication_change_master(
  '<old-db-fqdn>',    -- host
  '<repl-user>',       -- user
  '<repl-password>',   -- password
  3306,                -- port
  '<binlog-file>',     -- master_log_file
  <binlog-pos>,        -- master_log_pos
  ''                   -- ssl (빈 문자열 = 기본)
);
CALL mysql.az_replication_start;

-- 확인
SHOW REPLICA STATUS\G
-- Replica_IO_Running: Yes, Replica_SQL_Running: Yes, Seconds_Behind_Source: 0
```

#### 2. `require_secure_transport` 설정

복제 IO 스레드가 old-db에 연결할 때 SSL 없이 접근하므로, old-db에서 반드시 비활성화해야 합니다.

```bash
# 복제 전 old-db에서
az mysql flexible-server parameter set \
  --resource-group <rg> --server-name <old-db> \
  --name require_secure_transport --value OFF

# 복제 완료 + 커트오버 후 복원
az mysql flexible-server parameter set \
  --resource-group <rg> --server-name <old-db> \
  --name require_secure_transport --value ON
```

#### 3. mysqldump + `--master-data=2` 주의

`--master-data=2`는 내부적으로 `FLUSH TABLES WITH READ LOCK` (FTWRL)을 실행합니다.  
**활성 write 트래픽이 있는 상태에서 FTWRL은 모든 write를 블로킹**하며, 기존 트랜잭션이 완료될 때까지 대기합니다.

| 상황 | 결과 |
|------|------|
| write 없음 (maintenance window) | 정상 완료 |
| 활성 write 중 (250+ sessions) | **무한 대기** — long-running 트랜잭션이 FTWRL 획득 차단 |

**권장 방법:**

```bash
# 방법 1: 앱 트래픽 없는 시점에 dump
kubectl scale deployment <app> --replicas=0
mysqldump --single-transaction --master-data=2 --no-tablespaces <db> > dump.sql
kubectl scale deployment <app> --replicas=<N>

# 방법 2: binlog position 별도 확보 후 dump (write 중에도 가능)
mysql -e "SHOW MASTER STATUS;"   # → File, Position 기록
mysqldump --single-transaction --no-tablespaces <db> > dump.sql
# 기록해둔 File/Position으로 az_replication_change_master 호출
```

#### 4. MySQL 버전 업그레이드 쿼리 호환성

8.0 → 8.4 업그레이드 시 기존에 정상 동작하던 쿼리가 실패할 수 있습니다.

```sql
-- ❌ MySQL 8.4에서 ER_UPDATE_TABLE_USED
UPDATE orders SET qty = qty + 1
WHERE id = (SELECT id FROM orders ORDER BY id DESC LIMIT 1);

-- ✅ derived table로 래핑
UPDATE orders SET qty = qty + 1
WHERE id = (SELECT t.id FROM (SELECT id FROM orders ORDER BY id DESC LIMIT 1) t);
```

```sql
-- ❌ ORDER BY RAND() — full table scan + gap lock → INSERT 블로킹
SELECT id FROM orders ORDER BY RAND() LIMIT 1;

-- ✅ PK 범위 기반 랜덤 선택 (gap lock 최소화)
SELECT id FROM orders
WHERE id >= (SELECT FLOOR(MIN(id) + RAND() * (MAX(id) - MIN(id))) FROM orders)
LIMIT 1;
```

→ **사전에 new-db에서 전체 쿼리 regression test 수행 필수**

<details>
<summary>5. Rollback 절차</summary>

커트오버 후 문제 발생 시 아래 순서로 원복합니다.

```sql
-- 1. CNAME 원복
-- az network private-dns record-set cname set-record \
--   --resource-group <rg> --zone-name db.<prefix>.internal \
--   --record-set-name primary --cname <old-db-fqdn>

-- 2. appuser 복원 (old-db에서)
ALTER USER '<app-user>'@'%' ACCOUNT UNLOCK;
GRANT SELECT, INSERT, UPDATE, DELETE ON <db>.* TO '<app-user>'@'%';
FLUSH PRIVILEGES;

-- 3. Replication 정리 (new-db에서)
CALL mysql.az_replication_stop;
RESET REPLICA ALL;

-- 4. Pod 재시작 → old-db로 세션 수렴
-- kubectl rollout restart deployment <app>
```

| 확인 항목 | 기대값 |
|---|---|
| `nslookup primary.db.<prefix>.internal` | `<old-db-fqdn>` |
| `SELECT account_locked FROM mysql.user WHERE user='<app-user>'` | `N` |
| old-db `SHOW PROCESSLIST` | appuser 세션 수렴 |
| new-db `SHOW REPLICA STATUS` | 빈 결과 |

</details>

## 참고

- [mysql2 PoolCluster 문서](https://github.com/sidorares/node-mysql2#pool-cluster)
- [Azure Private DNS Zone TTL](https://learn.microsoft.com/azure/dns/private-dns-privatednszone)
- [MySQL super_read_only](https://dev.mysql.com/doc/refman/8.0/en/server-system-variables.html#sysvar_super_read_only)
- [Azure DNS Zone Groups](https://learn.microsoft.com/azure/private-link/private-endpoint-dns)
