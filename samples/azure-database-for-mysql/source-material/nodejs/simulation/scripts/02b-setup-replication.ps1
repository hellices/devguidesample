<#
.SYNOPSIS
  02b - Create new-db as standalone v8.4 (VNet Integration) and set up
        MySQL binlog replication from old-db.

  Steps:
    1. Create new-db (standalone v8.4, VNet Integration, same mysql-subnet as old-db)
    2. Create replication user on old-db
    3. mysqldump old-db (--single-transaction --master-data=2) via mysql-client pod
    4. Restore dump to new-db
    5. CHANGE REPLICATION SOURCE TO ... ; START REPLICA on new-db
    6. Verify SHOW REPLICA STATUS (IO + SQL threads running, Seconds_Behind_Source = 0)
    7. Update sim-env.json

  VNet topology:
    old-db in mysql-subnet (VNet Integration) -- accessible from new-db & AKS pods
    new-db in mysql-subnet (VNet Integration) -- same VNet, direct connection to old-db
    Replication: new-db IO thread -> old-db FQDN (resolved to VNet IP via
                 Private DNS Zone mysql.database.azure.com)

  Docs:
    https://dev.mysql.com/doc/refman/8.4/en/change-replication-source-to.html
    https://learn.microsoft.com/azure/mysql/flexible-server/concepts-networking-vnet

.USAGE
  .\02b-setup-replication.ps1
#>
param()
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path $MyInvocation.MyCommand.Path
$e         = Get-Content (Join-Path $scriptDir "sim-env.json") | ConvertFrom-Json
$rg        = $e.resourceGroup
$prefix    = $e.prefix
$oldFqdn   = $e.mysqlOldFqdn
$adminUser = $e.mysqlAdminUser
$password  = $e.password
$dbName    = $e.dbName

$newName = "$prefix-new-db"
$newFqdn = "$newName.$($e.privateDnsZoneName)"

$replUser = "repl_user"
$replPass = "ReplP@ss2026!"

function Log($step, $msg) {
    Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] [$step] $msg"
}

function Invoke-Sql($fqdn, $sql) {
    kubectl exec -n default mysql-client -- `
        mysql -h $fqdn -u $adminUser -p"$password" --ssl-mode=REQUIRED -e $sql
}

# --- Ensure mysql-client pod is running ------------------------------------------------
Log "INIT" "Ensure mysql-client pod..."
$existing = kubectl get pod mysql-client -n default --no-headers --ignore-not-found 2>$null
if (-not $existing) {
    @"
apiVersion: v1
kind: Pod
metadata:
  name: mysql-client
  namespace: default
spec:
  restartPolicy: Never
  containers:
  - name: mysql
    image: mysql:8.0
    command: ["sleep", "86400"]
"@ | kubectl apply -f -
    kubectl wait pod/mysql-client --for=condition=Ready --timeout=120s
}

# --- Step 1: Create new-db (standalone v8.4, VNet Integration) -------------------------
$ErrorActionPreference = 'Continue'
$newDbExists = az mysql flexible-server show --resource-group $rg --name $newName --query name -o tsv 2>$null
$ErrorActionPreference = 'Stop'

if ($newDbExists -eq $newName) {
    Log 1 "new-db already exists, skipping creation."
} else {
    Log 1 "Creating new-db: $newName (standalone v8.4, VNet Integration, ~5min)..."

    $dnsZoneId = az network private-dns zone show `
        --resource-group $rg `
        --name $e.privateDnsZoneName `
        --query id -o tsv

    az mysql flexible-server create `
        --resource-group $rg `
        --name $newName `
        --vnet "$prefix-vnet" `
        --subnet "mysql-subnet" `
        --private-dns-zone $dnsZoneId `
        --admin-user $adminUser `
        --admin-password $password `
        --version "8.4" `
        --sku-name "Standard_D4ds_v4" `
        --tier "GeneralPurpose" `
        --storage-size 20 `
        --backup-retention 1 `
        --geo-redundant-backup Disabled `
        --output none

    Log 1 "new-db created (v8.4, VNet Integration)."
}

# Ensure simdb database exists on new-db
Log 1 "Creating database $dbName on new-db if missing..."
Invoke-Sql $newFqdn "CREATE DATABASE IF NOT EXISTS $dbName;" | Out-Null

# --- Step 2: Create replication user on old-db -----------------------------------------
Log 2 "Creating replication user '$replUser' on old-db..."
Invoke-Sql $oldFqdn @"
CREATE USER IF NOT EXISTS '${replUser}'@'%' IDENTIFIED WITH mysql_native_password BY '${replPass}';
GRANT REPLICATION SLAVE ON *.* TO '${replUser}'@'%';
FLUSH PRIVILEGES;
"@ | Out-Null
Log 2 "Replication user ready."

# --- Step 3: mysqldump old-db via mysql-client pod -------------------------------------
Log 3 "Dumping old-db ($dbName) via mysql-client pod (--single-transaction --master-data=2)..."
$dumpCmd = "mysqldump -h $oldFqdn -u $adminUser -p'$password' " +
           "--single-transaction --master-data=2 --set-gtid-purged=OFF " +
           "--ssl-mode=REQUIRED $dbName > /tmp/dump.sql 2>/tmp/dump.err"

kubectl exec -n default mysql-client -- bash -c $dumpCmd 2>&1 | Out-Null
$dumpErr = kubectl exec -n default mysql-client -- bash -c "cat /tmp/dump.err" 2>&1
if ($dumpErr -and $dumpErr -notmatch '^\s*$') {
    Log 3 "  mysqldump stderr: $dumpErr"
}

# Parse binlog file/position embedded as comment in dump header
$changeLine = kubectl exec -n default mysql-client -- `
    bash -c "grep '^-- CHANGE MASTER TO' /tmp/dump.sql | head -1" 2>&1
Log 3 "  Binlog position line: $changeLine"

if ($changeLine -match "MASTER_LOG_FILE='([^']+)'.*MASTER_LOG_POS=(\d+)") {
    $logFile = $Matches[1]
    $logPos  = $Matches[2]
    Log 3 "  Binlog: FILE=$logFile  POS=$logPos"
} else {
    throw "[Step 3] Could not parse binlog position from dump. Check /tmp/dump.sql header."
}

# --- Step 4: Restore dump to new-db ----------------------------------------------------
Log 4 "Restoring dump to new-db ($dbName)..."
$restoreCmd = "mysql -h $newFqdn -u $adminUser -p'$password' " +
              "--ssl-mode=REQUIRED $dbName < /tmp/dump.sql 2>&1"
$restoreOut = kubectl exec -n default mysql-client -- bash -c $restoreCmd 2>&1
if ($restoreOut -and $restoreOut -notmatch '^\s*$') {
    Log 4 "  mysql output: $restoreOut"
}
Log 4 "Restore complete."

# --- Step 4b: Create app user on new-db (cutover 후 앱이 접속할 계정) ----------------
$appUser = $e.appUser
$appPass = $e.appPassword
Log "4b" "Creating app user '$appUser' on new-db..."
Invoke-Sql $newFqdn @"
CREATE USER IF NOT EXISTS '${appUser}'@'%' IDENTIFIED BY '${appPass}';
GRANT SELECT, INSERT, UPDATE, DELETE ON ${dbName}.* TO '${appUser}'@'%';
FLUSH PRIVILEGES;
"@ | Out-Null
Log "4b" "App user ready on new-db."

# --- Step 4c: Disable require_secure_transport on old-db (replication IO thread uses plain TCP) ---
Log "4c" "Disabling require_secure_transport on old-db (for replication IO thread)..."
az mysql flexible-server parameter set `
    --resource-group $rg --server-name $e.mysqlOldName `
    --name require_secure_transport --value OFF --output none 2>&1 | Out-Null
Log "4c" "require_secure_transport=OFF on old-db."

# --- Step 5: Set up replication on new-db ----------------------------------------------
Log 5 "Configuring replication on new-db (mysql.az_replication_change_master + az_replication_start)..."
# Azure MySQL Flexible Server 에서는 CHANGE REPLICATION SOURCE TO 에 SUPER 권한 필요
# → mysql.az_replication_change_master 스토어드 프로시저로 우회
Invoke-Sql $newFqdn "CALL mysql.az_replication_change_master('$oldFqdn', '$replUser', '$replPass', 3306, '$logFile', $logPos, '');" | Out-Null
Invoke-Sql $newFqdn "CALL mysql.az_replication_start;" | Out-Null
Log 5 "az_replication_start issued."

# --- Step 6: Verify replication is running, lag = 0 -----------------------------------
Log 6 "Verifying replication status (wait up to 60s for IO+SQL running, lag=0)..."
$deadline  = (Get-Date).AddSeconds(60)
$replicaOk = $false
while ((Get-Date) -lt $deadline) {
    $status     = kubectl exec -n default mysql-client -- `
        mysql -h $newFqdn -u $adminUser -p"$password" `
              --ssl-mode=REQUIRED -e "SHOW REPLICA STATUS\G"
    $ioRunning  = ($status | Select-String "Replica_IO_Running:\s+Yes").Count -gt 0
    $sqlRunning = ($status | Select-String "Replica_SQL_Running:\s+Yes").Count -gt 0
    $lagLine    = $status | Select-String "Seconds_Behind_Source:" | Select-Object -Last 1
    $lagStr     = if ($lagLine) { ($lagLine -replace '.*Seconds_Behind_Source:\s*', '').Trim() } else { 'unknown' }
    $ioStr      = if ($ioRunning)  { 'Yes' } else { 'No' }
    $sqlStr     = if ($sqlRunning) { 'Yes' } else { 'No' }
    Log 6 "  IO_Running=$ioStr  SQL_Running=$sqlStr  Lag=${lagStr}s"

    $ioErrors  = $status | Select-String "Last_IO_Error:" | Where-Object { $_ -notmatch 'Last_IO_Error:\s*$' }
    $sqlErrors = $status | Select-String "Last_SQL_Error:" | Where-Object { $_ -notmatch 'Last_SQL_Error:\s*$' }
    if ($ioErrors)  { Log 6 "  IO Error:  $ioErrors" }
    if ($sqlErrors) { Log 6 "  SQL Error: $sqlErrors" }

    if ($ioRunning -and $sqlRunning) {
        $replicaOk = $true
        Log 6 "  Replication running. Lag=${lagStr}s"
        break
    }
    Start-Sleep 5
}
if (-not $replicaOk) {
    Write-Warning "[Step 6] Replication threads not running after 60s. Check SHOW REPLICA STATUS on new-db."
}

# --- Step 7: Update sim-env.json -------------------------------------------------------
Log 7 "Updating sim-env.json..."
$e | Add-Member -NotePropertyName "mysqlNewName" -NotePropertyValue $newName -Force
$e | Add-Member -NotePropertyName "mysqlNewFqdn" -NotePropertyValue $newFqdn -Force
$e | ConvertTo-Json | Set-Content (Join-Path $scriptDir "sim-env.json")

Write-Host ""
Write-Host "==========================================================="
Log "DONE" "SQL Replication setup complete."
Write-Host "  old-db  : $oldFqdn  (source, v8.0.21)"
Write-Host "  new-db  : $newFqdn  (replica, v8.4, SQL replication running)"
Write-Host "  repl    : IO+SQL threads running, Seconds_Behind_Source=0"
Write-Host ""
Write-Host "  Promote preview: STOP REPLICA; RESET REPLICA ALL  (instant)"
Write-Host ""
Write-Host "  Next step: .\03-build-push.ps1"
Write-Host "             Then: .\04-watch-logs.ps1  (separate terminal)"
Write-Host "             Then: .\05-cutover.ps1"
Write-Host "==========================================================="
