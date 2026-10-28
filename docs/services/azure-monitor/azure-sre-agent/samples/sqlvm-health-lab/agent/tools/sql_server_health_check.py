"""Read-only SQL Server health check for a SQL Server VM, invoked by Azure SRE Agent.

The agent runs in Azure VNet egress mode, so this tool connects to the SQL
Server private IP over TDS from the agent's delegated subnet. The password of
the least-privilege monitoring login is read from a Key Vault that is reachable
only through a private endpoint, using the agent's user-assigned managed identity.
"""

import datetime
import decimal
import time

import requests

try:
    from azure.identity import ManagedIdentityCredential
except ImportError:  # pragma: no cover - the SRE Agent sandbox provides azure-identity
    ManagedIdentityCredential = None

try:
    import pymssql
except ImportError:  # pragma: no cover - installed from the tool dependencies
    pymssql = None

SQL_HOST = "@@SQL_HOST@@"
SQL_PORT = "@@SQL_PORT@@"
SQL_LOGIN = "@@SQL_LOGIN@@"
KEY_VAULT_NAME = "@@KEY_VAULT_NAME@@"
SECRET_NAME = "@@SECRET_NAME@@"
AGENT_CLIENT_ID = "@@AGENT_CLIENT_ID@@"

KEY_VAULT_SCOPE = "https://vault.azure.net/.default"
LOGIN_TIMEOUT_SECONDS = 10
QUERY_TIMEOUT_SECONDS = 30

BENIGN_WAITS = (
    "BROKER_EVENTHANDLER", "BROKER_RECEIVE_WAITFOR", "BROKER_TASK_STOP", "BROKER_TO_FLUSH",
    "BROKER_TRANSMITTER", "CHECKPOINT_QUEUE", "CHKPT", "CLR_AUTO_EVENT", "CLR_MANUAL_EVENT",
    "CLR_SEMAPHORE", "DIRTY_PAGE_POLL", "DISPATCHER_QUEUE_SEMAPHORE", "EXECSYNC", "FSAGENT",
    "FT_IFTS_SCHEDULER_IDLE_WAIT", "FT_IFTSHC_MUTEX", "HADR_FILESTREAM_IOMGR_IOCOMPLETION",
    "HADR_LOGCAPTURE_WAIT", "HADR_NOTIFICATION_DEQUEUE", "HADR_TIMER_TASK", "HADR_WORK_QUEUE",
    "KSOURCE_WAKEUP", "LAZYWRITER_SLEEP", "LOGMGR_QUEUE", "MEMORY_ALLOCATION_EXT",
    "ONDEMAND_TASK_QUEUE", "PARALLEL_REDO_DRAIN_WORKER", "PARALLEL_REDO_LOG_CACHE",
    "PARALLEL_REDO_TRAN_LIST", "PARALLEL_REDO_WORKER_SYNC", "PARALLEL_REDO_WORKER_WAIT_WORK",
    "PREEMPTIVE_OS_FLUSHFILEBUFFERS", "PREEMPTIVE_XE_GETTARGETSTATE", "PVS_PREALLOCATE",
    "PWAIT_ALL_COMPONENTS_INITIALIZED", "PWAIT_DIRECTLOGCONSUMER_GETNEXT",
    "PWAIT_EXTENSIBILITY_CLEANUP_TASK", "QDS_PERSIST_TASK_MAIN_LOOP_SLEEP", "QDS_ASYNC_QUEUE",
    "QDS_CLEANUP_STALE_QUERIES_TASK_MAIN_LOOP_SLEEP", "QDS_SHUTDOWN_QUEUE",
    "REDO_THREAD_PENDING_WORK", "REQUEST_FOR_DEADLOCK_SEARCH", "RESOURCE_QUEUE",
    "SERVER_IDLE_CHECK", "SLEEP_BPOOL_FLUSH", "SLEEP_DBSTARTUP", "SLEEP_DCOMSTARTUP",
    "SLEEP_MASTERDBREADY", "SLEEP_MASTERMDREADY", "SLEEP_MASTERUPGRADED", "SLEEP_MSDBSTARTUP",
    "SLEEP_SYSTEMTASK", "SLEEP_TASK", "SLEEP_TEMPDBSTARTUP", "SNI_HTTP_ACCEPT",
    "SOS_WORK_DISPATCHER", "SP_SERVER_DIAGNOSTICS_SLEEP", "SQLTRACE_BUFFER_FLUSH",
    "SQLTRACE_INCREMENTAL_FLUSH_SLEEP", "SQLTRACE_WAIT_ENTRIES", "STARTUP_DEPENDENCY_MANAGER",
    "VDI_CLIENT_OTHER", "WAIT_FOR_RESULTS", "WAITFOR", "WAITFOR_TASKSHUTDOWN",
    "WAIT_XTP_HOST_WAIT", "WAIT_XTP_OFFLINE_CKPT_NEW_LOG", "WAIT_XTP_CKPT_CLOSE",
    "WAIT_XTP_RECOVERY", "XE_DISPATCHER_JOIN", "XE_DISPATCHER_WAIT", "XE_LIVE_TARGET_TVF",
    "XE_TIMER_EVENT", "SOS_WORKER_MIGRATION",
)
_BENIGN_WAIT_LIST = ",".join(f"N'{name}'" for name in BENIGN_WAITS)

QUERIES = {
    "overview": """
SELECT @@SERVERNAME AS server_name,
       CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(32)) AS version,
       CAST(SERVERPROPERTY('ProductUpdateLevel') AS nvarchar(16)) AS update_level,
       CAST(SERVERPROPERTY('Edition') AS nvarchar(64)) AS edition,
       si.sqlserver_start_time AS started_at,
       DATEDIFF(MINUTE, si.sqlserver_start_time, SYSDATETIME()) AS uptime_min,
       si.cpu_count, si.physical_memory_kb / 1024 AS os_memory_mb,
       si.committed_kb / 1024 AS committed_mb, si.committed_target_kb / 1024 AS target_mb,
       (SELECT CAST(value_in_use AS int) FROM sys.configurations WHERE name = 'max server memory (MB)') AS max_server_memory_mb,
       (SELECT CAST(value_in_use AS int) FROM sys.configurations WHERE name = 'max degree of parallelism') AS maxdop,
       (SELECT CAST(value_in_use AS int) FROM sys.configurations WHERE name = 'cost threshold for parallelism') AS cost_threshold,
       (SELECT COUNT(*) FROM sys.databases) AS database_count,
       (SELECT COUNT(*) FROM sys.dm_exec_sessions WHERE is_user_process = 1) AS user_sessions,
       (SELECT client_net_address FROM sys.dm_exec_connections WHERE session_id = @@SPID) AS tool_client_address,
       (SELECT encrypt_option FROM sys.dm_exec_connections WHERE session_id = @@SPID) AS tool_connection_encrypted
FROM sys.dm_os_sys_info AS si;
""",
    "batch_requests": """
SELECT cntr_value FROM sys.dm_os_performance_counters
WHERE object_name LIKE '%SQL Statistics%' AND counter_name = 'Batch Requests/sec';
""",
    "cpu": """
WITH rb AS (
    SELECT TOP (10) [timestamp], CONVERT(xml, record) AS record
    FROM sys.dm_os_ring_buffers
    WHERE ring_buffer_type = N'RING_BUFFER_SCHEDULER_MONITOR' AND record LIKE N'%<SystemHealth>%'
    ORDER BY [timestamp] DESC)
SELECT DATEADD(ms, -1 * ((SELECT ms_ticks FROM sys.dm_os_sys_info) - rb.[timestamp]), SYSDATETIME()) AS at,
       rb.record.value('(./Record/SchedulerMonitorEvent/SystemHealth/ProcessUtilization)[1]', 'int') AS sql_cpu_pct,
       100 - rb.record.value('(./Record/SchedulerMonitorEvent/SystemHealth/SystemIdle)[1]', 'int')
           - rb.record.value('(./Record/SchedulerMonitorEvent/SystemHealth/ProcessUtilization)[1]', 'int') AS other_cpu_pct
FROM rb ORDER BY at DESC;
""",
    "waits": f"""
SELECT TOP (10) wait_type, waiting_tasks_count AS tasks, wait_time_ms,
       signal_wait_time_ms AS signal_ms,
       CAST(100.0 * wait_time_ms / NULLIF(SUM(wait_time_ms) OVER (), 0) AS decimal(5, 2)) AS pct
FROM sys.dm_os_wait_stats
WHERE waiting_tasks_count > 0 AND wait_type NOT IN ({_BENIGN_WAIT_LIST})
ORDER BY wait_time_ms DESC;
""",
    "memory": """
SELECT RTRIM(counter_name) AS counter, cntr_value AS value
FROM sys.dm_os_performance_counters
WHERE (object_name LIKE '%Buffer Manager%' AND counter_name IN ('Page life expectancy', 'Lazy writes/sec', 'Page reads/sec'))
   OR (object_name LIKE '%Memory Manager%' AND counter_name IN ('Memory Grants Pending', 'Memory Grants Outstanding', 'Target Server Memory (KB)', 'Total Server Memory (KB)', 'Stolen Server Memory (KB)'))
UNION ALL
SELECT 'process_physical_memory_mb', physical_memory_in_use_kb / 1024 FROM sys.dm_os_process_memory
UNION ALL
SELECT 'process_memory_low', CAST(process_physical_memory_low AS bigint) FROM sys.dm_os_process_memory
UNION ALL
SELECT 'available_os_memory_mb', available_physical_memory_kb / 1024 FROM sys.dm_os_sys_memory;
""",
    "top_queries": """
SELECT TOP (5) DB_NAME(CONVERT(int, pa.value)) AS db,
       qs.execution_count AS execs,
       qs.total_worker_time / 1000 AS total_cpu_ms,
       qs.total_worker_time / qs.execution_count / 1000 AS avg_cpu_ms,
       qs.total_elapsed_time / qs.execution_count / 1000 AS avg_elapsed_ms,
       qs.total_logical_reads / qs.execution_count AS avg_reads,
       qs.last_execution_time AS last_run,
       LEFT(REPLACE(REPLACE(SUBSTRING(t.text, (qs.statement_start_offset / 2) + 1,
            ((CASE qs.statement_end_offset WHEN -1 THEN DATALENGTH(t.text) ELSE qs.statement_end_offset END
              - qs.statement_start_offset) / 2) + 1), CHAR(13), ' '), CHAR(10), ' '), 200) AS stmt
FROM sys.dm_exec_query_stats AS qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) AS t
CROSS APPLY sys.dm_exec_plan_attributes(qs.plan_handle) AS pa
WHERE pa.attribute = N'dbid' AND CONVERT(int, pa.value) > 4
ORDER BY qs.total_worker_time DESC;
""",
    "active_requests": """
SELECT TOP (20) r.session_id AS sid, r.blocking_session_id AS blocked_by, r.status, r.command,
       r.wait_type, r.wait_time AS wait_ms, r.wait_resource, r.cpu_time AS cpu_ms,
       r.total_elapsed_time AS elapsed_ms, DB_NAME(r.database_id) AS db, s.program_name AS program,
       s.open_transaction_count AS open_tran,
       LEFT(REPLACE(REPLACE(t.text, CHAR(13), ' '), CHAR(10), ' '), 200) AS stmt
FROM sys.dm_exec_requests AS r
JOIN sys.dm_exec_sessions AS s ON s.session_id = r.session_id
OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) AS t
WHERE s.is_user_process = 1 AND r.session_id <> @@SPID
ORDER BY r.total_elapsed_time DESC;
""",
    # File sizes come from performance counters so that VIEW SERVER STATE is enough
    # (sys.master_files would also require VIEW ANY DEFINITION).
    "databases": """
WITH pc AS (
    SELECT RTRIM(instance_name) AS db, RTRIM(counter_name) AS counter, cntr_value
    FROM sys.dm_os_performance_counters
    WHERE object_name LIKE '%:Databases%'
      AND counter_name IN ('Data File(s) Size (KB)', 'Log File(s) Size (KB)', 'Percent Log Used'))
SELECT d.name, d.state_desc AS state, d.recovery_model_desc AS recovery, d.log_reuse_wait_desc AS log_reuse_wait,
       CAST(MAX(CASE WHEN pc.counter = 'Data File(s) Size (KB)' THEN pc.cntr_value END) / 1024.0 AS decimal(12, 1)) AS data_mb,
       CAST(MAX(CASE WHEN pc.counter = 'Log File(s) Size (KB)' THEN pc.cntr_value END) / 1024.0 AS decimal(12, 1)) AS log_mb,
       MAX(CASE WHEN pc.counter = 'Percent Log Used' THEN pc.cntr_value END) AS log_used_pct
FROM sys.databases AS d
LEFT JOIN pc ON pc.db = d.name
GROUP BY d.name, d.state_desc, d.recovery_model_desc, d.log_reuse_wait_desc
ORDER BY d.name;
""",
    "backups": """
SELECT d.name, d.recovery_model_desc AS recovery,
       (SELECT MAX(b.backup_finish_date) FROM msdb.dbo.backupset AS b WHERE b.database_name = d.name AND b.type = 'D') AS last_full_backup,
       (SELECT MAX(b.backup_finish_date) FROM msdb.dbo.backupset AS b WHERE b.database_name = d.name AND b.type = 'L') AS last_log_backup
FROM sys.databases AS d WHERE d.name <> 'tempdb' ORDER BY d.name;
""",
    "io": """
SELECT TOP (10) DB_NAME(vfs.database_id) AS db, vfs.file_id,
       vfs.num_of_reads AS reads, vfs.num_of_writes AS writes,
       CAST(vfs.io_stall_read_ms * 1.0 / NULLIF(vfs.num_of_reads, 0) AS decimal(10, 2)) AS avg_read_ms,
       CAST(vfs.io_stall_write_ms * 1.0 / NULLIF(vfs.num_of_writes, 0) AS decimal(10, 2)) AS avg_write_ms
FROM sys.dm_io_virtual_file_stats(NULL, NULL) AS vfs
ORDER BY vfs.io_stall_read_ms + vfs.io_stall_write_ms DESC;
""",
    "missing_indexes": """
SELECT TOP (5) DB_NAME(mid.database_id) AS db, mid.statement AS table_name,
       mid.equality_columns AS equality, mid.inequality_columns AS inequality, mid.included_columns AS included,
       migs.user_seeks + migs.user_scans AS uses,
       CAST(migs.avg_user_impact AS decimal(5, 1)) AS impact_pct,
       CAST(migs.avg_total_user_cost * migs.avg_user_impact * (migs.user_seeks + migs.user_scans) AS decimal(18, 1)) AS score
FROM sys.dm_db_missing_index_details AS mid
JOIN sys.dm_db_missing_index_groups AS mig ON mig.index_handle = mid.index_handle
JOIN sys.dm_db_missing_index_group_stats AS migs ON migs.group_handle = mig.index_group_handle
ORDER BY score DESC;
""",
}

OPERATIONS = (
    "summary",
    "overview",
    "cpu",
    "waits",
    "memory",
    "top_queries",
    "active_requests",
    "databases",
    "backups",
    "io",
    "missing_indexes",
)
BASE_OPERATIONS = OPERATIONS

# Sections returned by `summary` and the number of rows kept for each.
SUMMARY_SECTIONS = (
    ("cpu", 5),
    ("waits", 5),
    ("memory", None),
    ("active_requests", 5),
    ("databases", None),
    ("backups", None),
    ("top_queries", 3),
    ("missing_indexes", 3),
)


def validate_operation(operation):
    if operation not in ALL_OPERATIONS:
        raise ValueError("operation must be one of: " + ", ".join(ALL_OPERATIONS))
    return operation


def to_json_value(value):
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


def _rows(cursor, sql):
    cursor.execute(sql)
    columns = [column[0] for column in cursor.description]
    return [{name: to_json_value(value) for name, value in zip(columns, row)} for row in cursor.fetchall()]


def summarize_requests(rows):
    """Add blocking counts and head blockers (sessions that block others but are not blocked)."""
    blocked_by = {row["sid"]: row.get("blocked_by") or 0 for row in rows}
    blockers = sorted({value for value in blocked_by.values() if value > 0})
    return {
        "count": len(rows),
        "blocked": sum(1 for value in blocked_by.values() if value > 0),
        "head_blockers": [sid for sid in blockers if blocked_by.get(sid, 0) == 0],
        "top": rows,
    }


def _password(credential=None):
    if credential is None:
        if ManagedIdentityCredential is None:
            raise RuntimeError("azure-identity is not installed")
        credential = ManagedIdentityCredential(client_id=AGENT_CLIENT_ID)
    token = credential.get_token(KEY_VAULT_SCOPE).token
    response = requests.get(
        f"https://{KEY_VAULT_NAME}.vault.azure.net/secrets/{SECRET_NAME}?api-version=7.4",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["value"]


def _connect(password):
    if pymssql is None:
        raise RuntimeError("pymssql is not installed")
    # The VNet keeps traffic private; TLS is still required so credentials and
    # results are never sent in clear text inside the network.
    return pymssql.connect(
        server=SQL_HOST,
        port=int(SQL_PORT),
        user=SQL_LOGIN,
        password=password,
        database="master",
        login_timeout=LOGIN_TIMEOUT_SECONDS,
        timeout=QUERY_TIMEOUT_SECONDS,
        appname="sre-agent-health-check",
        tds_version="7.4",
        encryption="require",
        read_only=True,
    )


def collect(cursor, operation):
    result = {}
    errors = {}

    def section(name, func):
        try:
            result[name] = func()
        except Exception as exc:  # keep other sections when one query fails
            errors[name] = f"{type(exc).__name__}: {str(exc)[:200]}"

    cursor.execute("SET LOCK_TIMEOUT 2000; SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;")
    if operation in EXTRA_OPERATIONS:
        section(operation, lambda: collect_extra(cursor, operation))
        if errors:
            result["section_errors"] = errors
        return result
    if operation in ("summary", "overview"):
        section("overview", lambda: _rows(cursor, QUERIES["overview"])[0])

        def batch_rate():
            first = _rows(cursor, QUERIES["batch_requests"])[0]["cntr_value"]
            time.sleep(2)
            second = _rows(cursor, QUERIES["batch_requests"])[0]["cntr_value"]
            return round((second - first) / 2.0, 1)

        section("batch_requests_per_sec", batch_rate)
    if operation == "summary":
        for name, limit in SUMMARY_SECTIONS:
            def run(name=name, limit=limit):
                rows = _rows(cursor, QUERIES[name])
                if name == "memory":
                    return {row["counter"]: row["value"] for row in rows}
                if name == "active_requests":
                    summary = summarize_requests(rows)
                    summary["top"] = rows[:limit]
                    return summary
                return rows[:limit] if limit else rows
            section(name, run)
    elif operation != "overview":
        if operation == "active_requests":
            section(operation, lambda: summarize_requests(_rows(cursor, QUERIES[operation])))
        else:
            section(operation, lambda: _rows(cursor, QUERIES[operation]))
    if errors:
        result["section_errors"] = errors
    return result


# ── Operational checks beyond the health summary ─────────────────────────────
# Each handler runs fixed, read-only statements. Per-database statements run
# through <db>.sys.sp_executesql (CONNECT ANY DATABASE), so the connection never
# switches database. Times from Query Store and Extended Events are UTC.

LONG_RUNNING_SECONDS = 30
SLOW_AVG_MS = 500
REGRESSION_RATIO = 2.0

EXTRA_QUERIES = {
    "long_running": """
SELECT TOP (20) r.session_id AS sid, r.blocking_session_id AS blocked_by, r.status, r.command,
       DB_NAME(r.database_id) AS db, s.login_name AS login, s.host_name AS host, s.program_name AS program,
       r.start_time, r.total_elapsed_time / 1000 AS elapsed_s, r.cpu_time / 1000 AS cpu_s,
       r.logical_reads, r.wait_type, r.wait_time AS wait_ms, s.open_transaction_count AS open_tran,
       CONVERT(varchar(20), r.query_hash, 1) AS query_hash,
       LEFT(REPLACE(REPLACE(SUBSTRING(t.text, (r.statement_start_offset / 2) + 1,
            ((CASE r.statement_end_offset WHEN -1 THEN DATALENGTH(t.text) ELSE r.statement_end_offset END
              - r.statement_start_offset) / 2) + 1), CHAR(13), ' '), CHAR(10), ' '), 300) AS stmt
FROM sys.dm_exec_requests AS r
JOIN sys.dm_exec_sessions AS s ON s.session_id = r.session_id
OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) AS t
WHERE s.is_user_process = 1 AND r.session_id <> @@SPID
  AND r.total_elapsed_time >= {threshold_ms} AND ISNULL(r.wait_type, '') <> 'XE_LIVE_TARGET_TVF'
ORDER BY r.total_elapsed_time DESC;
""",
    "lock_summary": """
SELECT DB_NAME(resource_database_id) AS db, resource_type, request_mode AS mode,
       request_status AS status, COUNT(*) AS locks
FROM sys.dm_tran_locks
WHERE request_session_id <> @@SPID AND NOT (resource_type = 'DATABASE' AND request_status = 'GRANT')
GROUP BY resource_database_id, resource_type, request_mode, request_status
ORDER BY COUNT(*) DESC;
""",
    "lock_waits": """
SELECT TOP (50) l.request_session_id AS sid, DB_NAME(l.resource_database_id) AS db,
       l.resource_database_id AS db_id, l.resource_type, l.request_mode AS mode,
       l.resource_description, l.resource_associated_entity_id AS entity_id,
       w.blocking_session_id AS blocked_by, w.wait_duration_ms AS wait_ms, w.wait_type
FROM sys.dm_tran_locks AS l
LEFT JOIN sys.dm_os_waiting_tasks AS w ON w.resource_address = l.lock_owner_address
WHERE l.request_status IN ('WAIT', 'CONVERT')
ORDER BY w.wait_duration_ms DESC;
""",
    # Table-level locks held by each session; finer KEY/PAGE/RID locks are counted per table.
    "held_table_locks": """
SELECT TOP (50) l.request_session_id AS sid, s.login_name AS login, s.program_name AS program,
       s.status AS session_status, s.open_transaction_count AS open_tran,
       DB_NAME(l.resource_database_id) AS db,
       OBJECT_SCHEMA_NAME(l.resource_associated_entity_id, l.resource_database_id) + N'.'
           + OBJECT_NAME(l.resource_associated_entity_id, l.resource_database_id) AS [object],
       l.request_mode AS mode,
       (SELECT COUNT(*) FROM sys.dm_tran_locks AS f
        WHERE f.request_session_id = l.request_session_id AND f.resource_database_id = l.resource_database_id
          AND f.resource_type IN ('KEY', 'PAGE', 'RID') AND f.request_status = 'GRANT') AS row_page_locks_in_db
FROM sys.dm_tran_locks AS l
JOIN sys.dm_exec_sessions AS s ON s.session_id = l.request_session_id
WHERE l.resource_type = 'OBJECT' AND l.request_status = 'GRANT' AND l.request_mode <> 'Sch-S'
  AND l.resource_database_id > 4 AND l.request_session_id <> @@SPID
ORDER BY CASE WHEN l.request_mode IN ('X', 'IX', 'SIX', 'U', 'Sch-M') THEN 0 ELSE 1 END, l.request_session_id;
""",
    "blocking_sessions": """
WITH chain AS (
    SELECT session_id, blocking_session_id FROM sys.dm_exec_requests WHERE blocking_session_id > 0)
SELECT s.session_id AS sid, r.blocking_session_id AS blocked_by, s.status, s.login_name AS login,
       s.host_name AS host, s.program_name AS program, s.open_transaction_count AS open_tran,
       s.last_request_start_time, s.last_request_end_time, r.wait_type, r.wait_time AS wait_ms,
       r.wait_resource,
       LEFT(REPLACE(REPLACE(COALESCE(rt.text, ct.text), CHAR(13), ' '), CHAR(10), ' '), 300) AS last_sql
FROM sys.dm_exec_sessions AS s
LEFT JOIN sys.dm_exec_requests AS r ON r.session_id = s.session_id
LEFT JOIN sys.dm_exec_connections AS c ON c.session_id = s.session_id
OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) AS rt
OUTER APPLY sys.dm_exec_sql_text(c.most_recent_sql_handle) AS ct
WHERE s.session_id IN (SELECT session_id FROM chain UNION SELECT blocking_session_id FROM chain)
ORDER BY r.blocking_session_id, s.session_id;
""",
    "sql_logins": """
SELECT name AS login, is_disabled AS disabled, is_policy_checked AS check_policy,
       is_expiration_checked AS check_expiration,
       CAST(LOGINPROPERTY(name, 'IsLocked') AS int) AS locked,
       CAST(LOGINPROPERTY(name, 'IsExpired') AS int) AS expired,
       CAST(LOGINPROPERTY(name, 'IsMustChange') AS int) AS must_change,
       CAST(LOGINPROPERTY(name, 'BadPasswordCount') AS int) AS bad_password_count,
       CAST(LOGINPROPERTY(name, 'BadPasswordTime') AS datetime) AS last_bad_password,
       CAST(LOGINPROPERTY(name, 'LockoutTime') AS datetime) AS lockout_time,
       CAST(LOGINPROPERTY(name, 'PasswordLastSetTime') AS datetime) AS password_last_set,
       CAST(LOGINPROPERTY(name, 'DaysUntilExpiration') AS int) AS days_until_expiration
FROM sys.sql_logins
WHERE name NOT LIKE N'##%'
ORDER BY name;
""",
    "sysadmins": """
SELECT p.name AS login, p.type_desc AS login_type, p.is_disabled AS disabled
FROM sys.server_role_members AS m
JOIN sys.server_principals AS r ON r.principal_id = m.role_principal_id
JOIN sys.server_principals AS p ON p.principal_id = m.member_principal_id
WHERE r.name = N'sysadmin';
""",
    # Events come from the sre_login_audit event files in the default log folder
    # (a relative file name). A ring_buffer target returned truncated XML that
    # hid new events (observed). XML data type methods require QUOTED_IDENTIFIER
    # ON (error 1934 otherwise). Comparing timestamp_utc directly in WHERE
    # returned no rows on SQL Server 2022 (observed); the CAST follows the
    # documented example.
    "login_events": """
SET NOCOUNT ON;
SET QUOTED_IDENTIFIER ON;
SELECT f.object_name AS event, CAST(f.timestamp_utc AS datetime2(0)) AS ts_utc, CAST(f.event_data AS xml) AS x
INTO #raw
FROM sys.fn_xe_file_target_read_file(N'sre_login_audit*.xel', NULL, NULL, NULL) AS f
WHERE CAST(f.timestamp_utc AS datetime2(7)) > DATEADD(HOUR, -24, SYSUTCDATETIME());
SELECT event, ts_utc,
       x.value('(event/data[@name="state"]/value)[1]', 'int') AS state,
       x.value('(event/data[@name="message"]/value)[1]', 'nvarchar(400)') AS message,
       x.value('(event/action[@name="server_principal_name"]/value)[1]', 'nvarchar(128)') AS login,
       x.value('(event/action[@name="client_hostname"]/value)[1]', 'nvarchar(128)') AS host,
       x.value('(event/action[@name="client_app_name"]/value)[1]', 'nvarchar(128)') AS app
FROM #raw;
""",
    "volumes": """
SELECT DISTINCT vs.volume_mount_point AS volume, vs.logical_volume_name AS label,
       vs.total_bytes / 1048576 AS total_mb, vs.available_bytes / 1048576 AS available_mb,
       CAST(100.0 * (vs.total_bytes - vs.available_bytes) / vs.total_bytes AS decimal(5, 1)) AS used_pct
FROM sys.master_files AS mf
CROSS APPLY sys.dm_os_volume_stats(mf.database_id, mf.file_id) AS vs;
""",
    "agent": """
SELECT servicename, status_desc, startup_type_desc FROM sys.dm_server_services
WHERE servicename LIKE N'SQL Server Agent%';
""",
    "jobs": """
WITH runs AS (
    SELECT h.job_id, h.run_status, h.run_date, h.run_duration, h.message,
           DATEADD(SECOND, h.run_time / 10000 * 3600 + h.run_time / 100 % 100 * 60 + h.run_time % 100,
                   CONVERT(datetime2(0), CAST(h.run_date AS char(8)), 112)) AS started,
           ROW_NUMBER() OVER (PARTITION BY h.job_id ORDER BY h.instance_id DESC) AS rn
    FROM msdb.dbo.sysjobhistory AS h WHERE h.step_id = 0)
SELECT j.name AS job, j.enabled,
       CASE last.run_status WHEN 0 THEN 'failed' WHEN 1 THEN 'succeeded' WHEN 2 THEN 'retry'
            WHEN 3 THEN 'canceled' WHEN 4 THEN 'in progress' ELSE 'never run' END AS last_outcome,
       last.started AS last_run, last.run_duration AS last_duration_hhmmss,
       (SELECT COUNT(*) FROM runs AS f WHERE f.job_id = j.job_id AND f.run_status = 0
          AND f.run_date = CAST(CONVERT(char(8), GETDATE(), 112) AS int)) AS failures_today
FROM msdb.dbo.sysjobs AS j
LEFT JOIN runs AS last ON last.job_id = j.job_id AND last.rn = 1
ORDER BY j.name;
""",
    "job_failures_today": """
SELECT TOP (20) j.name AS job, h.step_id, h.step_name,
       DATEADD(SECOND, h.run_time / 10000 * 3600 + h.run_time / 100 % 100 * 60 + h.run_time % 100,
               CONVERT(datetime2(0), CAST(h.run_date AS char(8)), 112)) AS started,
       LEFT(h.message, 300) AS message
FROM msdb.dbo.sysjobhistory AS h
JOIN msdb.dbo.sysjobs AS j ON j.job_id = h.job_id
WHERE h.run_status = 0 AND h.step_id > 0
  AND h.run_date = CAST(CONVERT(char(8), GETDATE(), 112) AS int)
ORDER BY h.instance_id DESC;
""",
}

# Statements that run inside each database through sp_executesql.
PER_DB_QUERIES = {
    "query_store_today": """
SELECT TOP (15) CONVERT(varchar(20), q.query_hash, 1) AS query_hash,
       COUNT(DISTINCT q.query_id) AS query_variants, COUNT(DISTINCT p.plan_id) AS plans,
       SUM(rs.count_executions) AS executions,
       CAST(SUM(rs.avg_duration * rs.count_executions) / 1e3 AS decimal(18, 1)) AS total_ms,
       CAST(SUM(rs.avg_duration * rs.count_executions) / NULLIF(SUM(rs.count_executions), 0) / 1e3 AS decimal(18, 1)) AS avg_ms,
       CAST(MAX(rs.max_duration) / 1e3 AS decimal(18, 1)) AS max_ms,
       CAST(SUM(rs.avg_cpu_time * rs.count_executions) / NULLIF(SUM(rs.count_executions), 0) / 1e3 AS decimal(18, 1)) AS avg_cpu_ms,
       CAST(SUM(rs.avg_logical_io_reads * rs.count_executions) / NULLIF(SUM(rs.count_executions), 0) AS decimal(18, 0)) AS avg_reads,
       MAX(rs.last_execution_time) AS last_execution_utc,
       LEFT(REPLACE(REPLACE(MIN(CAST(qt.query_sql_text AS nvarchar(400))), NCHAR(13), N' '), NCHAR(10), N' '), 300) AS query_text
FROM sys.query_store_runtime_stats AS rs
JOIN sys.query_store_runtime_stats_interval AS i ON i.runtime_stats_interval_id = rs.runtime_stats_interval_id
JOIN sys.query_store_plan AS p ON p.plan_id = rs.plan_id
JOIN sys.query_store_query AS q ON q.query_id = p.query_id
JOIN sys.query_store_query_text AS qt ON qt.query_text_id = q.query_text_id
WHERE i.end_time > @today
  -- Exclude the monitoring queries themselves (the exporter and this tool).
  AND qt.query_sql_text NOT LIKE N'%query_store_runtime_stats%'
  AND qt.query_sql_text NOT LIKE N'%dm_db_partition_stats%'
  AND qt.query_sql_text NOT LIKE N'%sys.database_files%'
GROUP BY q.query_hash
ORDER BY SUM(rs.avg_duration * rs.count_executions) DESC;
""",
    "query_store_slow": """
WITH today AS (
    SELECT q.query_hash,
           SUM(rs.count_executions) AS executions,
           SUM(rs.avg_duration * rs.count_executions) / NULLIF(SUM(rs.count_executions), 0) / 1e3 AS avg_ms,
           MAX(rs.max_duration) / 1e3 AS max_ms,
           MIN(CAST(qt.query_sql_text AS nvarchar(400))) AS query_text
    FROM sys.query_store_runtime_stats AS rs
    JOIN sys.query_store_runtime_stats_interval AS i ON i.runtime_stats_interval_id = rs.runtime_stats_interval_id
    JOIN sys.query_store_plan AS p ON p.plan_id = rs.plan_id
    JOIN sys.query_store_query AS q ON q.query_id = p.query_id
    JOIN sys.query_store_query_text AS qt ON qt.query_text_id = q.query_text_id
    WHERE i.end_time > @today
      -- Exclude the monitoring queries themselves (the exporter and this tool).
      AND qt.query_sql_text NOT LIKE N'%query_store_runtime_stats%'
      AND qt.query_sql_text NOT LIKE N'%dm_db_partition_stats%'
      AND qt.query_sql_text NOT LIKE N'%sys.database_files%'
    GROUP BY q.query_hash),
baseline AS (
    SELECT q.query_hash,
           SUM(rs.avg_duration * rs.count_executions) / NULLIF(SUM(rs.count_executions), 0) / 1e3 AS avg_ms_7d
    FROM sys.query_store_runtime_stats AS rs
    JOIN sys.query_store_runtime_stats_interval AS i ON i.runtime_stats_interval_id = rs.runtime_stats_interval_id
    JOIN sys.query_store_plan AS p ON p.plan_id = rs.plan_id
    JOIN sys.query_store_query AS q ON q.query_id = p.query_id
    WHERE i.start_time >= DATEADD(DAY, -7, @today) AND i.end_time <= @today
    GROUP BY q.query_hash)
SELECT TOP (15) CONVERT(varchar(20), t.query_hash, 1) AS query_hash, t.executions,
       CAST(t.avg_ms AS decimal(18, 1)) AS avg_ms, CAST(t.max_ms AS decimal(18, 1)) AS max_ms,
       CAST(b.avg_ms_7d AS decimal(18, 1)) AS baseline_avg_ms_7d,
       CAST(t.avg_ms / NULLIF(b.avg_ms_7d, 0) AS decimal(10, 2)) AS ratio_vs_7d,
       LEFT(REPLACE(REPLACE(t.query_text, NCHAR(13), N' '), NCHAR(10), N' '), 300) AS query_text
FROM today AS t
LEFT JOIN baseline AS b ON b.query_hash = t.query_hash
WHERE t.avg_ms >= @slow_ms OR t.avg_ms >= @ratio * b.avg_ms_7d
ORDER BY t.avg_ms DESC;
""",
    "files": """
SELECT name AS [file], type_desc AS file_type, physical_name,
       CAST(size / 128.0 AS decimal(18, 1)) AS size_mb,
       CAST(FILEPROPERTY(name, 'SpaceUsed') / 128.0 AS decimal(18, 1)) AS used_mb,
       CAST(100.0 * FILEPROPERTY(name, 'SpaceUsed') / NULLIF(size, 0) AS decimal(5, 1)) AS used_pct,
       CASE WHEN max_size = -1 THEN NULL ELSE CAST(max_size / 128.0 AS decimal(18, 1)) END AS max_mb,
       CASE WHEN is_percent_growth = 1 THEN CONCAT(growth, '%')
            ELSE CONCAT(CAST(growth / 128.0 AS decimal(18, 1)), ' MB') END AS autogrowth
FROM sys.database_files;
""",
    "tables": """
SELECT TOP (20) s.name AS [schema], t.name AS [table],
       SUM(CASE WHEN ps.index_id IN (0, 1) THEN ps.row_count ELSE 0 END) AS row_count,
       CAST(SUM(ps.reserved_page_count) / 128.0 AS decimal(18, 1)) AS reserved_mb,
       CAST(SUM(CASE WHEN ps.index_id IN (0, 1) THEN ps.used_page_count ELSE 0 END) / 128.0 AS decimal(18, 1)) AS data_mb
FROM sys.dm_db_partition_stats AS ps
JOIN sys.tables AS t ON t.object_id = ps.object_id
JOIN sys.schemas AS s ON s.schema_id = t.schema_id
WHERE t.is_ms_shipped = 0
GROUP BY s.name, t.name
ORDER BY row_count DESC;
""",
    "hobt_object": """
SELECT TOP (1) OBJECT_SCHEMA_NAME(object_id) + N'.' + OBJECT_NAME(object_id) AS object_name
FROM sys.partitions WHERE hobt_id = @hobt_id;
""",
}

EXTRA_OPERATIONS = (
    "long_running",
    "locks",
    "today_queries",
    "slow_queries",
    "security",
    "login_attempts",
    "storage",
    "table_growth",
    "jobs",
)
ALL_OPERATIONS = BASE_OPERATIONS + EXTRA_OPERATIONS


def quote_name(name):
    return "[" + name.replace("]", "]]") + "]"


def _databases(cursor, query_store=False, user_only=True):
    sql = "SELECT name FROM sys.databases WHERE state = 0"
    if user_only:
        sql += " AND database_id > 4"
    if query_store:
        sql += " AND is_query_store_on = 1"
    cursor.execute(sql + " ORDER BY name")
    return [row[0] for row in cursor.fetchall()]


def _rows_in_db(cursor, db, sql, param_definition=None, params=()):
    """Run a fixed statement inside one database with <db>.sys.sp_executesql."""
    statement = f"EXEC {quote_name(db)}.sys.sp_executesql %s"
    args = [sql]
    if param_definition:
        statement += ", %s, " + ", ".join(f"@{name} = %s" for name, _ in params)
        args += [param_definition] + [value for _, value in params]
    cursor.execute(statement, tuple(args))
    columns = [column[0] for column in cursor.description]
    return [{name: to_json_value(value) for name, value in zip(columns, row)} for row in cursor.fetchall()]


def _today_utc():
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def parse_failed_login(message):
    """Extract login, client address, and reason from an error 18456 message."""
    message = message or ""
    login = client = reason = "unknown"
    if "user '" in message:
        login = message.split("user '", 1)[1].split("'", 1)[0]
    if "[CLIENT: " in message:
        client = message.split("[CLIENT: ", 1)[1].split("]", 1)[0]
    if "Reason: " in message:
        reason = message.split("Reason: ", 1)[1].split(".", 1)[0]
    return login, client, reason


def compact(rows):
    """Drop empty values so that large results stay within the agent's tool output budget."""
    return [{k: v for k, v in row.items() if v not in (None, "", 0) or k in ("locked", "disabled")} for row in rows]


def summarize_login_events(events):
    failed, succeeded = {}, {}
    recent_failures = []
    for event in events:
        if event["event"] == "error_reported":
            # Each failure raises error 18456 twice: the error log copy with
            # [CLIENT: ...] and a generic copy for the client. Count the first.
            if "[CLIENT: " not in (event.get("message") or ""):
                continue
            login, client, reason = parse_failed_login(event.get("message"))
            key = (login, client, reason)
            failed[key] = failed.get(key, 0) + 1
            recent_failures.append({"ts_utc": event["ts_utc"], "login": login, "client": client,
                                    "reason": reason, "state": event.get("state")})
        elif event["event"] == "login":
            key = (event.get("login") or "unknown", event.get("host") or "", event.get("app") or "")
            succeeded[key] = succeeded.get(key, 0) + 1
    recent_failures.sort(key=lambda item: item["ts_utc"] or "", reverse=True)
    return {
        "window": "last 24 hours of failed logins and new (not pooled) logins (event files keep up to 4 x 10 MB)",
        "failed_by_login_client_reason": [
            {"login": k[0], "client": k[1], "reason": k[2], "attempts": v}
            for k, v in sorted(failed.items(), key=lambda item: -item[1])],
        "succeeded_by_login_host_app": [
            {"login": k[0], "host": k[1], "app": k[2], "logins": v}
            for k, v in sorted(succeeded.items(), key=lambda item: -item[1])[:10]],
        "recent_failures": recent_failures[:10],
    }


def _locks(cursor):
    waits = _rows(cursor, EXTRA_QUERIES["lock_waits"])
    cache = {}
    for wait in waits:
        if wait["resource_type"] == "OBJECT":
            cursor.execute("SELECT OBJECT_SCHEMA_NAME(%s, %s) + N'.' + OBJECT_NAME(%s, %s)",
                           (wait["entity_id"], wait["db_id"], wait["entity_id"], wait["db_id"]))
            wait["object"] = cursor.fetchone()[0]
        elif wait["resource_type"] in ("KEY", "PAGE", "RID", "HOBT") and wait["db"]:
            key = (wait["db"], wait["entity_id"])
            if key not in cache:
                rows = _rows_in_db(cursor, wait["db"], PER_DB_QUERIES["hobt_object"],
                                   "@hobt_id bigint", [("hobt_id", wait["entity_id"])])
                cache[key] = rows[0]["object_name"] if rows else None
            wait["object"] = cache[key]
    sessions = _rows(cursor, EXTRA_QUERIES["blocking_sessions"])
    return {
        "summary": _rows(cursor, EXTRA_QUERIES["lock_summary"]),
        "held_table_locks": compact(_rows(cursor, EXTRA_QUERIES["held_table_locks"])),
        "waiting_locks": waits,
        "blocking_sessions": sessions,
        "head_blockers": [s["sid"] for s in sessions if not s.get("blocked_by")],
    }


def _per_db(cursor, key, query_store=False, user_only=True, with_today=False, extra_params=()):
    results, errors = {}, {}
    for db in _databases(cursor, query_store=query_store, user_only=user_only):
        try:
            if with_today or extra_params:
                params = ([("today", _today_utc())] if with_today else []) + list(extra_params)
                definition = ", ".join(
                    {"today": "@today datetimeoffset", "slow_ms": "@slow_ms float", "ratio": "@ratio float"}[name]
                    for name, _ in params)
                results[db] = _rows_in_db(cursor, db, PER_DB_QUERIES[key], definition, params)
            else:
                results[db] = _rows_in_db(cursor, db, PER_DB_QUERIES[key])
        except Exception as exc:
            errors[db] = f"{type(exc).__name__}: {str(exc)[:160]}"
    if errors:
        results["errors"] = errors
    return results


def collect_extra(cursor, operation):
    if operation == "long_running":
        rows = _rows(cursor, EXTRA_QUERIES["long_running"].replace("{threshold_ms}", str(LONG_RUNNING_SECONDS * 1000)))
        return {"threshold_seconds": LONG_RUNNING_SECONDS, "requests": rows}
    if operation == "locks":
        return _locks(cursor)
    if operation == "today_queries":
        return {"since_utc": _today_utc(), "group_by": "query_hash",
                "databases": _per_db(cursor, "query_store_today", query_store=True, with_today=True)}
    if operation == "slow_queries":
        return {"since_utc": _today_utc(), "criteria": f"avg >= {SLOW_AVG_MS} ms or >= {REGRESSION_RATIO}x the previous 7-day average",
                "databases": _per_db(cursor, "query_store_slow", query_store=True, with_today=True,
                                     extra_params=[("slow_ms", float(SLOW_AVG_MS)), ("ratio", REGRESSION_RATIO)])}
    if operation == "security":
        logins = _rows(cursor, EXTRA_QUERIES["sql_logins"])
        attempts = summarize_login_events(_rows(cursor, EXTRA_QUERIES["login_events"]))
        # Findings first: the agent's tool output can be cut off when it is long (observed).
        return {
            "locked": [l["login"] for l in logins if l.get("locked")],
            "disabled": [l["login"] for l in logins if l.get("disabled")],
            "expired_or_must_change": [l["login"] for l in logins if l.get("expired") or l.get("must_change")],
            "failed_logins_24h": attempts["failed_by_login_client_reason"],
            "sql_logins": compact(logins),
            "sysadmin_members": compact(_rows(cursor, EXTRA_QUERIES["sysadmins"])),
            "successful_logins_24h_top10": attempts["succeeded_by_login_host_app"],
        }
    if operation == "login_attempts":
        return summarize_login_events(_rows(cursor, EXTRA_QUERIES["login_events"]))
    if operation == "storage":
        return {"volumes": _rows(cursor, EXTRA_QUERIES["volumes"]),
                "database_files": _per_db(cursor, "files", user_only=False)}
    if operation == "table_growth":
        return {"tables": _per_db(cursor, "tables"),
                "growth": "Row growth is in the mssql_table_rows time series. Call SqlServerMetricsQuery with "
                          "delta(mssql_table_rows[1h]) or delta(mssql_table_rows[24h])."}
    if operation == "jobs":
        return {"agent": _rows(cursor, EXTRA_QUERIES["agent"]), "jobs": _rows(cursor, EXTRA_QUERIES["jobs"]),
                "failures_today": _rows(cursor, EXTRA_QUERIES["job_failures_today"])}
    raise ValueError(operation)


def main(operation: str = "summary") -> dict:
    started = time.time()
    try:
        validate_operation(operation)
        connection = _connect(_password())
        try:
            data = collect(connection.cursor(), operation)
        finally:
            connection.close()
        data["collected_at_utc"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "success": "section_errors" not in data,
            "operation": operation,
            "sql_server": f"{SQL_HOST}:{SQL_PORT}",
            "duration_seconds": round(time.time() - started, 1),
            "data": data,
        }
    except Exception as exc:  # return a structured error to the agent instead of raising
        return {
            "success": False,
            "operation": operation,
            "sql_server": f"{SQL_HOST}:{SQL_PORT}",
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }
