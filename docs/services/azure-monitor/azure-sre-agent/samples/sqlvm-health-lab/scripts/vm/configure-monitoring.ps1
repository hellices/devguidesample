# Installs the SQL Server metrics pipeline on the VM. Runs through a managed Run
# Command as LocalSystem; scripts/vm/grant-exporter-login.ps1 then creates the
# SQL Server login for the exporter service. scripts/render_monitoring_script.py
# fills the @@...@@ placeholders.
#
#   windows_exporter (MSI service, 127.0.0.1:9182)  OS + SQL Server perf counters
#   sql_exporter     (service, 127.0.0.1:9399)      DMV health queries
#   Prometheus agent (scheduled task, 127.0.0.1:9090) scrape -> remote_write
#                                                    to Azure Monitor workspace
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$packages = @{
    windows_exporter = @{
        Url    = 'https://github.com/prometheus-community/windows_exporter/releases/download/v0.32.0/windows_exporter-0.32.0-amd64.msi'
        Sha256 = 'd48ebad7999aac5603fe01007016a0ddbcecbc1aa0ecbc51867a2416b6c60a7d'
    }
    sql_exporter     = @{
        Url    = 'https://github.com/burningalchemist/sql_exporter/releases/download/0.24.12/sql_exporter-0.24.12.windows-amd64.zip'
        Sha256 = 'd698d9f7706ea53dd15cb4255b945266b1c8e5712ebb9505d1fc4c8fab3049e9'
    }
    prometheus       = @{
        Url    = 'https://github.com/prometheus/prometheus/releases/download/v3.15.1/prometheus-3.15.1.windows-amd64.zip'
        Sha256 = 'ba25b5e590520cb9fb028edef99bdc8523244d2d489b8c629e0d453d94fb030b'
    }
}

$root = 'C:\SreLab\monitoring'
$downloads = Join-Path $root 'downloads'
New-Item -ItemType Directory -Path $downloads -Force | Out-Null

function Get-VerifiedPackage([string]$name) {
    $package = $packages[$name]
    $file = Join-Path $downloads ([IO.Path]::GetFileName($package.Url))
    if (-not (Test-Path $file) -or (Get-FileHash $file -Algorithm SHA256).Hash -ne $package.Sha256.ToUpper()) {
        Invoke-WebRequest -Uri $package.Url -OutFile $file -UseBasicParsing
    }
    $hash = (Get-FileHash $file -Algorithm SHA256).Hash
    if ($hash -ne $package.Sha256.ToUpper()) { throw "SHA256 mismatch for ${name}: $hash" }
    return $file
}

function Expand-Binary([string]$zip, [string]$exe, [string]$destination) {
    $staging = Join-Path $downloads ([IO.Path]::GetFileNameWithoutExtension($zip))
    if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $staging -Force
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    $binary = Get-ChildItem $staging -Recurse -Filter $exe | Select-Object -First 1
    $target = Join-Path $destination $exe
    if ((Test-Path $target) -and (Get-FileHash $target).Hash -eq (Get-FileHash $binary.FullName).Hash) { return }
    Copy-Item $binary.FullName $target -Force
}

function Write-Base64File([string]$path, [string]$base64) {
    [IO.File]::WriteAllBytes($path, [Convert]::FromBase64String($base64))
}

function Wait-Endpoint([string]$url, [string]$pattern) {
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $body = (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 20).Content
            if ($body -match $pattern) { return }
        }
        catch { }
        Start-Sleep -Seconds 2
    }
    throw "$url did not expose $pattern"
}

# ── windows_exporter: OS and SQL Server performance counters ──
$msi = Get-VerifiedPackage 'windows_exporter'
$arguments = "/i `"$msi`" /qn /norestart ENABLED_COLLECTORS=cpu,logical_disk,memory,net,os,system,mssql LISTEN_ADDR=127.0.0.1 LISTEN_PORT=9182"
$process = Start-Process msiexec.exe -ArgumentList $arguments -Wait -PassThru
if ($process.ExitCode -notin 0, 3010) { throw "windows_exporter install failed: $($process.ExitCode)" }
Wait-Endpoint 'http://127.0.0.1:9182/metrics' 'windows_mssql_sqlstats_batch_requests_total'

# ── sql_exporter: DMV health queries as NT SERVICE\SqlExporterSvc ──
$sqlExporterDir = 'C:\Program Files\sql_exporter'
$serviceName = 'SqlExporterSvc'
$existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($existing) { Stop-Service $serviceName -Force }
# Re-runs replace the binary, so wait until the old process releases it.
Get-Process sql_exporter -ErrorAction SilentlyContinue | Wait-Process -Timeout 60 -ErrorAction SilentlyContinue
Expand-Binary (Get-VerifiedPackage 'sql_exporter') 'sql_exporter.exe' $sqlExporterDir
Write-Base64File (Join-Path $sqlExporterDir 'sql_exporter.yml') '@@SQL_EXPORTER_YML_B64@@'
Write-Base64File (Join-Path $sqlExporterDir 'mssql_health.collector.yml') '@@COLLECTOR_HEALTH_B64@@'
Write-Base64File (Join-Path $sqlExporterDir 'mssql_audit.collector.yml') '@@COLLECTOR_AUDIT_B64@@'
Write-Base64File (Join-Path $sqlExporterDir 'mssql_inventory.collector.yml') '@@COLLECTOR_INVENTORY_B64@@'
if (-not $existing) {
    $binaryPath = "`"$sqlExporterDir\sql_exporter.exe`" --config.file=`"$sqlExporterDir\sql_exporter.yml`" --web.listen-address=127.0.0.1:9399"
    New-Service -Name $serviceName -BinaryPathName $binaryPath -StartupType Automatic -DisplayName 'Prometheus SQL Exporter' | Out-Null
    & sc.exe config $serviceName obj= "NT SERVICE\$serviceName" | Out-Null
    & sc.exe failure $serviceName reset= 86400 actions= restart/60000/restart/60000/restart/60000 | Out-Null
}
& icacls.exe $sqlExporterDir /grant "NT SERVICE\${serviceName}:(OI)(CI)RX" | Out-Null
# Until grant-exporter-login.ps1 creates the SQL Server login, /metrics returns
# HTTP 500, so only the landing page is checked here.
Start-Service $serviceName
Wait-Endpoint 'http://127.0.0.1:9399/' '.'

# ── Prometheus agent: scrape and remote_write with managed identity ──
$prometheusDir = 'C:\Program Files\prometheus'
$taskName = 'PrometheusAgent'
# The task restarts Prometheus after it exits, so disable it before stopping the process.
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    Stop-ScheduledTask -TaskName $taskName
}
Get-Process prometheus -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process prometheus -ErrorAction SilentlyContinue | Wait-Process -Timeout 60 -ErrorAction SilentlyContinue
Expand-Binary (Get-VerifiedPackage 'prometheus') 'prometheus.exe' $prometheusDir
Write-Base64File (Join-Path $prometheusDir 'prometheus.yml') '@@PROMETHEUS_YML_B64@@'
New-Item -ItemType Directory -Path (Join-Path $root 'prometheus-wal') -Force | Out-Null
$promArgs = "--agent --config.file=`"$prometheusDir\prometheus.yml`" --storage.agent.path=`"$root\prometheus-wal`" --web.listen-address=127.0.0.1:9090"
# Prometheus is not a Windows service binary, so a SYSTEM startup task keeps it running.
$action = New-ScheduledTaskAction -Execute "$prometheusDir\prometheus.exe" -Argument $promArgs -WorkingDirectory $prometheusDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Wait-Endpoint 'http://127.0.0.1:9090/metrics' 'prometheus_remote_storage_samples_total'

Write-Output 'Exporters and Prometheus agent are installed.'
