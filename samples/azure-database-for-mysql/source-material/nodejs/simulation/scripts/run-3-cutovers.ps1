<#
.SYNOPSIS
  Run 3 cutover tests at 50 pods, collecting metrics for each run.
  After each cutover, automatically resets the environment for the next run.
#>
param()
$ErrorActionPreference = 'Continue'
$scriptDir = Split-Path $MyInvocation.MyCommand.Path
$e = Get-Content (Join-Path $scriptDir "sim-env.json") | ConvertFrom-Json
$env:AZURE_EXTENSION_DIR = "$env:USERPROFILE\.azure\cliextensions-clean"

$oldFqdn   = $e.mysqlOldFqdn
$newFqdn   = $e.mysqlNewFqdn
$adminUser = $e.mysqlAdminUser
$pw        = $e.password
$rg        = $e.resourceGroup
$zone      = $e.customDnsZone
$appFqdn   = $e.appFqdn
$appUser   = $e.appUser

function Sql($fqdn, $sql) {
    kubectl exec -n default mysql-client-co -- mysql -h $fqdn -u $adminUser -p"$pw" --ssl-mode=REQUIRED -s -N -e $sql 2>&1
}

function SqlMulti($fqdn, $sql) {
    kubectl exec -n default mysql-client-co -- mysql -h $fqdn -u $adminUser -p"$pw" --ssl-mode=REQUIRED -e $sql 2>&1
}

function Log($msg) {
    $ts = (Get-Date).ToString("HH:mm:ss.fff")
    Write-Host "[$ts] $msg"
}

function Reset-Environment {
    Log "=== RESETTING ENVIRONMENT ==="
    
    # Scale to 0
    kubectl scale deployment crud-worker -n db-sim --replicas=0 2>&1 | Out-Null
    Log "Scaled to 0"
    Start-Sleep 8
    
    # CNAME -> old-db
    az network private-dns record-set cname set-record --resource-group $rg --zone-name $zone --record-set-name primary --cname $oldFqdn --output none 2>&1
    Log "CNAME -> old-db"
    
    # Unlock appuser on old-db
    SqlMulti $oldFqdn "GRANT SELECT,INSERT,UPDATE,DELETE ON simdb.* TO '${appUser}'@'%'; ALTER USER '${appUser}'@'%' ACCOUNT UNLOCK; FLUSH PRIVILEGES;" | Out-Null
    Log "appuser unlocked on old-db"
    
    # Stop replication with Azure procedure (critical: raw STOP REPLICA alone can leave bad state)
    SqlMulti $newFqdn "CALL mysql.az_replication_stop;" 2>&1 | Out-Null
    Start-Sleep 2
    SqlMulti $newFqdn "RESET REPLICA ALL;" 2>&1 | Out-Null
    Log "Replication stopped"
    
    # Drop + recreate tables on both (clean slate, avoids binlog position mismatch)
    $ddl = @"
DROP TABLE IF EXISTS simdb.orders;
CREATE TABLE simdb.orders (
  id int NOT NULL AUTO_INCREMENT,
  item varchar(100) NOT NULL,
  qty int NOT NULL DEFAULT 1,
  server_name varchar(100) DEFAULT NULL COMMENT 'DB server hostname at insert time',
  created_at datetime(3) DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
"@
    SqlMulti $oldFqdn $ddl | Out-Null
    SqlMulti $newFqdn $ddl | Out-Null
    Log "Tables recreated (DROP+CREATE)"
    
    # Fresh binlog (after DDL, so new-db starts from clean state)
    $posRaw = Sql $oldFqdn "SHOW MASTER STATUS;"
    $posLine = ($posRaw | Where-Object { $_ -match 'mysql-bin' }) | Select-Object -First 1
    $parts = $posLine -split '\s+'
    $script:replFile = $parts[0]; $script:replPos = $parts[1]
    Log "Binlog: $($script:replFile) @ $($script:replPos)"
    
    # Setup replication
    SqlMulti $newFqdn "CALL mysql.az_replication_change_master('$oldFqdn', 'repl_user', 'ReplP@ss2026!', 3306, '$($script:replFile)', $($script:replPos), '');" | Out-Null
    SqlMulti $newFqdn "CALL mysql.az_replication_start;" | Out-Null
    Start-Sleep 5
    
    # Verify replication (retry up to 3 times)
    $replOk = $false
    for ($retry = 1; $retry -le 3; $retry++) {
        $replOut = SqlMulti $newFqdn "SHOW REPLICA STATUS\G"
        $ioOk = ($replOut | Select-String "Replica_IO_Running:\s+Yes").Count -gt 0
        $sqlOk = ($replOut | Select-String "Replica_SQL_Running:\s+Yes").Count -gt 0
        if ($ioOk -and $sqlOk) {
            $replOk = $true
            break
        }
        $sqlErr = ($replOut | Select-String "Last_SQL_Error:" | ForEach-Object { ($_ -replace '.*Last_SQL_Error:\s*','').Trim() }) | Select-Object -First 1
        Log "Replication check $retry : IO=$ioOk SQL=$sqlOk err=$sqlErr"
        Start-Sleep 5
    }
    if (-not $replOk) {
        Log "FATAL: Replication not healthy after 3 retries"
        $script:resetFailed = $true
        return
    }
    Log "Replication OK (IO=Yes, SQL=Yes)"
    $script:resetFailed = $false
    
    # Scale to 50
    kubectl scale deployment crud-worker -n db-sim --replicas=50 2>&1 | Out-Null
    kubectl rollout status deployment crud-worker -n db-sim --timeout=180s 2>&1 | Out-Null
    Log "50 pods ready"
    
    # Wait for steady state
    Start-Sleep 20
    
    # Verify
    $sess = (Sql $oldFqdn "SELECT COUNT(*) FROM information_schema.processlist WHERE user='$appUser';") | Where-Object { $_ -match '^\d+$' } | Select-Object -First 1
    $pod = kubectl get pod -n db-sim -l app=crud-worker --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>$null
    $logLines = kubectl logs -n db-sim $pod --tail=2 2>&1
    Log "Sessions on old-db: $sess"
    $logLines | ForEach-Object { Log "  $_" }
}

function Run-Cutover($runNum) {
    Log "========================================="
    Log "=== CUTOVER RUN $runNum ==="
    Log "========================================="
    
    $metrics = @{
        Run = $runNum
        TotalTime = 0
        LagWaitTime = 0
        CNAMEPropTime = 0
        KillRounds = 0
        KillCount = 0
        AppErrors = 0
        PostOps = 0
    }
    
    $startTs = Get-Date
    
    # --- Phase 1: Lock appuser ---
    $p1Ts = Get-Date
    SqlMulti $oldFqdn "REVOKE INSERT, UPDATE, DELETE ON simdb.* FROM '${appUser}'@'%'; ALTER USER '${appUser}'@'%' ACCOUNT LOCK; FLUSH PRIVILEGES;"
    Log "[P1] appuser locked"
    Start-Sleep 2
    
    # --- Phase 1W: Wait for lag = 0 ---
    $p1wTs = Get-Date
    $deadline = (Get-Date).AddSeconds(60)
    $lagZero = $false
    while ((Get-Date) -lt $deadline) {
        $status = SqlMulti $newFqdn "SHOW REPLICA STATUS\G"
        $ioRunning  = ($status | Select-String "Replica_IO_Running:\s+Yes").Count -gt 0
        $sqlRunning = ($status | Select-String "Replica_SQL_Running:\s+Yes").Count -gt 0
        $lagLine    = $status | Select-String "Seconds_Behind_Source:" | Select-Object -Last 1
        $lagStr     = if ($lagLine) { ($lagLine -replace '.*Seconds_Behind_Source:\s*', '').Trim() } else { '?' }
        Log "[P1W] IO=$(if($ioRunning){'Y'}else{'N'}) SQL=$(if($sqlRunning){'Y'}else{'N'}) Lag=${lagStr}s"
        if ($ioRunning -and $sqlRunning -and ($lagStr -eq '0' -or $lagStr -eq 'NULL')) {
            $lagZero = $true
            break
        }
        Start-Sleep 3
    }
    $lagWaitEnd = Get-Date
    $metrics.LagWaitTime = [math]::Round(($lagWaitEnd - $p1wTs).TotalSeconds, 1)
    Log "[P1W] Lag wait: $($metrics.LagWaitTime)s (zero=$lagZero)"
    
    # --- Phase 1S: Promote new-db ---
    SqlMulti $newFqdn "STOP REPLICA; RESET REPLICA ALL;" | Out-Null
    Log "[P1S] new-db promoted (standalone)"
    
    # --- Phase 2: CNAME switch ---
    $p2Ts = Get-Date
    az network private-dns record-set cname set-record --resource-group $rg --zone-name $zone --record-set-name primary --cname $newFqdn --output none 2>&1
    $cnameUpdTs = Get-Date
    Log "[P2] CNAME updated"
    
    # --- Phase 2W: Wait for DNS propagation ---
    $pod = kubectl get pod -n db-sim -l app=crud-worker --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>$null
    $dnsDeadline = (Get-Date).AddSeconds(30)
    $dnsOk = $false
    while ((Get-Date) -lt $dnsDeadline) {
        $ns = kubectl exec -n db-sim $pod -- nslookup $appFqdn 2>&1
        if ($ns -match [regex]::Escape($e.mysqlNewName)) {
            $dnsOk = $true
            break
        }
        Start-Sleep 1
    }
    $dnsPropTs = Get-Date
    $metrics.CNAMEPropTime = [math]::Round(($dnsPropTs - $cnameUpdTs).TotalSeconds, 1)
    Log "[P2W] DNS propagated in $($metrics.CNAMEPropTime)s (ok=$dnsOk)"
    
    # --- Phase 3: Kill sessions ---
    # Create kill script
    $scriptContent = @'
#!/bin/bash
MYSQL="mysql -h __OLD__ -u __ADMIN__ -p__PW__ --ssl-mode=REQUIRED"
CNT=$($MYSQL -s -N -e "SELECT COUNT(*) FROM information_schema.processlist WHERE user='__APP__'" 2>/dev/null)
echo FOUND:$CNT
if [ "$CNT" = "0" ]; then exit 0; fi
$MYSQL -s -N -e "SELECT id FROM information_schema.processlist WHERE user='__APP__'" 2>/dev/null | while read id; do echo "CALL mysql.az_kill($id);"; done > /tmp/kill.sql
echo STMTS:$(wc -l < /tmp/kill.sql)
$MYSQL --force < /tmp/kill.sql 2>/dev/null
REMAINING=$($MYSQL -s -N -e "SELECT COUNT(*) FROM information_schema.processlist WHERE user='__APP__'" 2>/dev/null)
echo REMAINING:$REMAINING
'@
    $scriptContent = $scriptContent.Replace('__OLD__', $oldFqdn).Replace('__ADMIN__', $adminUser).Replace('__PW__', $pw).Replace('__APP__', $appUser)
    $tmpFile = Join-Path $scriptDir "kill_tmp.sh"
    [IO.File]::WriteAllText($tmpFile, $scriptContent.Replace("`r`n","`n"), [Text.UTF8Encoding]::new($false))
    Push-Location $scriptDir
    kubectl cp "kill_tmp.sh" default/mysql-client-co:/tmp/kill_sessions.sh 2>&1 | Out-Null
    Pop-Location
    Remove-Item $tmpFile -Force
    kubectl exec -n default mysql-client-co -- chmod +x /tmp/kill_sessions.sh 2>&1 | Out-Null
    
    $totalKilled = 0
    for ($round = 1; $round -le 3; $round++) {
        $result = kubectl exec -n default mysql-client-co -- bash /tmp/kill_sessions.sh 2>&1
        $found  = ($result | Select-String 'FOUND:'     | ForEach-Object { ($_ -replace '.*FOUND:','').Trim() }) | Select-Object -First 1
        $stmts  = ($result | Select-String 'STMTS:'     | ForEach-Object { ($_ -replace '.*STMTS:','').Trim() }) | Select-Object -First 1
        $remain = ($result | Select-String 'REMAINING:' | ForEach-Object { ($_ -replace '.*REMAINING:','').Trim() }) | Select-Object -First 1
        Log "[P3] Round $round : found=$found killed=$stmts remaining=$remain"
        if ($stmts) { $totalKilled += [int]$stmts }
        $metrics.KillRounds = $round
        if ($found -eq '0' -or $remain -eq '0') { break }
        Start-Sleep 2
    }
    $metrics.KillCount = $totalKilled
    
    # --- Phase 3V: Verify old-db drained ---
    $drainDeadline = (Get-Date).AddSeconds(30)
    $drained = $false
    while ((Get-Date) -lt $drainDeadline) {
        $oldSess = (Sql $oldFqdn "SELECT COUNT(*) FROM information_schema.processlist WHERE user='$appUser';") | Where-Object { $_ -match '^\d+$' } | Select-Object -First 1
        if ($oldSess -eq '0') { $drained = $true; break }
        Log "[P3V] old-db sessions: $oldSess"
        Start-Sleep 3
    }
    Log "[P3V] old-db drained=$drained"
    
    # --- Phase 4: Verify new-db convergence ---
    Start-Sleep 5
    $newSess = (Sql $newFqdn "SELECT COUNT(*) FROM information_schema.processlist WHERE user='$appUser';") | Where-Object { $_ -match '^\d+$' } | Select-Object -First 1
    Log "[P4] new-db sessions: $newSess"
    
    $endTs = Get-Date
    $metrics.TotalTime = [math]::Round(($endTs - $startTs).TotalSeconds, 1)
    
    # Get app errors from a pod log
    Start-Sleep 3
    $pod = kubectl get pod -n db-sim -l app=crud-worker --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>$null
    $logLines = kubectl logs -n db-sim $pod --tail=5 2>&1
    # Extract err count from latest log line
    $errLine = $logLines | Where-Object { $_ -match 'err=\d+' } | Select-Object -Last 1
    if ($errLine -match 'err=(\d+)') { $metrics.AppErrors = [int]$Matches[1] }
    if ($errLine -match 'ops=(\d+)/s') { $metrics.PostOps = [int]$Matches[1] }
    $logLines | ForEach-Object { Log "  $_" }
    
    Log "========================================="
    Log "=== RUN $runNum RESULTS ==="
    Log "  Total time    : $($metrics.TotalTime)s"
    Log "  Lag wait      : $($metrics.LagWaitTime)s"
    Log "  CNAME prop    : $($metrics.CNAMEPropTime)s"
    Log "  Kill rounds   : $($metrics.KillRounds)"
    Log "  Kill count    : $($metrics.KillCount)"
    Log "  App errors    : $($metrics.AppErrors)"
    Log "  Post ops/s    : $($metrics.PostOps)"
    Log "  new-db sess   : $newSess"
    Log "========================================="
    
    return $metrics
}

# ─── MAIN ──────────────────────────────────────────────────────────────────────
$allResults = @()
$script:resetFailed = $false

for ($i = 1; $i -le 3; $i++) {
    if ($i -eq 1) {
        # For the first run, environment should already be ready (replication set up, 0 pods)
        # Just scale up
        kubectl scale deployment crud-worker -n db-sim --replicas=50 2>&1 | Out-Null
        kubectl rollout status deployment crud-worker -n db-sim --timeout=180s 2>&1 | Out-Null
        Log "50 pods ready"
        Start-Sleep 20
        
        $sess = (Sql $oldFqdn "SELECT COUNT(*) FROM information_schema.processlist WHERE user='$appUser';") | Where-Object { $_ -match '^\d+$' } | Select-Object -First 1
        Log "Pre-cutover sessions on old-db: $sess"
    }
    
    $result = Run-Cutover $i
    $allResults += $result
    
    if ($i -lt 3) {
        Log "Waiting 10s before reset..."
        Start-Sleep 10
        
        # Check if mysql-client-co is still running
        $coStatus = kubectl get pod mysql-client-co -n default -o jsonpath='{.status.phase}' 2>$null
        if ($coStatus -ne 'Running') {
            Log "mysql-client-co not running ($coStatus). Recreating..."
            kubectl delete pod mysql-client-co -n default --ignore-not-found 2>&1 | Out-Null
            @"
apiVersion: v1
kind: Pod
metadata:
  name: mysql-client-co
  namespace: default
spec:
  restartPolicy: Never
  containers:
  - name: mysql
    image: mysql:8.0
    command: ["sleep", "7200"]
"@ | kubectl apply -f -
            kubectl wait pod/mysql-client-co --for=condition=Ready --timeout=120s 2>&1 | Out-Null
        }
        
        Reset-Environment
        if ($script:resetFailed) {
            Log "RESET FAILED. Stopping."
            break
        }
    }
}

Write-Host "`n`n========================================"
Write-Host "=== ALL RUNS COMPLETE ==="
Write-Host "========================================"
foreach ($r in $allResults) {
    Write-Host "Run $($r.Run): Total=$($r.TotalTime)s  Lag=$($r.LagWaitTime)s  CNAME=$($r.CNAMEPropTime)s  Kill=$($r.KillCount)/R$($r.KillRounds)  Err=$($r.AppErrors)  PostOps=$($r.PostOps)/s"
}
Write-Host "========================================"
