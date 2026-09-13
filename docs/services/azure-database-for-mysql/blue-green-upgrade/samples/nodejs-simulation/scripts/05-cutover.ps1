<#
.SYNOPSIS
  05 - Blue/Green Cutover: stop replication, CNAME switch, session kill

  Cutover phases (AWS Blue/Green equivalent on Azure):
    Phase 1  : SET GLOBAL super_read_only = ON on old-db  (block all writes)
    Phase 1W : Wait for replica lag = 0 on new-db         (SHOW REPLICA STATUS)
    Phase 1S : STOP REPLICA; RESET REPLICA ALL on new-db  (promote to standalone, instant)
    Phase 2  : CNAME change: primary -> new-db FQDN       (TTL=5s)
    Phase 2W : Wait for DNS propagation inside Pod        (max 30s)
    Phase 3  : KILL all app sessions on old-db            (force reconnect)
    Phase 4  : Verify new-db connection convergence       (max 30s)

  Run 04-watch-logs.ps1 in a separate terminal before executing this script.
  Look for: RECOVERED + "reconnected to DB server: {new-hostname}"

.USAGE
  .\05-cutover.ps1
#>
param()
$ErrorActionPreference = 'Continue'
$scriptDir = Split-Path $MyInvocation.MyCommand.Path
$e = Get-Content (Join-Path $scriptDir "sim-env.json") | ConvertFrom-Json
$rg        = $e.resourceGroup
$customZone = $e.customDnsZone   # "db.{prefix}.internal"
$appFqdn   = $e.appFqdn           # "primary.db.{prefix}.internal"
$oldFqdn   = $e.mysqlOldFqdn      # "{prefix}-old-db.mysql.database.azure.com"
$newFqdn   = $e.mysqlNewFqdn      # "{prefix}-new-db.mysql.database.azure.com"
$adminUser = $e.mysqlAdminUser    # 관리용 (processlist, session kill)
$appUser   = $e.appUser            # 앱 전용 (session kill 대상 필터)

function Log($phase, $msg) {
    $ts = (Get-Date).ToString("HH:mm:ss.fff")
    Write-Host "[$ts] [Phase $phase] $msg"
}

# ─── Ensure mysql-client-co pod is running ────────────────────────────────────
Write-Host "`n[05] Checking mysql-client-co pod..."
$existing = kubectl get pod mysql-client-co -n default --no-headers --ignore-not-found 2>$null
if (-not $existing) {
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
    kubectl wait pod/mysql-client-co --for=condition=Ready --timeout=120s
}

$pod = kubectl get pod -n db-sim -l app=crud-worker `
    --field-selector=status.phase=Running `
    -o jsonpath='{.items[0].metadata.name}' 2>$null
if (-not $pod) { Write-Error "No crud-worker pod found. Run 03-build-push.ps1 first."; exit 1 }

function Run-Sql($fqdn, $sql) {
    kubectl exec -n default mysql-client-co -- `
        mysql -h $fqdn -u $adminUser -p"$($e.password)" `
              --ssl-mode=REQUIRED -e $sql 2>&1
}

# ─── PRE: Current state ────────────────────────────────────────────────────────
Log "PRE" "DNS resolution check from Pod..."
kubectl exec -n db-sim $pod -- nslookup $appFqdn 2>&1 | Select-String -Pattern "Address:|canonical"

Log "PRE" "old-db processlist (app sessions)..."
Run-Sql $oldFqdn @"
SELECT id, user, host, command, time, state
FROM information_schema.processlist
WHERE user = '$appUser'
ORDER BY id;
"@

# ─── Phase 1: Block app on old-db ─────────────────────────────────────────────
# Azure MySQL Flexible Server 제약:
#   - super_read_only: az CLI / SQL 모두 변경 불가 (8.0 read-only parameter)
#   - KILL CONNECTION: CONNECTION_ADMIN 없어 다른 유저 세션 kill 불가
# 전략: REVOKE writes + ACCOUNT LOCK
#   1) REVOKE INSERT/UPDATE/DELETE → 기존 세션은 SELECT만 가능 (write 에러 유발)
#   2) ACCOUNT LOCK → Pool이 새 커넥션 시도 시 무조건 실패 (errorCount 단조 증가)
#   → removeNodeErrorCount(5) 도달 → 노드 offline → restoreNodeTimeout(3s) → DNS 재해석 → new-db
Log 1 "old-db: REVOKE writes + ACCOUNT LOCK on '$appUser'"
Run-Sql $oldFqdn @"
REVOKE INSERT, UPDATE, DELETE ON $($e.dbName).* FROM '${appUser}'@'%';
ALTER USER '${appUser}'@'%' ACCOUNT LOCK;
FLUSH PRIVILEGES;
"@
# 반영 확인
$grants = Run-Sql $oldFqdn "SHOW GRANTS FOR '${appUser}'@'%';" 2>&1
$locked = Run-Sql $oldFqdn "SELECT account_locked FROM mysql.user WHERE user='${appUser}';" 2>&1
Log 1 "Grants after revoke:"
$grants | ForEach-Object { Log 1 "  $_" }
Log 1 "Account locked: $($locked | Select-String 'Y')"
Start-Sleep 2

# ─── Phase 1W: Wait for replica lag = 0 (SHOW REPLICA STATUS) ─────────────────
Log "1W" "Waiting for SQL replication lag = 0 on new-db (max 60s)..."
$deadline   = (Get-Date).AddSeconds(60)
$lagZero    = $false
while ((Get-Date) -lt $deadline) {
    $status     = kubectl exec -n default mysql-client-co -- `
        mysql -h $e.mysqlNewFqdn -u $adminUser -p"$($e.password)" `
              --ssl-mode=REQUIRED -e "SHOW REPLICA STATUS\G" 2>&1
    $ioRunning  = ($status | Select-String "Replica_IO_Running:\s+Yes").Count -gt 0
    $sqlRunning = ($status | Select-String "Replica_SQL_Running:\s+Yes").Count -gt 0
    $lagLine    = $status | Select-String "Seconds_Behind_Source:" | Select-Object -Last 1
    $lagStr     = if ($lagLine) { ($lagLine -replace '.*Seconds_Behind_Source:\s*', '').Trim() } else { '?' }
    $ioStr  = if ($ioRunning)  { 'Yes' } else { 'No' }
    $sqlStr = if ($sqlRunning) { 'Yes' } else { 'No' }
    Log "1W" "  IO=$ioStr  SQL=$sqlStr  Lag=${lagStr}s"
    if ($ioRunning -and $sqlRunning -and ($lagStr -eq '0' -or $lagStr -eq 'NULL')) {
        $lagZero = $true
        Log "1W" "  Lag = 0. Safe to proceed."
        break
    }
    Start-Sleep 3
}
if (-not $lagZero) {
    Write-Warning "[Phase 1W] Lag not confirmed 0 within 60s. Proceeding anyway."
}

# ─── Phase 1S: Promote new-db (STOP REPLICA; RESET REPLICA ALL, instant) ──────────
Log "1S" "Promoting new-db: STOP REPLICA; RESET REPLICA ALL (standalone, instant)"
kubectl exec -n default mysql-client-co -- `
    mysql -h $e.mysqlNewFqdn -u $adminUser -p"$($e.password)" `
          --ssl-mode=REQUIRED -e "STOP REPLICA; RESET REPLICA ALL;" 2>&1 | Out-Null
Log "1S" "new-db is now standalone (replication stopped, ready for writes)."

# ─── Phase 2: CNAME change ────────────────────────────────────────────────────
$cutoverTs = Get-Date
Log 2 "Updating Custom DNS Zone CNAME: $customZone"
Log 2 "  primary: $oldFqdn -> $newFqdn"

az network private-dns record-set cname set-record `
    --resource-group $rg --zone-name $customZone `
    --record-set-name "primary" --cname $newFqdn --output none

Log 2 "CNAME updated (TTL=5s -> max 5s propagation)"

# ─── Phase 2W: Wait for DNS propagation inside Pod ────────────────────────────
Log "2W" "Waiting for DNS propagation inside Pod (max 30s)..."
$deadline = (Get-Date).AddSeconds(30)
$dnsOk = $false
while ((Get-Date) -lt $deadline) {
    $ns = kubectl exec -n db-sim $pod -- nslookup $appFqdn 2>&1
    if ($ns -match [regex]::Escape($e.mysqlNewName)) {
        Log "2W" "DNS propagated: $appFqdn -> $newFqdn"
        $dnsOk = $true
        break
    }
    $current = ($ns | Select-String "Address:" | Select-Object -Last 1)
    Log "2W" "Still propagating... (current: $current)"
    Start-Sleep 3
}
if (-not $dnsOk) { Log "2W" "WARNING: DNS not yet propagated - continuing (will converge after TTL)" }

# ─── Phase 3: Force-close all app sessions on old-db ─────────────────────────
# Azure MySQL admin 에 CONNECTION_ADMIN 없어 KILL CONNECTION 불가.
# → mysql.az_kill(id) stored procedure 사용 (Azure 전용, admin 권한으로 동작)
# Pod 내 bash 에서 SELECT id → CALL az_kill 생성 → 일괄 실행 (3 round retry)
# ACCOUNT LOCK (Phase 1) + az_kill → 기존 세션 강제 종료 + 새 로그인 차단
# → Pool 재연결 시 ER_ACCOUNT_HAS_BEEN_LOCKED → errorCount 증가 → DNS 재해석 → new-db
Log 3 "Killing all appuser sessions on old-db via mysql.az_kill() (batch, max 3 rounds)..."
$killTs = Get-Date
# bash 스크립트를 임시 파일 → kubectl cp → Pod에서 실행 (pipe/escape 문제 완전 회피)
# Literal here-string (@'...'@) → PowerShell 변수 확장 없음 → .Replace()로 치환
$scriptContent = @'
#!/bin/bash
MYSQL="mysql -h __OLD_FQDN__ -u __ADMIN__ -p__PASSWORD__ --ssl-mode=REQUIRED"
CNT=$($MYSQL -s -N -e "SELECT COUNT(*) FROM information_schema.processlist WHERE user='__APPUSER__'" 2>/dev/null)
echo FOUND:$CNT
if [ "$CNT" = "0" ]; then exit 0; fi
$MYSQL -s -N -e "SELECT id FROM information_schema.processlist WHERE user='__APPUSER__'" 2>/dev/null | while read id; do echo "CALL mysql.az_kill($id);"; done > /tmp/kill.sql
echo STMTS:$(wc -l < /tmp/kill.sql)
$MYSQL --force < /tmp/kill.sql 2>/dev/null
REMAINING=$($MYSQL -s -N -e "SELECT COUNT(*) FROM information_schema.processlist WHERE user='__APPUSER__'" 2>/dev/null)
echo REMAINING:$REMAINING
'@
$scriptContent = $scriptContent.Replace('__OLD_FQDN__', $oldFqdn).Replace('__ADMIN__', $adminUser).Replace('__PASSWORD__', $e.password).Replace('__APPUSER__', $appUser)
$tmpFile = Join-Path $scriptDir "kill_sessions_tmp.sh"
[IO.File]::WriteAllText($tmpFile, $scriptContent.Replace("`r`n","`n"), [Text.UTF8Encoding]::new($false))
Push-Location $scriptDir
$cpOut = kubectl cp "kill_sessions_tmp.sh" default/mysql-client-co:/tmp/kill_sessions.sh 2>&1
Pop-Location
if ($cpOut) { Log 3 "  kubectl cp output: $cpOut" }
Remove-Item $tmpFile -Force
kubectl exec -n default mysql-client-co -- chmod +x /tmp/kill_sessions.sh 2>&1 | Out-Null
for ($round = 1; $round -le 3; $round++) {
    $result = kubectl exec -n default mysql-client-co -- bash /tmp/kill_sessions.sh 2>&1
    $found = ($result | Select-String 'FOUND:' | ForEach-Object { ($_ -replace '.*FOUND:','').Trim() }) | Select-Object -First 1
    $stmts = ($result | Select-String 'STMTS:' | ForEach-Object { ($_ -replace '.*STMTS:','').Trim() }) | Select-Object -First 1
    $remain = ($result | Select-String 'REMAINING:' | ForEach-Object { ($_ -replace '.*REMAINING:','').Trim() }) | Select-Object -First 1
    Log 3 "  Round ${round}: found=$found  killed=$stmts  remaining=$remain"
    if ($found -eq '0' -or $remain -eq '0') {
        Log 3 "  All sessions cleared."
        break
    }
    if ($round -lt 3) { Start-Sleep 2 }
}

# ─── Phase 3V: Verify all app sessions drained from old-db ───────────────────
Log "3V" "Verifying app sessions drained from old-db (max 30s)..."
$deadline = (Get-Date).AddSeconds(30)
$drained = $false
while ((Get-Date) -lt $deadline) {
    $remaining = kubectl exec -n default mysql-client-co -- `
        mysql -h $oldFqdn -u $adminUser -p"$($e.password)" `
              --ssl-mode=REQUIRED -s -N `
              -e "SELECT COUNT(*) FROM information_schema.processlist WHERE user='$appUser';" 2>&1 |
        Select-Object -Last 1
    $remaining = ($remaining -replace '\D','').Trim()
    Log "3V" "  old-db appuser sessions: $remaining"
    if ($remaining -eq '0') {
        $drained = $true
        Log "3V" "  All app sessions cleared from old-db."
        break
    }
    Start-Sleep 2
}
if (-not $drained) {
    Log "3V" "WARNING: $remaining sessions still remain on old-db after 30s"
}

# ─── Phase 4: Verify convergence on new-db ───────────────────────────────────
Log 4 "Waiting for app connections to converge on new-db (max 30s)..."
$deadline = (Get-Date).AddSeconds(30)
$converged = $false
while ((Get-Date) -lt $deadline) {
    $cnt = kubectl exec -n default mysql-client-co -- `
        mysql -h $newFqdn -u $adminUser -p"$($e.password)" `
              --ssl-mode=REQUIRED -s -N `
              -e "SELECT COUNT(*) FROM information_schema.processlist WHERE user='$appUser';" 2>&1 |
        Select-Object -Last 1
    $cnt = $cnt.Trim()
    Log 4 "new-db app session count: $cnt"
    if ([int]$cnt -gt 0) {
        Log 4 "Converged on new-db."
        $converged = $true
        break
    }
    Start-Sleep 2
}

# ─── Summary ─────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "==========================================================="
Log "DONE" "Cutover complete"
Write-Host "  CNAME updated : $($cutoverTs.ToString('HH:mm:ss.fff'))"
Write-Host "  Session kill  : $($killTs.ToString('HH:mm:ss.fff'))"
Write-Host "  new-db convgd : $(if ($converged) {'YES'} else {'NOT CONFIRMED'})"
Write-Host ""
Write-Host "  Check 04-watch-logs terminal for:"
Write-Host "     RECOVERED + 'reconnected to DB server: {new-hostname}'"
Write-Host ""
Write-Host "  Verify writes landed on new-db:"
Run-Sql $newFqdn @"
SELECT id, item, server_name, created_at
FROM $($e.dbName).orders
ORDER BY id DESC LIMIT 10;
"@
Write-Host "==========================================================="
Write-Host ""
Write-Host "  To rollback: .\06-rollback-or-cleanup.ps1 -Rollback"
