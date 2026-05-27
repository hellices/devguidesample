<#
.SYNOPSIS
  03 - App 이미지 빌드 → ACR Push → AKS rollout restart

  ACR Task 를 사용하므로 로컬 Docker 불필요.
  app/ 디렉터리 전체를 az acr build 로 클라우드 빌드.

.USAGE
  .\03-build-push.ps1
#>
param()
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path $MyInvocation.MyCommand.Path
$env = Get-Content (Join-Path $scriptDir "sim-env.json") | ConvertFrom-Json

$appDir = (Resolve-Path (Join-Path $scriptDir "..\app")).Path

Write-Host "`n[03] ACR 빌드 & ACR attach 병렬 실행..."
Write-Host "  Source : $appDir"
Write-Host "  ACR    : $($env.acrLoginServer)"

# az acr build 와 az aks update --attach-acr 는 서로 무관 (attach-acr = AKS managed identity에 pull 권한 부여)
$jobBuild = Start-Job -Name "ACRBuild" -ScriptBlock {
    param($acrName, $rg, $appDir)
    az acr build `
        --registry $acrName `
        --resource-group $rg `
        --image "db-sim-app:latest" `
        --file "$appDir\Dockerfile" `
        $appDir 2>&1
} -ArgumentList $env.acrName, $env.resourceGroup, $appDir

$jobAttach = Start-Job -Name "ACRAttach" -ScriptBlock {
    param($aksName, $rg, $acrName)
    az aks update `
        --name $aksName `
        --resource-group $rg `
        --attach-acr $acrName `
        --output none 2>&1
} -ArgumentList $env.aksName, $env.resourceGroup, $env.acrName

Write-Host "[03] 빌드 + attach 완료 대기..."
$jobBuild, $jobAttach | Wait-Job | Out-Null
foreach ($job in $jobBuild, $jobAttach) {
    $out = Receive-Job $job
    if ($out) { $out | ForEach-Object { Write-Host "  [$($job.Name)] $_" } }
    if ($job.State -eq 'Failed') { throw "[$($job.Name)] 실패 - 위 출력 확인" }
}
$jobBuild, $jobAttach | Remove-Job

Write-Host "[03] Deployment rollout restart..."
kubectl rollout restart deployment/crud-worker -n db-sim
kubectl rollout status deployment/crud-worker -n db-sim --timeout=120s

Write-Host "`n[03] 완료. Pod 상태:"
kubectl get pods -n db-sim -o wide
