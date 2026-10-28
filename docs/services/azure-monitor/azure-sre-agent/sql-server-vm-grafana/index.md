---
title: SQL Insights 은퇴 이후 SQL Server VM을 exporter와 Azure Managed Grafana로 모니터링하기
description: 관리자들이 널리 쓰는 SQL Server 점검 쿼리와 잠금 보유·대기, 장시간·금일 쿼리, 잠긴 계정과 로그인 실패, 스토리지, 테이블 행 증가, SQL Agent 작업을 sql_exporter 지표로 만들고, windows_exporter 성능 카운터와 함께 Azure Monitor managed Prometheus에 보내 Azure Managed Grafana 대시보드로 보는 구성을 배포부터 검증까지 재현합니다.
document_type: lab
services: [azure-monitor, azure-managed-grafana]
technologies: [prometheus, grafana, sql-server, bicep, powershell]
tags: [operate, diagnose]
status: verified
verification_status: verified
sources_checked_at: 2026-10-27
official_sources:
  - title: SQL Insights has been retired
    url: https://learn.microsoft.com/azure/azure-sql/database/sql-insights-overview
  - title: Enable performance monitoring for SQL Server on Azure VMs (preview)
    url: https://learn.microsoft.com/azure/azure-sql/virtual-machines/windows/enable-performance-monitoring-sql-vm
  - title: Monitor Azure SQL workloads with database watcher (preview)
    url: https://learn.microsoft.com/azure/azure-sql/database-watcher-overview
  - title: Connect self-managed Prometheus to Azure Monitor managed service for Prometheus
    url: https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-remote-write
  - title: Azure Monitor managed service for Prometheus technical details
    url: https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-metrics-details
  - title: Azure Monitor and Prometheus
    url: https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-metrics-overview
  - title: Structure of a data collection rule (DCR) in Azure Monitor
    url: https://learn.microsoft.com/azure/azure-monitor/data-collection/data-collection-rule-structure
  - title: What is Azure Managed Grafana?
    url: https://learn.microsoft.com/azure/managed-grafana/overview
  - title: Add an Azure Monitor workspace to Azure Managed Grafana to collect Prometheus data
    url: https://learn.microsoft.com/azure/managed-grafana/how-to-connect-azure-monitor-workspace
  - title: Connect Grafana to Azure Monitor managed service for Prometheus
    url: https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-grafana
  - title: sys.dm_os_wait_stats (Transact-SQL)
    url: https://learn.microsoft.com/sql/relational-databases/system-dynamic-management-views/sys-dm-os-wait-stats-transact-sql
  - title: Monitor SQL Server Components
    url: https://learn.microsoft.com/sql/relational-databases/performance/monitor-sql-server-components
  - title: sys.dm_tran_locks (Transact-SQL)
    url: https://learn.microsoft.com/sql/relational-databases/system-dynamic-management-objects/sys-dm-tran-locks-transact-sql
  - title: Monitor performance by using the Query Store
    url: https://learn.microsoft.com/sql/relational-databases/performance/monitoring-performance-by-using-the-query-store
  - title: GRANT Server Permissions (Transact-SQL)
    url: https://learn.microsoft.com/sql/t-sql/statements/grant-server-permissions-transact-sql
  - title: sys.sql_logins (Transact-SQL)
    url: https://learn.microsoft.com/sql/relational-databases/system-catalog-views/sys-sql-logins-transact-sql
  - title: sys.fn_xe_file_target_read_file (Transact-SQL)
    url: https://learn.microsoft.com/sql/relational-databases/system-functions/sys-fn-xe-file-target-read-file-transact-sql
  - title: SET QUOTED_IDENTIFIER (Transact-SQL)
    url: https://learn.microsoft.com/sql/t-sql/statements/set-quoted-identifier-transact-sql
  - title: sys.dm_db_partition_stats (Transact-SQL)
    url: https://learn.microsoft.com/sql/relational-databases/system-dynamic-management-objects/sys-dm-db-partition-stats-transact-sql
  - title: Run scripts in your Windows VM by using managed Run Commands
    url: https://learn.microsoft.com/azure/virtual-machines/windows/run-command-managed
  - title: prometheus-community/windows_exporter mssql collector
    url: https://github.com/prometheus-community/windows_exporter/blob/master/docs/collector.mssql.md
  - title: burningalchemist/sql_exporter
    url: https://github.com/burningalchemist/sql_exporter
  - title: OpenTelemetry Collector Contrib SQL Server receiver
    url: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/sqlserverreceiver
  - title: prometheus-community/postgres_exporter
    url: https://github.com/prometheus-community/postgres_exporter
last_verified: 2026-10-27
review_cycle_days: 90
estimated_time: 60m
cost: paid
cleanup_required: true
topic_order: 11
---

# SQL Insights 은퇴 이후 SQL Server VM을 exporter와 Azure Managed Grafana로 모니터링하기

이 실습은 [SRE Agent 상태 점검 실습](../sql-server-vm-health-check/index.md)과 같은
SQL Server VM에 지표 파이프라인을 더합니다. 관리자들이 널리 쓰는 SQL Server
점검 쿼리가 공통으로 보는 항목을 sql_exporter collector로 만들고,
windows_exporter의 SQL Server 성능 카운터와 함께 Prometheus 에이전트가 Azure
Monitor workspace로 보냅니다. Azure Managed Grafana에서는 `SQL Server VM 상태`
대시보드로 봅니다.

2026-10-27 Korea Central에서 실제로 배포해 확인한 결과는 다음과 같습니다.

- Prometheus 에이전트의 remote write는 첫 60초 동안 7,242개 샘플을 보냈고
  실패·재시도는 0건이었습니다.
- 대시보드의 패널 쿼리를 Azure Monitor workspace에 그대로 실행하자, 정상
  서버에서 비어 있어야 하는 `문제 DB` 패널을 제외한 모든 쿼리가 데이터를
  반환했습니다.
- Grafana 12.4.8(Standard)이 자체 관리 ID로 같은 workspace를 조회해 HTTP 200을
  반환했고, CPU 부하 중 상위 대기는 `SOS_SCHEDULER_YIELD`(초당 2.35초)였습니다.
- 확장한 collector로 잠긴 계정(`app_user`, 실패 10회), 계정·클라이언트·사유별
  로그인 실패(각 48건), `AuditEvents` 1시간 증가량, 오늘 실패한 SQL Agent 작업,
  금일 Query Store 상위 쿼리가 대시보드에 나타났습니다. 46개 패널 중 데이터가 없던
  것은 부하가 없을 때 비어 있어야 하는 현재 잠금·차단, 장시간 실행 요청, 문제 DB
  패널뿐이었고, 잠금 부하 중에는 잠금 패널도 채워졌습니다.

## Grafana 대시보드 하나로 상태·잠금·쿼리·계정·용량을 본다

![SQL Server VM 상태 대시보드 상단. 수집 상태, 가동 시간, Batch requests, 사용자 연결, 차단된 요청, Page life expectancy, CPU와 대기 통계 패널](images/dashboard-summary.png)

잠금 부하를 건 상태에서는 잠금 상세 행에 모드·상태별 잠금 수와 현재 차단 관계(차단 세션,
대기 세션, 대기 리소스)가 표로 나타납니다.

![잠금 상세 행. 보유·대기 중인 잠금, 리소스 유형별 잠금 대기 시간, 현재 차단 관계 표](images/dashboard-locks.png)

![세션·장시간 쿼리와 금일 쿼리 행. 30초 이상 실행 중인 요청과 Query Store 기준 금일 상위 쿼리](images/dashboard-sessions-queries.png)

![보안·접속 행. SQL 로그인 잠김·사용 중지 상태, sysadmin 구성원, 최근 1시간 로그인 실패와 성공](images/dashboard-security.png)

![스토리지와 테이블 증가 행. 볼륨 사용률, DB 파일 크기, 테이블 행 수와 1시간 증가량](images/dashboard-storage-tables.png)

같은 지표를 SRE Agent도 `SqlServerMetricsQuery` 도구로 조회합니다. 채팅 예시는
[SRE Agent 실습](../sql-server-vm-health-check/index.md)에 있습니다.

## 관리자들이 먼저 돌리는 공개 점검 쿼리 모음

SQL Server 관리자들이 상태 점검에 널리 쓰는 공개 스크립트는 다음과 같습니다.
모두 DMV와 시스템 뷰를 읽으며, 일부는 서버에 저장 프로시저를 설치해야 합니다.
라이선스와 상태는 2026-10-27 각 저장소·배포처 기준입니다.

| 모음 | 관리 주체 | 라이선스 | 주로 보는 것 |
| --- | --- | --- | --- |
| [SQL Server Diagnostic Information Queries](https://glennsqlperformance.com/resources/) | Glenn Berry | 배포처 조건 확인 | SQL Server 버전별 스크립트. 구성, 대기 통계, CPU·메모리, 파일 I/O 지연, 상위 쿼리, 인덱스 |
| [First Responder Kit](https://github.com/BrentOzarULTD/SQL-Server-First-Responder-Kit) (`sp_Blitz`, `sp_BlitzFirst`, `sp_BlitzCache`, `sp_BlitzIndex`, `sp_BlitzWho`) | Brent Ozar Unlimited | MIT | 서버 전반 위험 점검, 짧은 구간 샘플링, 계획 캐시 상위 쿼리, 인덱스 진단, 현재 실행 요청 |
| [sp_WhoIsActive](https://github.com/amachanic/sp_whoisactive) | Adam Machanic | GPL-3.0 | 현재 실행 중인 세션, 차단, 대기, 열린 트랜잭션 |
| [DarlingData](https://github.com/erikdarlingdata/DarlingData) (`sp_PressureDetector` 등) | Erik Darling | MIT | CPU·메모리 압박, Query Store 분석 |
| [Tiger Toolbox](https://github.com/microsoft/tigertoolbox) | Microsoft SQL Server Tiger team | 저장소 조건 확인 | 모범 사례 점검 스크립트 |
| [SQL Server Maintenance Solution](https://github.com/olahallengren/sql-server-maintenance-solution) | Ola Hallengren | MIT | 점검보다 백업·무결성 검사·인덱스 유지 관리 작업 |

이 스크립트들이 공통으로 출발하는 항목은 `sys.dm_os_wait_stats` 같은 DMV입니다.
대기 통계는 `VIEW SERVER STATE` 권한으로 읽을 수 있고 엔진 시작 이후 누적된
값입니다. 이 실습은 외부 저장 프로시저를 설치하지 않고, 공통 항목만 읽기 전용
쿼리로 다시 작성해 지표로 만듭니다.

| 점검 항목 | 사용한 DMV·시스템 뷰 | 지표 |
| --- | --- | --- |
| 대기 통계 (유휴성 대기 제외) | `sys.dm_os_wait_stats` | `mssql_wait_time_seconds_total`, `mssql_signal_wait_time_seconds_total` |
| CPU 사용률 | `sys.dm_os_ring_buffers` 스케줄러 모니터 | `mssql_cpu_percent` |
| 차단과 선두 차단 세션 | `sys.dm_exec_requests` | `mssql_blocked_requests`, `mssql_head_blockers`, `mssql_longest_blocked_wait_seconds` |
| 오래 열린 트랜잭션 | `sys.dm_tran_active_transactions`, `sys.dm_tran_session_transactions` | `mssql_oldest_open_transaction_seconds` |
| DB 상태·복구 모델 | `sys.databases` | `mssql_database_online` |
| 로그 사용률과 재사용 대기 | `sys.dm_os_performance_counters`, `sys.databases` | `mssql_log_used_percent`, `mssql_log_reuse_waiting` |
| 마지막 백업 | `msdb.dbo.backupset` | `mssql_last_backup_timestamp_seconds` |
| DB 파일 I/O 지연 | `sys.dm_io_virtual_file_stats` | `mssql_io_stall_seconds_total`, `mssql_io_operations_total` |
| 누락 인덱스 제안 | `sys.dm_db_missing_index_*` | `mssql_missing_index_suggestions` |
| 메모리 상한 설정 | `sys.configurations` | `mssql_max_server_memory_bytes` |
| 잠금 보유·대기 (DB·리소스 유형·모드·상태) | `sys.dm_tran_locks` | `mssql_locks`, `mssql_blocking_wait_seconds` |
| 장시간 실행 요청 (30초 이상) | `sys.dm_exec_requests`, `sys.dm_exec_sessions` | `mssql_long_running_request_seconds` |
| 금일 상위 쿼리 (UTC 자정 이후, `query_hash` 단위) | 각 사용자 DB의 Query Store | `mssql_query_today_executions`, `mssql_query_today_avg_duration_seconds` 등 |
| SQL 로그인 잠금·사용 중지·만료, sysadmin 구성원 | `sys.sql_logins`, `LOGINPROPERTY`, 서버 역할 | `mssql_sql_login_*`, `mssql_sysadmin_member` |
| 최근 1시간 로그인 실패·성공 | XE 세션 `sre_login_audit`의 이벤트 파일 | `mssql_failed_logins_last_hour`, `mssql_successful_logins_last_hour` |
| 볼륨·DB 파일 사용량 | `sys.dm_os_volume_stats`, 각 DB의 `sys.database_files`와 `FILEPROPERTY` | `mssql_volume_*`, `mssql_db_file_*` |
| 테이블 행 수·예약 공간 | 각 사용자 DB의 `sys.dm_db_partition_stats` | `mssql_table_rows`, `mssql_table_reserved_bytes` |
| SQL Agent 상태와 작업 실패 | `sys.dm_server_services`, `msdb.dbo.sysjobs`·`sysjobhistory` | `mssql_agent_running`, `mssql_job_*` |

행 증가량은 별도 이력 테이블 없이 `delta(mssql_table_rows[1h])`처럼 시계열에서
계산합니다. 금일 쿼리, 스토리지, 테이블 지표는 5분, 로그인 이벤트는 1분 간격으로
캐시해 scrape마다 DB를 순회하지 않습니다(collector의 `min_interval`).

Batch requests, Page life expectancy, Memory grants pending, 잠금 대기, 교착 같은
성능 카운터는 windows_exporter의 `mssql` collector가 수집합니다.

## Microsoft 관리형 선택지가 이 VM에 맞지 않는 이유

| 선택지 | 상태 (2026-10-27 확인) | 이 실습에서의 판단 |
| --- | --- | --- |
| SQL Insights | 2024-12-31에 은퇴. 문서는 SQL Server VM에 VM Insights와 DCR을 안내 | 사용할 수 없음 |
| Database watcher (preview) | 지원 대상은 Azure SQL Database와 Azure SQL Managed Instance | SQL Server on Azure VM 대상 아님 |
| SQL Server on Azure VMs performance monitoring (preview) | SQL IaaS Agent 확장이 수집. Developer·Express·Evaluation edition은 클라이언트 연결 데이터(`SqlServerClientConnections`)만 수집 | 이 실습 VM은 Developer edition이라 대기·세션 데이터가 없음 |
| Azure Monitor Agent의 Prometheus 수집 | DCR의 `prometheusForwarder`는 Kubernetes 클러스터용 | VM의 exporter를 직접 수집하지 못함 |

Standard·Enterprise edition이라면 performance monitoring (preview)도 함께 검토할
만합니다. 이 실습은 edition과 관계없이 동작하고 Grafana에서 PromQL로 다룰 수 있는
exporter 방식을 택했습니다.

## SQL Server exporter 후보 비교

| exporter | 수집 방식 | 상태 (2026-10-27) | 이 실습의 사용 |
| --- | --- | --- | --- |
| [windows_exporter](https://github.com/prometheus-community/windows_exporter) `mssql` collector | SQL Server 성능 카운터(WMI 클래스) | v0.32.0, MIT, MSI로 서비스 설치 | 사용. OS 지표(cpu, memory, logical_disk 등)도 함께 수집 |
| [sql_exporter](https://github.com/burningalchemist/sql_exporter) | 설정 파일의 SQL 쿼리를 지표로 변환 | 0.24.12, MIT, Windows 서비스 등록 지원 | 사용. 위 점검 항목을 collector로 정의 |
| [Telegraf `sqlserver` input](https://github.com/influxdata/telegraf/tree/master/plugins/inputs/sqlserver) | 미리 정의된 DMV 쿼리 묶음(성능 카운터, 대기, 요청, 백업 등) | Telegraf v1.40.2, MIT | 대안. 출력 형식과 수집 경로를 따로 구성해야 함 |
| [Grafana Alloy `prometheus.exporter.mssql`](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.mssql/) | sql_exporter를 내장. 기본 `mssql_standard` collector, `query_config`로 사용자 쿼리 지정 | Alloy 구성 요소 | 대안. 사용자 쿼리를 지정하면 기본 collector를 대체 |
| [OpenTelemetry `sqlserverreceiver`](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/sqlserverreceiver) | 성능 카운터와 DMV | 지표는 beta, 일부 지표는 Development 단계 | 대안. 잠금 대기율·교착률·차단 프로세스 수 같은 카운터 |
| [awaragi/prometheus-mssql-exporter](https://github.com/awaragi/prometheus-mssql-exporter) | Node.js 기반 고정 쿼리 | 마지막 릴리스 2022-04 | 제외 |

## 잠금 현황은 postgres_exporter처럼 기본 제공되지 않아 직접 정의

PostgreSQL의 [postgres_exporter](https://github.com/prometheus-community/postgres_exporter)는
`pg_locks`를 DB·모드별로 센 `pg_locks_count{datname,mode}`를 기본으로 냅니다.
SQL Server용 exporter를 같은 관점에서 비교하면 다음과 같습니다(2026-10-27 확인).

| 원본 | 잠금 관련 지표 | 한계 |
| --- | --- | --- |
| windows_exporter `mssql` | Locks 성능 카운터: 리소스 유형(`resource`)별 잠금 대기 수·대기 시간, 교착, 타임아웃 | 누적 카운터라 지금 잠금을 잡은 세션이나 대기 중인 객체를 알 수 없음 |
| Alloy `mssql_standard`, OTel `sqlserverreceiver` | 잠금 대기율, 교착률, 차단된 프로세스 수 | 마찬가지로 현재 잠금 목록이 아님 |
| 이 실습의 sql_exporter collector | `sys.dm_tran_locks`를 DB·리소스 유형·모드·상태(`GRANT`/`WAIT`)별로 센 `mssql_locks`, 대기 중인 잠금의 대기 시간 `mssql_blocking_wait_seconds`(차단 세션·대기 세션·프로그램·대기 리소스 레이블) | 30초 scrape 사이의 짧은 잠금은 놓침 |

`mssql_locks`는 `pg_locks_count`에 해당하는 현재 잠금 분포이고, 어느 세션이 어느
테이블을 잡았는지 같은 세부 조회는 [SRE Agent의 `locks` operation](../sql-server-vm-health-check/index.md)이
실행 시점의 DMV로 답하고, 더 파고들 때는 에이전트가 `SqlServerQuery`로 읽기 전용
SQL을 직접 실행합니다. 세션 ID 같은 레이블은 시계열 수를 늘리므로 대기 중인
잠금에만 붙입니다.

## Prometheus가 30초마다 exporter를 수집해 관리 ID로 workspace에 전송

![SQL Server VM 실습 구성도. SRE Agent 도구는 질문할 때만 snet-agent에서 실행되어 Key Vault 비밀번호로 SQL Server를 조회하고, VM의 Prometheus는 30초마다 windows_exporter와 sql_exporter를 scrape해 Azure Monitor workspace로 remote write하며, Grafana와 에이전트가 PromQL로 조회한다](images/architecture.svg)

VM 안의 수집은 pull, VM에서 Azure로 보내는 것은 push입니다. 조회 쪽(Grafana,
SRE Agent)은 저장된 시계열을 필요할 때 PromQL로 읽습니다.

| 구성 요소 | 동작 방식 | 주기 | 내용 |
| --- | --- | --- | --- |
| Prometheus 3.15.1 (agent 모드, 예약 작업 `PrometheusAgent`) | 두 exporter의 `/metrics`를 scrape (pull) | 30초, 제한 시간 25초 | 수집한 시계열에 외부 레이블 `sql_vm`을 붙임. 로컬에는 전송 대기용 WAL만 둠 |
| windows_exporter v0.32.0 (서비스) | scrape 요청을 받을 때 성능 카운터·OS 지표를 읽어 응답 | 30초 | SQL Server 성능 카운터(batch requests, 컴파일, PLE, 메모리, 잠금 대기·교착·타임아웃), CPU·메모리·디스크·네트워크 |
| sql_exporter 0.24.12 `mssql_health` | scrape 요청 때 DMV 쿼리 실행 | 30초 (`min_interval` 25초) | 대기, CPU, 차단·잠금, 장시간 요청, 열린 트랜잭션, DB 상태·로그, 백업, 파일 I/O, 로그인 상태, SQL Agent 작업 |
| sql_exporter `mssql_audit` | scrape 요청 때 쿼리, 결과를 캐시해 재사용 | 60초 | 최근 1시간 로그인 실패·성공 (XE 이벤트 파일) |
| sql_exporter `mssql_inventory` | scrape 요청 때 사용자 DB를 순회해 쿼리, 결과 캐시 | 5분 | 금일 상위 쿼리(Query Store), 볼륨·DB 파일 사용량, 테이블 행 수·크기 |
| XE 세션 `sre_login_audit` | SQL Server가 이벤트 발생 시 파일에 기록 (push) | 최대 5초 버퍼 | 로그인 실패(오류 18456), 풀 재사용이 아닌 로그인 성공 |
| Prometheus remote write | VM 관리 ID 토큰으로 workspace 기본 DCR에 전송 (push, HTTPS, NAT Gateway 경유) | 기본 설정으로 샘플을 묶어 최대 약 5초 안에 전송 | 실패하면 WAL에서 재시도 |
| Azure Managed Grafana 대시보드 | 패널별 PromQL 조회 (pull) | 대시보드가 열려 있는 동안 30초 | 기본 시간 범위 최근 1시간 |

| 결정 | 이유 |
| --- | --- |
| exporter와 Prometheus는 루프백 주소에만 바인딩 | 지표 엔드포인트를 네트워크에 노출하지 않습니다. NSG 규칙도 추가하지 않습니다. |
| sql_exporter를 가상 서비스 계정 `NT SERVICE\SqlExporterSvc`로 실행 | DSN에 사용자가 없으면 go-mssqldb가 Windows에서 SSO를 사용합니다. 저장할 비밀번호가 없습니다. |
| 해당 로그인에 `VIEW SERVER STATE`, `VIEW ANY DEFINITION`, `CONNECT ANY DATABASE`와 `msdb`의 `backupset`·`sysjobs`·`sysjobhistory` SELECT만 부여 | 로그인 상태, 테이블 행 수, 각 DB의 Query Store와 파일 사용량을 읽는 최소 조합입니다. 사용자 테이블을 SELECT하면 오류 229로 거부됩니다(관측). 권한별 근거는 [SRE Agent 실습](../sql-server-vm-health-check/index.md)에 정리했습니다. |
| Prometheus는 agent 모드(`--agent`) | 로컬 쿼리·저장 없이 수집과 remote write만 합니다. |
| VM 전용 사용자 할당 관리 ID로 remote write | Azure VM의 사용자 할당 관리 ID 인증은 Prometheus 2.45 이상에서 지원합니다. 이 실습은 3.15.1을 씁니다. |
| Monitoring Metrics Publisher는 workspace의 기본 DCR에만 부여 | 공식 절차가 지정한 범위입니다. |
| Grafana 관리 ID의 Monitoring Data Reader는 workspace에만 부여 | Bicep으로 만든 Grafana에는 이 할당 하나만 있었습니다(관측). 포털 흐름처럼 구독 범위로 넓히지 않습니다. |
| 다운로드 파일은 버전과 SHA256으로 고정 | GitHub 릴리스 자산의 digest와 일치할 때만 설치합니다. |

## 같은 deploy.sh가 지표 파이프라인과 대시보드까지 구성

sample은 [samples/sqlvm-health-lab](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-monitor/azure-sre-agent/samples/sqlvm-health-lab)에 있습니다.

```bash
cd docs/services/azure-monitor/azure-sre-agent/samples/sqlvm-health-lab
./scripts/deploy.sh rg-sqlvm-sre-lab koreacentral
```

SRE Agent 실습의 단계 뒤에 다음이 이어집니다.

1. Bicep이 Azure Monitor workspace(`Microsoft.Monitor/accounts`), Azure Managed
   Grafana(`Microsoft.Dashboard/grafana`, Standard, 시스템 관리 ID), VM의 지표용
   사용자 할당 관리 ID를 만듭니다. Grafana에는
   `grafanaIntegrations.azureMonitorWorkspaceIntegrations`로 workspace를 연결해
   Prometheus 데이터 원본을 자동으로 만듭니다.
2. `scripts/configure-monitoring.sh`가 workspace의 기본 DCR·DCE에서 remote write
   URL을 조합하고, VM 관리 ID에 DCR의 Monitoring Metrics Publisher를 부여합니다.
3. 같은 스크립트가 managed Run Command로 VM에서 두 단계를 실행합니다.
   - `configure-monitoring.ps1` (LocalSystem): 세 바이너리 다운로드·SHA256 확인,
     windows_exporter MSI 설치, sql_exporter 서비스 등록, Prometheus 에이전트
     예약 작업 등록
   - `grant-exporter-login.ps1` (일회용 비밀번호로 재설정한 로컬 관리자): SQL
     Server 로그인 생성과 권한 부여, sql_exporter 재시작, remote write 카운터 보고

   sql_exporter는 세 collector 파일을 읽습니다. `mssql_health`(30초마다),
   `mssql_audit`(로그인 이벤트, 1분 캐시), `mssql_inventory`(Query Store·스토리지·
   테이블, 5분 캐시)입니다. 로그인 이벤트는 SRE Agent 실습의 `configure-checks.ps1`이
   만든 XE 세션 `sre_login_audit`에서 읽습니다.
4. `scripts/import-dashboard.sh`가 Grafana의 Prometheus 데이터 원본 UID를 찾아
   대시보드를 가져옵니다.

`configure-monitoring.sh`의 마지막 출력에서 remote write 상태를 확인합니다.

```text
prometheus_remote_storage_samples_failed_total{...} 0
prometheus_remote_storage_samples_retried_total{...} 0
prometheus_remote_storage_samples_total{...} 7242
```

공식 문서에 따르면 역할 할당이 적용되기까지 약 30분이 걸릴 수 있고, 그동안
Prometheus 로그에 HTTP 403이 보일 수 있습니다. 이 실습에서는 첫 실행부터 실패가
없었습니다.

## 대시보드 패널과 확인할 신호

| 영역 | 패널 | 확인할 신호 |
| --- | --- | --- |
| 요약 | 수집 상태, 가동 시간, Batch requests/s, 사용자 연결, 차단된 요청, Page life expectancy, Memory grants pending, 가장 오래된 열린 트랜잭션 | 차단 1 이상, grant pending 1 이상, 오래 열린 트랜잭션 |
| CPU·처리량 | SQL Server 측정 CPU와 VM 전체 CPU, 요청·컴파일·재컴파일 | SQL Server 외 프로세스의 CPU 사용, 재컴파일 급증 |
| 대기 통계 | 상위 10개 대기 유형, signal wait 비율 | 차단(`LCK_M_*`), I/O(`PAGEIOLATCH_*`), CPU(`SOS_SCHEDULER_YIELD`) 중 무엇이 지배적인지 |
| 차단·잠금 | 차단 수·선두 세션, 가장 긴 차단 대기, 잠금 대기·교착 | 지속되는 차단과 교착 발생 |
| 메모리 | Total·Target server memory와 OS 가용 메모리, PLE, max server memory 설정 | 상한 미설정(2147483647 MB) |
| 데이터베이스·백업 | 로그 사용률, 마지막 전체·로그 백업, 오프라인·로그 재사용 대기, DB 크기, 누락 인덱스 제안 | 백업 `기록 없음`, 로그 사용률 증가 |
| I/O | DB별 평균 읽기·쓰기 지연, 디스크 사용률 | 파일 지연 증가와 디스크 여유 공간 |
| 잠금 상세 | 모드·상태별 보유·대기 잠금, DB·리소스·모드별 대기 잠금, 리소스 유형별 잠금 대기 시간, 현재 차단 관계 표, 잠금 타임아웃·에스컬레이션 | `WAIT` 상태 잠금의 지속, 같은 차단 세션 반복 |
| 세션·장시간 쿼리 | 30초 이상 실행 중인 요청 수와 목록(세션, 로그인, 프로그램, 대기 유형, SQL 앞부분) | 5분 이상 요청, 잠금·I/O 대기 중인 장시간 요청 |
| 금일 쿼리 (Query Store) | 누적 실행 시간·실행 수·평균 실행 시간 상위 쿼리 | 실행 수가 많은 짧은 쿼리, 평균이 긴 쿼리 |
| 보안·접속 | SQL 로그인 잠김·사용 중지·만료·실패 횟수, sysadmin 구성원, 최근 1시간 로그인 실패·성공 | 잠긴 계정, 존재하지 않는 로그인 시도, 예상하지 않은 sysadmin |
| 스토리지 | 볼륨 사용률, DB 파일 크기·사용량·최대 크기 | 볼륨 80%, 파일 90% 이상 |
| 테이블 증가 | 행 수 상위 테이블, 1시간 행 증가량, 행 수 추이 | 평소보다 큰 증가 |
| SQL Agent 작업 | Agent 실행 여부, 작업별 마지막 결과·실행 시각·금일 실패 수 | 실패 1회 이상 |

모든 쿼리는 Prometheus 외부 레이블 `sql_vm`으로 VM을 구분하므로, 같은
workspace에 여러 SQL Server VM을 보내면 대시보드 상단 변수로 전환할 수 있습니다.

## 패널 쿼리를 workspace와 Grafana 양쪽에서 실행해 검증

`scripts/verify_dashboard_queries.py`는 대시보드의 모든 패널 쿼리를 Azure
Monitor workspace의 PromQL 엔드포인트에 실행합니다. CPU 부하
(`./scripts/generate-load.sh cpu 30`) 중의 결과 일부입니다.

| 패널 | 결과 |
| --- | --- |
| 수집 상태 | `1` (UP) |
| Batch requests/s | 약 61 |
| CPU 사용률 (VM 전체) | 약 77.9% |
| Page life expectancy | 14,688초 |
| Signal wait 비율 | 약 0.99 |
| 상위 10개 대기 유형 | 10개 시계열 |
| 마지막 백업 | 4개 DB × 전체·로그 = 8개 행 |
| 데이터베이스 크기 | 7개 DB × 데이터·로그 = 14개 시계열 |
| 문제 DB: 오프라인·로그 재사용 대기 | 0개 (정상) |

확장 패널은 데모 부하를 함께 실행한 2026-10-27 17:3x~17:5x UTC에 같은 스크립트로
확인했습니다.

| 패널 | 결과 |
| --- | --- |
| SQL 로그인 상태 | `app_user` 잠김 1·잘못된 비밀번호 10회(`badlogin` 직후), `legacy_report`·`sa` 사용 중지 |
| 로그인 실패 (최근 1시간) | `app_user`(비밀번호 불일치)·`scanner`(로그인 없음) 각 48건, 클라이언트 `127.0.0.1` |
| 1시간 행 증가량 | `dbo.AuditEvents` 약 234,000행, `dbo.Orders` 0 |
| 작업 상태 | `sre-demo-nightly-check` 금일 실패 5회 |
| 금일 상위 쿼리 | `SreDemo`의 6개 `query_hash`. 점검 쿼리는 제외됨 |
| 보유·대기 중인 잠금 (`blocking` 중) | `S`/`WAIT` 3, `IX`/`GRANT` 31, `IS`/`GRANT` 6 |
| 현재 차단 관계 (`blocking` 중) | 차단 세션 77(`sre-demo-load`), 대기 리소스 `KEY` |

Grafana 쪽 경로는 Grafana HTTP API `/api/ds/query`를 Microsoft Entra 토큰으로
호출해 확인했습니다. 두 쿼리 모두 HTTP 200을 반환했고 상위 대기는
`sos_scheduler_yield`였습니다.

```bash
TOKEN=$(az account get-access-token --resource ce34e7e5-485f-4d76-964f-b3d2b16d1e4f --query accessToken -o tsv)
curl -sS -X POST "$GRAFANA_ENDPOINT/api/ds/query" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" --data @query.json
```

## remote write·패널 데이터·Grafana 경로·최소 권한이 모두 확인되면 통과

| 확인 항목 | 통과 기준 |
| --- | --- |
| remote write | `prometheus_remote_storage_samples_failed_total`이 0이고 `samples_total`이 증가 |
| 패널 데이터 | `verify_dashboard_queries.py`가 종료 코드 0 |
| Grafana 경로 | Grafana 데이터 원본 쿼리가 HTTP 200과 시계열을 반환 |
| 노출 범위 | exporter와 Prometheus가 `127.0.0.1`에만 바인딩, NSG 변경 없음 |
| 최소 권한 | `NT SERVICE\SqlExporterSvc`가 sysadmin이 아니고 위 서버 권한과 `msdb` 이력 읽기만 보유 |
| 확장 패널 | 부하별로 잠금·로그인 실패·행 증가·작업 실패 패널이 값을 반환 |

## Grafana Standard 인스턴스와 지표 수집·조회 비용

| 자원 | 과금 특성 |
| --- | --- |
| Azure Managed Grafana Standard (X1) | Standard 요금. 새 workspace는 Standard 계층만 만들 수 있습니다. 가격은 Azure Managed Grafana 가격 페이지를 확인합니다. |
| Azure Monitor workspace (managed Prometheus) | 수집량과 쿼리량 기준. 저장은 18개월까지 추가 비용이 없습니다. |
| VM, NAT Gateway 등 | [SRE Agent 실습](../sql-server-vm-health-check/index.md)과 동일 |

이 실습의 수집량은 VM 한 대, 30초 간격입니다. sql_exporter의 대기 유형 레이블과
금일 쿼리의 `query_hash`·`query_text`, 테이블 이름 레이블이 시계열 수를 가장 많이
늘립니다. 금일 쿼리는 DB별 상위 10개, 테이블은 DB별 행 수 상위 20개로 제한했습니다. 여러
VM으로 확장할 때는 이 상한과 대기 유형 수를 줄이는 것을 검토합니다.

## 리소스 그룹 삭제로 정리하고 workspace 관리 리소스 그룹 확인

```bash
./scripts/cleanup.sh
```

Azure Monitor workspace와 Grafana도 같은 리소스 그룹에 있으므로 함께
삭제됩니다. workspace의 기본 DCR·DCE는 Azure가 만든
`MA_<workspace>_<region>_managed` 리소스 그룹에 있습니다(관측). 스크립트는 정리
후 이 리소스 그룹이 남아 있으면 알려 줍니다.

## 구성 중 만난 오류와 대응

| 증상 | 원인 | 대응 |
| --- | --- | --- |
| windows_exporter 서비스가 시작 직후 중지, 이벤트 로그에 `unknown collector cs` | v0.32.0에 `cs` collector가 없음(관측) | 수집기 목록을 `cpu,logical_disk,memory,net,os,system,mssql`로 지정합니다. |
| RunAs로 실행한 스크립트가 출력 없이 `System error ... 'Incorrect function.'` | 스크립트가 종료 코드 1로 끝나면 managed Run Command가 이 메시지만 반환(관측). 처음에는 스크립트 크기 문제로 오인했음 | 스크립트를 `try`/`catch`로 감싸 로그 파일을 남기고 SYSTEM Run Command로 읽어 실제 오류를 확인합니다. 설치는 LocalSystem, SQL 로그인 생성만 RunAs로 나눈 구성은 유지합니다. |
| 재실행 시 `prometheus.exe ... being used by another process` | 예약 작업의 재시작 설정이 중지한 Prometheus를 다시 띄움(관측) | 바이너리 교체 전에 예약 작업을 비활성화하고, 같은 해시의 바이너리는 복사하지 않습니다. |
| sql_exporter 설정을 읽지 못함 | `job`, `instance`는 Prometheus가 예약한 레이블 | SQL Agent 작업 이름 레이블을 `job_name`으로 씁니다. |
| 로그인 실패 패널이 비어 있음 | 세 가지가 겹침(관측): `ring_buffer` XML이 잘림(`truncated=1`), 이벤트 파일을 `WHERE timestamp_utc > ...`로 거르면 0건, XML 메서드가 `QUOTED_IDENTIFIER` 기본값에서 오류 1934 | `event_file` 대상, 공식 예제의 `CAST(timestamp_utc AS datetime2(7))` 비교, 쿼리 앞 `SET QUOTED_IDENTIFIER ON;`을 적용합니다. |
| 로그인 실패가 두 배로 집계 | 실패 한 번에 오류 18456 이벤트가 두 번 발생하고, 오류 로그용 메시지에만 `[CLIENT: ...]`가 있음 | 해당 문자열이 있는 이벤트만 셉니다. |
| 금일 상위 쿼리에 exporter 자체 쿼리가 보임 | DB마다 실행하는 메타데이터 쿼리도 Query Store에 기록됨 | `query_store_runtime_stats`, `dm_db_partition_stats`, `sys.database_files`를 포함한 문장을 제외합니다. |
| 설치 직후 sql_exporter `/metrics`가 HTTP 500 | 서비스 계정의 SQL Server 로그인이 아직 없음 | 설치 단계는 시작 페이지만 확인하고, 로그인 생성 뒤 `/metrics`를 확인합니다. |
| 쿼리 결과의 DB 이름이 `SreDemo`가 아니라 `sredemo` | managed Prometheus는 대소문자를 구분하지 않으며 반환되는 대소문자가 일정하지 않음 | 레이블 값 비교가 대소문자에 의존하지 않게 작성합니다. |
| 테이블에 `microsoft.amwresourceid` 열이 보임 | workspace가 반환하는 시계열에 workspace 리소스 ID 레이블이 붙음(관측) | 테이블 변환에서 해당 열을 숨깁니다. |
| `az grafana data-source query`가 `Invalid time range` 오류 | CLI가 보낸 시간 범위를 workspace가 거부(관측) | Grafana HTTP API `/api/ds/query`에 밀리초 단위 `from`·`to`를 직접 지정합니다. |

## 공식 참고 자료

- [SQL Insights has been retired](https://learn.microsoft.com/azure/azure-sql/database/sql-insights-overview):
  2024-12-31 은퇴, SQL Server VM은 VM Insights와 DCR 안내
- [Enable performance monitoring for SQL Server on Azure VMs (preview)](https://learn.microsoft.com/azure/azure-sql/virtual-machines/windows/enable-performance-monitoring-sql-vm):
  edition별 수집 범위
- [Monitor Azure SQL workloads with database watcher (preview)](https://learn.microsoft.com/azure/azure-sql/database-watcher-overview):
  지원 대상
- [Connect self-managed Prometheus to Azure Monitor managed service for Prometheus](https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-remote-write):
  VM의 관리 ID 인증, Prometheus 버전 요구 사항, DCR 역할, 403 지연
- [Azure Monitor managed service for Prometheus technical details](https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-metrics-details):
  대소문자 비구분
- [Azure Monitor and Prometheus](https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-metrics-overview):
  workspace 저장과 요금 구조
- [Structure of a data collection rule (DCR) in Azure Monitor](https://learn.microsoft.com/azure/azure-monitor/data-collection/data-collection-rule-structure):
  `prometheusForwarder`의 대상
- [What is Azure Managed Grafana?](https://learn.microsoft.com/azure/managed-grafana/overview):
  Standard·Essential 서비스 계층
- [Add an Azure Monitor workspace to Azure Managed Grafana to collect Prometheus data](https://learn.microsoft.com/azure/managed-grafana/how-to-connect-azure-monitor-workspace),
  [Connect Grafana to Azure Monitor managed service for Prometheus](https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-grafana):
  Monitoring Data Reader 역할
- [sys.dm_os_wait_stats (Transact-SQL)](https://learn.microsoft.com/sql/relational-databases/system-dynamic-management-views/sys-dm-os-wait-stats-transact-sql),
  [Monitor SQL Server Components](https://learn.microsoft.com/sql/relational-databases/performance/monitor-sql-server-components)
- [sys.dm_tran_locks (Transact-SQL)](https://learn.microsoft.com/sql/relational-databases/system-dynamic-management-objects/sys-dm-tran-locks-transact-sql):
  잠금 요청 상태와 리소스 유형
- [Monitor performance by using the Query Store](https://learn.microsoft.com/sql/relational-databases/performance/monitoring-performance-by-using-the-query-store):
  SQL Server 2022 새 DB의 기본 `READ_WRITE` 모드
- [GRANT Server Permissions (Transact-SQL)](https://learn.microsoft.com/sql/t-sql/statements/grant-server-permissions-transact-sql),
  [sys.sql_logins (Transact-SQL)](https://learn.microsoft.com/sql/relational-databases/system-catalog-views/sys-sql-logins-transact-sql),
  [sys.dm_db_partition_stats (Transact-SQL)](https://learn.microsoft.com/sql/relational-databases/system-dynamic-management-objects/sys-dm-db-partition-stats-transact-sql):
  collector 로그인에 필요한 권한
- [sys.fn_xe_file_target_read_file (Transact-SQL)](https://learn.microsoft.com/sql/relational-databases/system-functions/sys-fn-xe-file-target-read-file-transact-sql),
  [SET QUOTED_IDENTIFIER (Transact-SQL)](https://learn.microsoft.com/sql/t-sql/statements/set-quoted-identifier-transact-sql):
  이벤트 파일 읽기와 XML 메서드 조건
- [Run scripts in your Windows VM by using managed Run Commands](https://learn.microsoft.com/azure/virtual-machines/windows/run-command-managed)
- [windows_exporter mssql collector](https://github.com/prometheus-community/windows_exporter/blob/master/docs/collector.mssql.md),
  [sql_exporter](https://github.com/burningalchemist/sql_exporter),
  [go-mssqldb](https://github.com/microsoft/go-mssqldb): 수집 클래스, Windows 서비스 등록,
  사용자 없는 DSN의 Windows SSO
- [Grafana Alloy `prometheus.exporter.mssql`](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.mssql/),
  [OpenTelemetry `sqlserverreceiver`](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/sqlserverreceiver),
  [postgres_exporter](https://github.com/prometheus-community/postgres_exporter): 잠금 관련 지표 비교
- [Prometheus configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/):
  `scrape_interval`, remote write `batch_send_deadline` 기본값 5초
