# Prepares the objects that the security and job checks read. Runs through a
# managed Run Command as the VM local administrator (sysadmin). With RunAs, a
# script failure is reported only as "Incorrect function" (exit code 1).
# - Extended Events session sre_login_audit: failed logins (error 18456) and
#   new (not pooled) successful logins in event files next to the error log.
# - Demo SQL logins: app_user (CHECK_POLICY = ON, so 10 bad passwords lock it
#   under the VM's default lockout policy) and legacy_report (disabled).
# - SQL Server Agent set to start automatically, with one failing and one
#   succeeding demo job.
$ErrorActionPreference = 'Stop'

function Invoke-Sql([string]$sql, [string]$database = 'master') {
    $connection = New-Object System.Data.SqlClient.SqlConnection "Server=localhost;Database=$database;Integrated Security=SSPI;Application Name=sre-lab-setup"
    try {
        $connection.Open()
        $command = $connection.CreateCommand()
        $command.CommandText = $sql
        [void]$command.ExecuteNonQuery()
    }
    finally { $connection.Dispose() }
}

# Recreated on every run so that definition changes apply. Pooled connection
# reuse (is_cached = 1) is excluded: it made up about 90% of login events
# (observed). The event_file target sits next to the SQL Server error log.
# A ring_buffer target returned truncated XML (truncated="1") that hid new events.
Invoke-Sql @"
DECLARE @dir nvarchar(4000) = CAST(SERVERPROPERTY('ErrorLogFileName') AS nvarchar(4000));
SET @dir = LEFT(@dir, LEN(@dir) - CHARINDEX(N'\', REVERSE(@dir)) + 1);
IF EXISTS (SELECT 1 FROM sys.server_event_sessions WHERE name = N'sre_login_audit')
    DROP EVENT SESSION [sre_login_audit] ON SERVER;
DECLARE @sql nvarchar(max) = N'CREATE EVENT SESSION [sre_login_audit] ON SERVER
ADD EVENT sqlserver.error_reported (
    ACTION (sqlserver.client_hostname, sqlserver.client_app_name)
    WHERE ([error_number] = (18456))),
ADD EVENT sqlserver.login (
    ACTION (sqlserver.server_principal_name, sqlserver.client_hostname, sqlserver.client_app_name)
    WHERE ([is_cached] = (0)))
ADD TARGET package0.event_file (SET filename = N''' + @dir + N'sre_login_audit.xel'', max_file_size = (10), max_rollover_files = (4))
WITH (MAX_DISPATCH_LATENCY = 5 SECONDS, STARTUP_STATE = ON);';
EXEC (@sql);
ALTER EVENT SESSION [sre_login_audit] ON SERVER STATE = START;
"@

# Demo logins. Their passwords are random and discarded: nobody signs in with them.
$appPassword = [guid]::NewGuid().ToString() + 'aA1!'
$legacyPassword = [guid]::NewGuid().ToString() + 'aA1!'
Invoke-Sql @"
IF SUSER_ID(N'app_user') IS NULL
    CREATE LOGIN [app_user] WITH PASSWORD = N'$appPassword', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF;
IF SUSER_ID(N'legacy_report') IS NULL
    CREATE LOGIN [legacy_report] WITH PASSWORD = N'$legacyPassword', CHECK_POLICY = ON;
ALTER LOGIN [legacy_report] DISABLE;
"@

Set-Service -Name SQLSERVERAGENT -StartupType Automatic
Start-Service -Name SQLSERVERAGENT

# Each part is checked separately so that a partly created job is completed on re-run.
function Add-DemoJob([string]$name, [string]$command, [string]$scheduleName, [int]$subdayType, [int]$subdayInterval) {
    Invoke-Sql @"
IF NOT EXISTS (SELECT 1 FROM dbo.sysjobs WHERE name = N'$name')
    EXEC dbo.sp_add_job @job_name = N'$name', @description = N'SRE lab demo job.';
IF NOT EXISTS (SELECT 1 FROM dbo.sysjobsteps AS s JOIN dbo.sysjobs AS j ON j.job_id = s.job_id WHERE j.name = N'$name')
    EXEC dbo.sp_add_jobstep @job_name = N'$name', @step_name = N'main', @subsystem = N'TSQL',
        @database_name = N'SreDemo', @command = N'$($command.Replace("'", "''"))';
IF NOT EXISTS (SELECT 1 FROM dbo.sysjobschedules AS s JOIN dbo.sysjobs AS j ON j.job_id = s.job_id WHERE j.name = N'$name')
    EXEC dbo.sp_add_jobschedule @job_name = N'$name', @name = N'$scheduleName',
        @freq_type = 4, @freq_interval = 1, @freq_subday_type = $subdayType, @freq_subday_interval = $subdayInterval;
IF NOT EXISTS (SELECT 1 FROM dbo.sysjobservers AS s JOIN dbo.sysjobs AS j ON j.job_id = s.job_id WHERE j.name = N'$name')
    EXEC dbo.sp_add_jobserver @job_name = N'$name';
"@ 'msdb'
}

# freq_subday_type 4 = minutes, 8 = hours.
Add-DemoJob 'sre-demo-nightly-check' "RAISERROR(N'Demo failure: 3 orphan orders found', 16, 1);" 'every 30 minutes' 4 30
Add-DemoJob 'sre-demo-update-stats' 'UPDATE STATISTICS dbo.Orders;' 'hourly' 8 1
Invoke-Sql @"
EXEC dbo.sp_start_job @job_name = N'sre-demo-nightly-check';
EXEC dbo.sp_start_job @job_name = N'sre-demo-update-stats';
"@ 'msdb'

Write-Output 'Login audit session, demo logins, and demo jobs are ready.'
