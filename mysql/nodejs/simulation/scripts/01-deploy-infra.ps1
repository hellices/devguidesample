<#
.SYNOPSIS
  01 - Azure 리소스 배포 (VNet, AKS, MySQL old-db, Private Endpoint, Custom DNS Zone)

  new-db 는 이 스크립트에서 배포하지 않음.
  02b-setup-replication.ps1 에서 old-db 의 Read Replica 로 생성함.

.USAGE
  .\01-deploy-infra.ps1 -ResourceGroup "rg-dbsim" -Password "YourStr0ngP@ss!"
#>
param(
    [Parameter(Mandatory)][string]$ResourceGroup,
    [Parameter(Mandatory)][string]$Password,
    [string]$Location = "koreacentral",
    [string]$Prefix   = "dbsim"
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path $MyInvocation.MyCommand.Path
$bicepFile = Join-Path $scriptDir "..\infra\main.bicep"

Write-Host "`n[01] Resource Group 생성..."
az group create --name $ResourceGroup --location $Location --output none

Write-Host "[01] Bicep 배포 시작 (약 10-15분 소요)..."
$deploy = az deployment group create `
    --resource-group $ResourceGroup `
    --template-file $bicepFile `
    --parameters prefix=$Prefix location=$Location mysqlAdminPassword=$Password `
    --query "properties.outputs" `
    --output json | ConvertFrom-Json

# 출력값 저장 (후속 스크립트에서 재사용)
$outputs = @{
    aksName          = $deploy.aksName.value
    acrLoginServer   = $deploy.acrLoginServer.value
    acrName          = $deploy.acrName.value
    mysqlOldName     = $deploy.mysqlOldName.value
    mysqlNewName     = ""   # 02b-setup-replication.ps1 에서 설정됨
    mysqlOldFqdn     = $deploy.mysqlOldFqdn.value
    mysqlNewFqdn     = ""   # 02b-setup-replication.ps1 에서 설정됨
    privateDnsZoneName = $deploy.privateDnsZoneName.value
    customDnsZone    = $deploy.customDnsZone.value
    appFqdn          = $deploy.appFqdn.value
    dbName           = $deploy.dbName.value
    resourceGroup    = $ResourceGroup
    prefix           = $Prefix
    mysqlAdminUser   = "simadmin"
    appUser          = "appuser"
    appPassword      = "App@Pass2026!"
    password         = $Password
}
$outputs | ConvertTo-Json | Set-Content (Join-Path $scriptDir "sim-env.json")

Write-Host "[01] 완료. sim-env.json 저장됨."
Write-Host "  AKS     : $($outputs.aksName)"
Write-Host "  ACR     : $($outputs.acrLoginServer)"
Write-Host "  old-db  : $($outputs.mysqlOldName)"
Write-Host "  new-db  : (02b-setup-replication.ps1 실행 후 생성됨)"
