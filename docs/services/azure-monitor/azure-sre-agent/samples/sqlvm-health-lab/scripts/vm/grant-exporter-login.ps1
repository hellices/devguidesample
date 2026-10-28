# Creates the SQL Server login for the sql_exporter virtual service account,
# checks that sql_exporter exposes metrics, and reports whether remote_write
# has sent samples. Runs through a managed Run Command as the VM
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

# Wait until remote_write has sent samples. The Monitoring Metrics Publisher
# assignment can take a while to propagate (HTTP 403 until then), so a timeout
# is reported as a warning with the counters instead of failing the deployment.
function Get-RemoteWriteCounters {
    $lines = (Invoke-WebRequest -Uri 'http://127.0.0.1:9090/metrics' -UseBasicParsing).Content -split "`n"
    $lines | Where-Object { $_ -match '^prometheus_remote_storage_(samples_total|samples_failed_total|samples_retried_total)' }
}
function Get-Counter([string[]]$lines, [string]$name) {
    $line = $lines | Where-Object { $_ -match "^${name}[{ ]" } | Select-Object -First 1
    if ($line) { [double]($line -split ' ')[-1] } else { 0 }
}
$sent = 0
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 10
    $counters = Get-RemoteWriteCounters
    $sent = Get-Counter $counters 'prometheus_remote_storage_samples_total'
    $failed = Get-Counter $counters 'prometheus_remote_storage_samples_failed_total'
    if ($sent -gt 0 -and $failed -eq 0) { break }
}
$counters | ForEach-Object { Write-Output $_ }
if ($sent -gt 0 -and $failed -eq 0) {
    Write-Output "Login $login is ready and remote_write has sent $sent samples without failures."
}
else {
    Write-Warning "remote_write has not succeeded yet (sent $sent, failed $failed). Check again after the role assignment propagates."
    Write-Output "Login $login is ready; remote_write is not confirmed yet."
}
