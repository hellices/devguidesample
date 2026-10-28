# Creates the SQL Server login for the sql_exporter virtual service account and
# verifies the whole pipeline. Runs through a managed Run Command as the VM
# local administrator (a sysadmin on the SQL Server marketplace image).
# Permissions: server state, metadata, and per-database DMVs (no table data),
# plus SELECT on msdb backup and job history.
$ErrorActionPreference = 'Stop'
$serviceName = 'SqlExporterSvc'
$login = "NT SERVICE\$serviceName"

function Invoke-Sql([string]$sql) {
    $connection = New-Object System.Data.SqlClient.SqlConnection 'Server=localhost;Database=master;Integrated Security=SSPI;Application Name=sre-lab-setup'
    try {
        $connection.Open()
        $command = $connection.CreateCommand()
        $command.CommandText = $sql
        [void]$command.ExecuteNonQuery()
    }
    finally { $connection.Dispose() }
}

Invoke-Sql @"
IF SUSER_ID(N'$login') IS NULL CREATE LOGIN [$login] FROM WINDOWS WITH DEFAULT_DATABASE = master;
GRANT VIEW SERVER STATE, VIEW ANY DEFINITION, CONNECT ANY DATABASE TO [$login];
"@
Invoke-Sql @"
USE msdb;
IF USER_ID(N'$login') IS NULL CREATE USER [$login] FOR LOGIN [$login];
GRANT SELECT ON dbo.backupset TO [$login];
GRANT SELECT ON dbo.sysjobs TO [$login];
GRANT SELECT ON dbo.sysjobhistory TO [$login];
"@
Restart-Service $serviceName

$body = ''
for ($i = 0; $i -lt 30 -and $body -notmatch 'mssql_wait_time_seconds_total'; $i++) {
    Start-Sleep -Seconds 2
    try { $body = (Invoke-WebRequest -Uri 'http://127.0.0.1:9399/metrics' -UseBasicParsing -TimeoutSec 25).Content } catch { }
}
if ($body -notmatch 'mssql_wait_time_seconds_total') { throw 'sql_exporter does not expose mssql_health metrics' }

# Report remote_write progress (HTTP 403 is expected for a while after the
# Monitoring Metrics Publisher assignment while it propagates).
Start-Sleep -Seconds 60
$metrics = (Invoke-WebRequest -Uri 'http://127.0.0.1:9090/metrics' -UseBasicParsing).Content -split "`n"
$metrics | Where-Object { $_ -match '^prometheus_remote_storage_(samples_total|samples_failed_total|samples_retried_total)' } | ForEach-Object { Write-Output $_ }
Write-Output "Login $login is ready and metrics are flowing to remote_write."
