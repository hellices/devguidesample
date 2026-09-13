<#
.SYNOPSIS
  06 - 롤백 또는 정리

  -Rollback  : DNS 원복 + super_read_only OFF
  -Cleanup   : 모든 Azure 리소스 삭제 (Resource Group 통째로)

.USAGE
  .\06-rollback-or-cleanup.ps1 -Rollback
  .\06-rollback-or-cleanup.ps1 -Cleanup
#>
param(
    [switch]$Rollback,
    [switch]$Cleanup
)
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path $MyInvocation.MyCommand.Path
$simEnv = Get-Content (Join-Path $scriptDir "sim-env.json") | ConvertFrom-Json
$rg = $simEnv.resourceGroup
$customZone = $simEnv.customDnsZone   # "db.{prefix}.internal"
$oldFqdn    = $simEnv.mysqlOldFqdn

if ($Rollback) {
    Write-Host "`n[06-Rollback] Custom DNS Zone CNAME 원복: primary → $oldFqdn"
    # set-record 는 멱등 — 현재 CNAME 값에 무관하게 덮어씀
    az network private-dns record-set cname set-record `
        --resource-group $rg --zone-name $customZone `
        --record-set-name "primary" --cname $oldFqdn --output none
    Write-Host "  DNS 원복 완료 → primary.$customZone = $oldFqdn"

    Write-Host "[06-Rollback] old-db appuser UNLOCK + GRANT 복원"
    $adminUser = $simEnv.mysqlAdminUser
    $appUser   = $simEnv.appUser
    $dbName    = $simEnv.dbName
    kubectl exec -n default mysql-client-co -- `
        mysql -h $oldFqdn -u $adminUser -p"$($simEnv.password)" `
              --ssl-mode=REQUIRED `
              -e "ALTER USER '${appUser}'@'%' ACCOUNT UNLOCK; GRANT SELECT, INSERT, UPDATE, DELETE ON ${dbName}.* TO '${appUser}'@'%'; FLUSH PRIVILEGES;" 2>&1 | Out-Null

    Write-Host "[06-Rollback] 완료."
    Write-Host "  ⚠ cutover 이후 new-db 에 write 가 발생했다면 데이터 동기화 필요."
}

if ($Cleanup) {
    Write-Host "`n[06-Cleanup] Resource Group '$rg' 전체 삭제 (되돌릴 수 없음)"
    $confirm = Read-Host "정말 삭제하시겠습니까? (yes 입력)"
    if ($confirm -ne "yes") { Write-Host "취소됨."; exit 0 }

    Write-Host "[06-Cleanup] 삭제 중..."
    az group delete --name $rg --yes --no-wait
    Write-Host "[06-Cleanup] 백그라운드 삭제 요청 완료."
}

if (-not $Rollback -and -not $Cleanup) {
    Write-Host "사용법:"
    Write-Host "  .\06-rollback-or-cleanup.ps1 -Rollback   # DNS 원복 + read_only OFF"
    Write-Host "  .\06-rollback-or-cleanup.ps1 -Cleanup    # Azure 리소스 전체 삭제"
}
