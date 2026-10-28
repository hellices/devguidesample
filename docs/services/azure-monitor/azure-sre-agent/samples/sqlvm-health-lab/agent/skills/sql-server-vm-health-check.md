# SQL Server VM 상태 점검

이 스킬은 SQL Server VM(`@@VM_NAME@@`, 리소스 그룹 `@@RESOURCE_GROUP@@`)의
SQL Server를 점검할 때 사용한다. 에이전트는 Azure VNet 모드로 실습 VNet에
통합되어 있다.

- `SqlServerHealthCheck`: SQL Server 사설 IP `@@SQL_HOST@@:1433`에 TLS로 접속해
  고정된 읽기 전용 쿼리 결과를 JSON으로 돌려준다. 모니터링 로그인은 서버 상태와
  메타데이터를 읽을 수 있지만 테이블 데이터는 읽지 못한다.
- `SqlServerQuery`: 같은 경로와 로그인으로 에이전트가 작성한 읽기 전용 T-SQL을
  실행한다. 고정 operation으로 답할 수 없는 질문을 DMV·카탈로그 뷰·Query Store·
  `msdb` 이력으로 직접 확인할 때 쓴다. 배치는 항상 롤백되고 잠금 대기는 5초에서
  끊긴다. `database` 매개 변수로 DB 문맥을 지정한다(기본 `master`).
- `SqlServerMetricsQuery`: exporter가 30초(일부 5분)마다 수집해 Azure Monitor
  workspace에 저장한 지표를 PromQL로 조회한다. 추세와 증가량은 이 도구로 본다.
  모든 시계열은 `sql_vm="@@VM_NAME@@"` 레이블을 가진다.

## 질문별 operation

| 질문 | 호출 |
| --- | --- |
| 전반적인 상태 | `summary` → 이상 항목만 `cpu`, `waits`, `memory`, `databases`, `backups`, `io`, `missing_indexes` |
| 쿼리가 멈춤, 잠금, 차단 | `locks` (세션별로 보유한 테이블 잠금, 대기 중인 잠금과 대기 대상 객체, 차단 체인, 선두 세션의 마지막 SQL). 30초 이상 간격으로 두 번 호출해 지속 여부를 확인 |
| 오래 실행 중인 쿼리 | `long_running` (30초 이상 실행 중인 요청) |
| 오늘 수행된 쿼리 | `today_queries` (Query Store, UTC 자정 이후, query_hash 단위) |
| 느린 쿼리, 성능 저하 | `slow_queries` (오늘 평균 500ms 이상 또는 직전 7일 평균의 2배 이상) |
| 잠긴·비활성·만료 계정, sysadmin | `security` |
| 접속 시도, 로그인 실패 | `login_attempts` (Extended Events, 최근 24시간) |
| 디스크·파일 용량 | `storage` |
| 큰 테이블, 행 증가량 | `table_growth` 후 `SqlServerMetricsQuery`로 증가량 조회 |
| SQL Agent 작업 실패 | `jobs` |

## SqlServerMetricsQuery 예시

| 목적 | promql | lookback_minutes |
| --- | --- | --- |
| 테이블 행 증가량(1시간) | `sort_desc(delta(mssql_table_rows{sql_vm="@@VM_NAME@@"}[1h]))` | 0 |
| 테이블 행 추이(24시간) | `mssql_table_rows{sql_vm="@@VM_NAME@@"}` | 1440 |
| 대기 유형 추이 | `topk(5, rate(mssql_wait_time_seconds_total{sql_vm="@@VM_NAME@@"}[5m]))` | 60 |
| 차단 추이 | `max(mssql_blocked_requests{sql_vm="@@VM_NAME@@"})` | 120 |
| 로그인 실패 추이 | `sum by (login) (mssql_failed_logins_last_hour{sql_vm="@@VM_NAME@@"})` | 180 |
| 볼륨 여유 공간 | `mssql_volume_available_bytes{sql_vm="@@VM_NAME@@"}` | 0 |
| 데이터 파일 사용률 | `mssql_db_file_used_bytes{sql_vm="@@VM_NAME@@"} / mssql_db_file_size_bytes{sql_vm="@@VM_NAME@@"}` | 0 |

`mssql_table_rows`, Query Store, 파일 지표는 5분마다 갱신된다. managed
Prometheus는 레이블 값의 대소문자를 구분하지 않으므로 DB·테이블 이름은 소문자로
보일 수 있다.

## SqlServerQuery로 직접 조회

고정 operation으로 먼저 전체 상황을 보고, 특정 세션·객체·대기·설정을 더 파고들
때 SqlServerQuery를 쓴다. 사용자가 SQL로 직접 확인해 달라고 하면 바로 써도 된다.

- 읽기 전용 배치 하나만 보낸다. `INSERT`·`UPDATE`·`DELETE`·DDL·트랜잭션 제어·
  `EXEC`·동적 SQL·`USE`·`WAITFOR`는 거부된다. 임시 테이블(`#t`, `@t`), `EXEC`
  `sp_who2`·`sp_lock`·`sp_helpdb`·`sp_spaceused` 등과 `DBCC SQLPERF`·`INPUTBUFFER`·
  `OPENTRAN`·`SHOW_STATISTICS`는 허용된다.
- 사용자 테이블 데이터는 읽을 수 없다(오류 229). 행 수는 `sys.dm_db_partition_stats`로 본다.
- `sys.dm_db_*`, `sys.tables`, `sys.indexes`, Query Store 뷰는 `database`에 대상 DB를
  지정한다. 서버 범위 DMV는 기본값 `master`로 충분하다.
- 오류가 나면 반환된 SQL Server 오류 번호와 메시지를 읽고 쿼리를 고쳐 다시 실행한다.
  권한 오류(229, 297, 300)는 이 로그인의 범위 밖이므로 그대로 보고한다.
- 결과가 `truncated: true`면 조건이나 `TOP`으로 줄여 다시 조회한다.
- 보고에는 실행한 SQL을 코드 블록으로 함께 적는다.

참고 쿼리(필요에 맞게 고쳐 쓴다):

```sql
-- 잠금 대기: 누가 어떤 리소스를 어떤 모드로 기다리고 누가 막는지
SELECT wt.session_id, wt.blocking_session_id, wt.wait_type, wt.wait_duration_ms,
       DB_NAME(tl.resource_database_id) AS db, tl.resource_type, tl.request_mode,
       tl.resource_description, wt.resource_description AS wait_resource
FROM sys.dm_os_waiting_tasks AS wt
JOIN sys.dm_tran_locks AS tl ON tl.lock_owner_address = wt.resource_address
WHERE wt.wait_type LIKE N'LCK[_]%'
ORDER BY wt.wait_duration_ms DESC;

-- 세션별 보유 잠금 (객체 이름은 database에 해당 DB를 지정해 확인)
SELECT l.request_session_id, l.resource_type, l.request_mode, l.request_status, COUNT(*) AS locks,
       COALESCE(OBJECT_NAME(p.object_id), OBJECT_NAME(CASE WHEN l.resource_type = 'OBJECT'
                THEN l.resource_associated_entity_id END)) AS object_name
FROM sys.dm_tran_locks AS l
LEFT JOIN sys.partitions AS p ON p.hobt_id = l.resource_associated_entity_id
WHERE l.resource_database_id = DB_ID()
GROUP BY l.request_session_id, l.resource_type, l.request_mode, l.request_status,
         p.object_id, l.resource_associated_entity_id;

-- 열린 트랜잭션과 로그 사용량
SELECT st.session_id, s.login_name, s.program_name, s.status, at.transaction_begin_time,
       DATEDIFF(SECOND, at.transaction_begin_time, SYSDATETIME()) AS open_seconds,
       dt.database_transaction_log_bytes_used AS log_bytes
FROM sys.dm_tran_session_transactions AS st
JOIN sys.dm_tran_active_transactions AS at ON at.transaction_id = st.transaction_id
LEFT JOIN sys.dm_tran_database_transactions AS dt ON dt.transaction_id = st.transaction_id
JOIN sys.dm_exec_sessions AS s ON s.session_id = st.session_id
ORDER BY at.transaction_begin_time;

-- 메모리 grant 대기, tempdb 사용 상위 세션
SELECT session_id, requested_memory_kb, granted_memory_kb, wait_time_ms FROM sys.dm_exec_query_memory_grants;
SELECT TOP (10) session_id, (user_objects_alloc_page_count + internal_objects_alloc_page_count) * 8 AS tempdb_kb
FROM sys.dm_db_session_space_usage ORDER BY tempdb_kb DESC;
```

## 도구 사용 규칙

1. 한 번에 필요한 operation만 호출한다. 도구 오류(timeout, login failed)는
   네트워크 경로(VNet 통합, NSG 1433 허용, SQL 연결 유형 Private)나 Key Vault
   비밀 문제로 분류해 보고하고 다른 방법으로 VM에 접속하지 않는다.
2. 변경 작업(세션 종료, 인덱스 생성, 계정 잠금 해제, 비밀번호 변경, 작업 재실행,
   설정 변경)은 권고로만 제시하고 직접 실행하지 않는다. 이 로그인은 변경 권한이 없다.
3. `section_errors`나 `databases.errors`가 있으면 읽지 못한 항목을 보고에 포함한다.
4. 쿼리 텍스트에 리터럴 값이 보이면 같은 query_hash의 대표 문장일 뿐이라고 설명한다.

## 판단 기준

| 영역 | 확인 값 | 주의 기준 |
| --- | --- | --- |
| CPU | `cpu[].sql_cpu_pct` | 최근 샘플 다수가 80% 이상 |
| 대기 | `waits` 상위 항목 | `LCK_M_*` 차단, `PAGEIOLATCH_*` 디스크·메모리, `SOS_SCHEDULER_YIELD` CPU, `WRITELOG` 로그 I/O, `RESOURCE_SEMAPHORE` 메모리 grant |
| 메모리 | `Page life expectancy`, `Memory Grants Pending`, `process_memory_low` | PLE 300 미만 지속, grant pending 0 초과, memory low 1 |
| 잠금·차단 | `locks.held_table_locks`, `locks.waiting_locks`, `locks.head_blockers` | 대기 잠금이 두 번 연속 보이면 지속 차단. 선두 세션이 `sleeping`이고 `open_tran` 1 이상이면 커밋되지 않은 트랜잭션 |
| 장시간 실행 | `long_running.requests[].elapsed_s` | 5분 이상, 또는 `wait_type`이 잠금·I/O |
| 느린 쿼리 | `slow_queries[].ratio_vs_7d`, `avg_ms` | 비율 2 이상은 성능 저하(회귀), 기준선이 없으면 신규 쿼리 |
| 계정 | `security.locked`, `security.disabled`, `security.expired_or_must_change`, `security.sql_logins` | `locked` 1, `bad_password_count` 증가, 사용 중인데 `disabled`, sysadmin에 예상하지 않은 계정 |
| 접속 시도 | `security.failed_logins_24h`, `login_attempts.failed_by_login_client_reason` | 같은 login·client에서 반복 실패, 존재하지 않는 로그인 시도 |
| 스토리지 | `storage.volumes[].used_pct`, 파일 `used_pct`, `max_mb` | 볼륨 80% 이상, 파일 90% 이상이고 `max_mb`에 근접 |
| 테이블 증가 | `delta(mssql_table_rows[1h])` | 평소보다 큰 증가, 예상하지 않은 테이블의 증가 |
| 작업 | `jobs.jobs[].last_outcome`, `failures_today` | 실패 1회 이상이면 `failures_today[].message` 인용 |
| 백업 | `backups[]` | FULL 복구 모델인데 로그 백업이 없음, 전체 백업 없음 또는 24시간 초과 |

대기·쿼리 통계는 SQL Server 시작 이후 누적값이다. `overview.uptime_min`이
짧으면 결론의 신뢰도가 낮다고 밝힌다.

## 보고 형식

1. 한 줄 결론: 정상, 주의, 위험 중 하나와 가장 중요한 이유.
2. 근거 표: 영역, 측정값, 판단.
3. 권고 조치: 우선순위 순서. 각 조치에 예상 효과와 위험을 적는다.
4. 수집 시각(`collected_at_utc`, `executed_at_utc`)과 호출한 operation·SQL·PromQL 목록.
