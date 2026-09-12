<#
.SYNOPSIS
  04 - CRUD 로그 실시간 확인 (cutover 전 정상 동작 확인용)

  kubectl logs -f 로 crud-worker Pod 를 스트리밍 출력.
  별도 터미널에서 이 스크립트를 켜둔 채 05-cutover.ps1 을 실행하면
  다운타임 시작/종료/duration 을 실시간으로 확인할 수 있음.

.USAGE
  .\04-watch-logs.ps1
#>
param()
$ErrorActionPreference = 'Continue'
$scriptDir = Split-Path $MyInvocation.MyCommand.Path

Write-Host "`n[04] crud-worker 로그 스트리밍 (Ctrl+C 로 중지)"
Write-Host "     ⚠ DOWNTIME START / ✅ RECOVERED 메시지를 주목하세요`n"

# 2개 replica 모두 출력 (--prefix 로 Pod 이름 구분)
kubectl logs -f -l app=crud-worker -n db-sim --prefix --max-log-requests=50
