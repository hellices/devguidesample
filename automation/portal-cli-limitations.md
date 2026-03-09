# Azure Automation - 포탈/CLI 제한사항 및 우회 방법

> 작성일: 2026-03-08  
> 대상: Automation Account `autorecovery` (RG: `rg-hellices-krc-01`)

---

## 0. 변수 정의

아래 코드 블록의 변수들을 먼저 설정한 후, 이후 모든 명령에서 재사용합니다.

```powershell
$rg             = ""        # 리소스 그룹
$aaName         = ""              # Automation Account 이름
$runbookName    = ""            # Runbook 이름
$runbookType    = "PowerShell"                # Runbook 타입
$location       = ""              # 리전
$scheduleName   = ""             # 스케줄 이름
$startTime      = "2026-03-09T22:00:00+00:00" # 시작 시간 (UTC) → KST 07:00
$timeZone       = "Korea Standard Time"        # 타임존
$scriptPath     = "./your-script.ps1"          # 업로드할 스크립트 경로
```

---

## 1. Runbook 생성 및 게시 (Publish)

### 문제 상황

- **Portal**: Runbook 생성 후 **Publish 버튼 클릭 시 반응 없음** (DevTools 콘솔에 아래 오류 출력)
  ```
  Uncaught (in promise) TypeError: Cannot read properties of null (reading 'name')
      at S91GJuDpLXzD.js:1:2945472
      at onYesClicked (S91GJuDpLXzD.js:1:2949145)
  
  [Microsoft_Azure_Automation] ReactInternalErrorHandler
  Cannot read properties of null (reading 'name')
  Unhandled Promise Rejection
  ```

### 원인 분석

- Azure Portal의 Automation 블레이드 내부 React 컴포넌트 버그로, `name` 프로퍼티가 null인 객체를 참조하면서 발생
- 브라우저 캐시 삭제, InPrivate/시크릿 모드에서도 동일 증상 재현

### 해결 방법: Azure CLI

```powershell
# Runbook 생성
az automation runbook create `
  --resource-group $rg `
  --automation-account-name $aaName `
  --name $runbookName `
  --type $runbookType `
  --location $location

# 스크립트 업로드
az automation runbook replace-content `
  --resource-group $rg `
  --automation-account-name $aaName `
  --name $runbookName `
  --content @$scriptPath

# 게시 (Publish)
az automation runbook publish `
  --resource-group $rg `
  --automation-account-name $aaName `
  --name $runbookName
```

---

## 2. 스케줄 생성

### 문제 상황

- **Portal**: 스케줄 생성은 가능하나 타임존 설정이 직관적이지 않음
- **CLI**: `az automation schedule create`는 정상 동작

### 해결 방법: Azure CLI

```powershell
az automation schedule create `
  --resource-group $rg `
  --automation-account-name $aaName `
  --name $scheduleName `
  --start-time $startTime `
  --frequency Day `
  --interval 1 `
  --time-zone $timeZone `
  --description "매일 한국시간 오전 7시 실행"
```

> **참고**: KST 오전 7시 = UTC 전날 22:00. `--time-zone`에 `"Korea Standard Time"` 지정 시 실제 저장은 `Asia/Seoul`로 됨.

---

## 3. 스케줄 ↔ Runbook 연동 (Job Schedule)

### 문제 상황

- **Portal**: Runbook 상세 → "스케줄 연결" UI에서 연동 실패 또는 버튼 미반응 (Publish와 동일한 React 내부 오류 발생 가능)
- **CLI**: `az automation job-schedule` 명령 자체가 존재하지 않음 (2026-03 기준)
- **CLI**: `az automation runbook schedule create`도 미지원 (`schedule`은 인식되지 않는 하위 명령)
- **PowerShell Az 모듈**: `Register-AzAutomationScheduledRunbook`은 동작하지만 별도 `Connect-AzAccount` 인증 필요 (CLI 인증과 별개)

### 해결 방법 1: Azure REST API (권장)

CLI 토큰을 재사용하여 REST API로 직접 호출 가능.

```powershell
# 1) CLI에서 토큰 및 구독 ID 획득
$token = az account get-access-token --query accessToken -o tsv
$subscriptionId = az account show --query id -o tsv
$jobScheduleId = [guid]::NewGuid().ToString()

# 2) REST API 호출
$uri = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$rg/providers/Microsoft.Automation/automationAccounts/$aaName/jobSchedules/$($jobScheduleId)?api-version=2023-11-01"

$body = @{
    properties = @{
        schedule = @{ name = $scheduleName }
        runbook  = @{ name = $runbookName }
    }
} | ConvertTo-Json -Depth 5

$headers = @{
    Authorization  = "Bearer $token"
    "Content-Type" = "application/json"
}

Invoke-RestMethod -Uri $uri -Method PUT -Headers $headers -Body $body
```

### 해결 방법 2: PowerShell Az 모듈

별도 인증(`Connect-AzAccount`)이 필요하지만 명령이 간결함.

```powershell
# 인증 (MFA 등 대화형 로그인 필요)
Connect-AzAccount -TenantId "your-tenant-id"

# 연동
Register-AzAutomationScheduledRunbook `
  -ResourceGroupName $rg `
  -AutomationAccountName $aaName `
  -RunbookName $runbookName `
  -ScheduleName $scheduleName
```

---

## 4. 연동 확인 방법

### REST API로 확인

```powershell
$token = az account get-access-token --query accessToken -o tsv
$subscriptionId = az account show --query id -o tsv

$uri = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$rg/providers/Microsoft.Automation/automationAccounts/$aaName/jobSchedules?api-version=2023-11-01"

$headers = @{ Authorization = "Bearer $token" }

(Invoke-RestMethod -Uri $uri -Headers $headers).value | ForEach-Object {
    [PSCustomObject]@{
        Runbook  = $_.properties.runbook.name
        Schedule = $_.properties.schedule.name
        Id       = $_.properties.jobScheduleId
    }
} | Format-Table
```

### 스케줄 확인 (CLI)

```powershell
az automation schedule show `
  --resource-group $rg `
  --automation-account-name $aaName `
  --schedule-name $scheduleName `
  -o table
```

---

## 요약

| 작업 | Portal | CLI (`az`) | REST API | PowerShell Az 모듈 |
|------|--------|-----------|----------|-------------------|
| Runbook 생성 | X (React 내부 오류: `Cannot read properties of null (reading 'name')`) | **O** | O | O |
| Runbook Publish | X (버튼 무반응, 동일 오류) | **O** (`az automation runbook publish`) | O | O |
| 스케줄 생성 | △ (타임존 불편) | **O** | O | O |
| 스케줄 ↔ Runbook 연동 | X (UI 오류) | **X** (명령 미지원) | **O (권장)** | O (별도 인증 필요) |
| 연동 상태 확인 | △ | X (명령 미지원) | **O** | O |

## 참고 링크

- [Azure Automation Runbook 관리](https://learn.microsoft.com/ko-kr/azure/automation/manage-runbooks)
- [az automation runbook CLI 참조](https://learn.microsoft.com/ko-kr/cli/azure/automation/runbook)
- [Azure Automation REST API 참조](https://learn.microsoft.com/ko-kr/rest/api/automation/)
