<#
.SYNOPSIS
    Adaptive TPM Quota Controller (PowerShell / Azure Automation) — OPTIONAL 대체 구현

.DESCRIPTION
    Python 런북(adaptive_tpm_quota_controller.py)과 **동일한 제어 로직**을 PowerShell(Az 모듈)로
    이식한 "선택적(optional) 대체 구현"이다. 기본 구현은 Python 런북이며, 본 스크립트는
    PowerShell 선호 환경을 위한 동등 참조본이다.

    [Python 버전과의 동등성 — 핵심 설계 결정]
    * 두 배포 capacity 의 합은 Reservation 한 총량(ReservedTotalTpm)을 어떤 시점에도
      초과할 수 없다. 고정된 Reserved 총량을 트래픽 비율에 맞춰 재분배한다:
        - 필요량 합 ≤ 총량  → 각자 need 만 배정(나머지는 미할당 버퍼)
        - 필요량 합 > 총량  → 소비 TPM 비율로 비례 배분(경합)
    * 감축 먼저, 증설 나중: 총량이 꽉 찬 상태에서 증설을 먼저 하면 실패하므로,
      잉여 리전을 먼저 감축해 headroom 을 확보한 뒤 증설한다(loss 최소화).
    * 리전 최소 보장(MinCapacity)은 Reserved 총량의 25% 로 유지한다.
    * capacity(배포 SKU capacity) 를 조정 knob 으로 직접 사용. 1 unit ≈ TpmPerCapacityUnit.
    * 실제 actuation: Az.CognitiveServices 로 배포 SKU capacity 를 실제 갱신(폐루프).
    * 쿨다운: ScaleAction 이력에서 리전별 마지막 실제 변경 시각을 확인해 재조정 차단.

.NOTES
    [인증 / 의존 모듈]
    * 인증: 관리 ID  ->  Connect-AzAccount -Identity   (로컬은 Connect-AzAccount 로 로그인)
    * 필요 모듈: Az.Accounts, Az.CognitiveServices, AzTable
    * 필요 RBAC:
        - Storage: "Storage Table Data Contributor"       (TrafficWindow 읽기 / 이력 쓰기)
        - Foundry: "Cognitive Services Contributor"        (배포 capacity 갱신)

    [네트워크 주의]
    * Storage 가 publicNetworkAccess=Disabled + Private Endpoint 구성인 경우, 이 런북도
      프라이빗 경로가 닿는 곳(예: Hybrid Runbook Worker)에서 실행되어야 테이블에 접근된다.
      (Linux Hybrid Worker 에는 PowerShell 이 기본 설치되어 있지 않을 수 있으므로,
       PowerShell 로 운영하려면 Windows Hybrid Worker 를 사용)

.EXAMPLE
    .\optional_adaptive_tpm_quota_controller.ps1 -DryRun     # 계산/기록만

.EXAMPLE
    .\optional_adaptive_tpm_quota_controller.ps1             # 실제 조정
#>

param(
    # --- 대상 리소스 -------------------------------------------------------------
    [string]$SubscriptionId = "2cf925b6-80cb-4567-abda-5ccd3010aab5",
    [string]$ResourceGroup = "ptu-lb",
    [string]$StorageAccountName = "ptulb59018sa",

    [string]$TrafficTable = "TrafficWindow",
    [string]$DecisionTable = "ControlDecision",
    [string]$ActionTable = "ScaleAction",

    # --- 제어 파라미터 (Python 버전 상수와 동일) --------------------------------
    [int]$MetricWindowMinutes = 5,       # TrafficWindow 1건이 대표하는 시간(분)
    [int]$SmoothingWindows = 3,          # 이동평균에 사용할 최근 윈도우 개수
    [int]$TpmPerCapacityUnit = 1000,     # capacity 1 unit ≈ 1000 TPM (운영값으로 조정)

    [double]$TargetUtilHigh = 0.75,      # 초과 시 증설 압력
    [double]$TargetUtilLow = 0.30,       # 미만 시 감축(잉여 회수)
    [double]$AimUtil = 0.60,             # 조정 후 목표 사용률(중간값)

    [int]$MaxStepUnits = 5,              # 1회 조정 최대 capacity 변경폭(단위)
    [int]$ReservedTotalTpm = 20000,      # Reservation 한 총 TPM 상한(합산 불변)
    [double]$MinCapacityRatio = 0.25,    # 리전별 최소 보장 = Reserved 총량의 25%
    [int]$CooldownMinutes = 20,          # 실제 조정 후 재조정 금지 시간(분)

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# --- Reserved 총량 파생값 (합산 불변식의 기준) ---------------------------------
$TotalCapacityUnits = [int]($ReservedTotalTpm / $TpmPerCapacityUnit)                          # =20
$MinCapacity = [int][math]::Max(1, [math]::Ceiling($TotalCapacityUnits * $MinCapacityRatio))  # =5
$MaxCapacity = $TotalCapacityUnits - $MinCapacity                                             # =15 (2리전 가정)

# 리전 -> Foundry 계정/배포 매핑 (Reserved 총량을 두 리전이 공유)
$Regions = [ordered]@{
    korea = @{ Account = "ptufoundrykr001"; Deployment = "tpmtest-kr" }
    uk    = @{ Account = "ptufoundryuk001"; Deployment = "tpmtest-uk" }
}

# ---------------------------------------------------------------------------
# 인증 + 테이블 컨텍스트
# ---------------------------------------------------------------------------

function Connect-Context {
    # Azure Automation: 시스템 할당 관리 ID. 로컬: 이미 로그인된 컨텍스트가 있으면 재사용.
    if (-not (Get-AzContext)) {
        try {
            Connect-AzAccount -Identity -Subscription $SubscriptionId | Out-Null
        }
        catch {
            Connect-AzAccount -Subscription $SubscriptionId | Out-Null
        }
    }
    Set-AzContext -Subscription $SubscriptionId | Out-Null
}

function Get-CloudTable {
    param([string]$TableName)
    # 공유키 없이 Entra(RBAC) 자격으로 접근
    $ctx = New-AzStorageContext -StorageAccountName $StorageAccountName -UseConnectedAccount
    return (Get-AzStorageTable -Name $TableName -Context $ctx).CloudTable
}

function Clamp {
    param([int]$Value, [int]$Min, [int]$Max)
    return [math]::Min([math]::Max($Value, $Min), $Max)
}

# ---------------------------------------------------------------------------
# 메트릭 조회
# ---------------------------------------------------------------------------

function Get-RecentWindows {
    param([string]$Region, [int]$Limit)

    $table = Get-CloudTable -TableName $TrafficTable
    $rows = Get-AzTableRow -Table $table -CustomFilter "PartitionKey eq '$Region'"
    if (-not $rows) { return @() }

    # RowKey 는 ISO8601 타임스탬프 문자열이므로 문자열 정렬 = 시간 정렬
    return @($rows | Sort-Object -Property RowKey -Descending | Select-Object -First $Limit)
}

function Get-AvgConsumedTpm {
    param([array]$Rows)
    # 윈도우별 (inputTokens+outputTokens)/window_minutes 의 평균(분당 소비 TPM)
    if ($Rows.Count -eq 0) { return 0.0 }

    $total = 0.0
    foreach ($r in $Rows) {
        $tokens = [double]($r.inputTokens) + [double]($r.outputTokens)
        $total += $tokens / $MetricWindowMinutes
    }
    return [math]::Round($total / $Rows.Count, 2)
}

# ---------------------------------------------------------------------------
# 배포 capacity 조회/갱신 (실제 actuation)
# ---------------------------------------------------------------------------

function Get-DeploymentCapacity {
    param([string]$Account, [string]$Deployment)
    $dep = Get-AzCognitiveServicesAccountDeployment `
        -ResourceGroupName $ResourceGroup -AccountName $Account -Name $Deployment
    return [int]$dep.Sku.Capacity
}

function Set-DeploymentCapacity {
    param([string]$Account, [string]$Deployment, [int]$Capacity)
    # 기존 배포의 model/properties 는 유지하고 SKU capacity 만 갱신(create-or-update)
    $existing = Get-AzCognitiveServicesAccountDeployment `
        -ResourceGroupName $ResourceGroup -AccountName $Account -Name $Deployment
    $sku = New-Object 'Microsoft.Azure.Management.CognitiveServices.Models.Sku' `
        -ArgumentList $existing.Sku.Name, $null, $null, $Capacity, $null
    New-AzCognitiveServicesAccountDeployment `
        -ResourceGroupName $ResourceGroup -AccountName $Account -Name $Deployment `
        -Properties $existing.Properties -Sku $sku | Out-Null
}

# ---------------------------------------------------------------------------
# 쿨다운 체크
# ---------------------------------------------------------------------------

function Test-InCooldown {
    param([string]$Region, [datetime]$Now)

    $table = Get-CloudTable -TableName $ActionTable
    $actions = Get-AzTableRow -Table $table -CustomFilter "region eq '$Region'"
    if (-not $actions) { return $false }

    # 실제 capacity 가 바뀐(changed=true) 액션만 대상으로 최신 것을 찾는다
    $changed = @($actions | Where-Object { "$($_.changed)".ToLower() -eq "true" })
    if ($changed.Count -eq 0) { return $false }

    $last = $changed | Sort-Object -Property TableTimestamp -Descending | Select-Object -First 1
    $elapsedMin = ($Now.ToUniversalTime() - $last.TableTimestamp.UtcDateTime).TotalMinutes
    return ($elapsedMin -lt $CooldownMinutes)
}

# ---------------------------------------------------------------------------
# 공유 상한(Reserved quota) 재분배 로직
# ---------------------------------------------------------------------------

function Get-NeedCapacity {
    param([double]$ConsumedTpm)
    if ($ConsumedTpm -le 0) { return $MinCapacity }
    $raw = [int][math]::Ceiling($ConsumedTpm / ($AimUtil * $TpmPerCapacityUnit))
    return (Clamp -Value $raw -Min $MinCapacity -Max $MaxCapacity)
}

function Get-Targets {
    # $States: 각 원소 = @{ Region; Account; Deployment; Current; Consumed; Utilization }
    param([array]$States)

    $needs = @{}
    foreach ($s in $States) { $needs[$s.Region] = Get-NeedCapacity -ConsumedTpm $s.Consumed }
    $totalNeed = ($needs.Values | Measure-Object -Sum).Sum

    if ($totalNeed -le $TotalCapacityUnits) {
        # 여유 있음: 필요량만 배정, 나머지는 미할당 버퍼(증설은 무손실)
        return @{ Targets = $needs; Contention = $false }
    }

    # 경합: MIN 을 먼저 보장하고 남은 용량을 소비 TPM 비율로 배분
    $n = $States.Count
    $rem = $TotalCapacityUnits - ($n * $MinCapacity)
    $totalConsumed = ($States | ForEach-Object { [math]::Max($_.Consumed, 0.0) } | Measure-Object -Sum).Sum
    if ($totalConsumed -le 0) { $totalConsumed = 1.0 }

    $targets = @{}
    foreach ($s in $States) {
        $extra = [int][math]::Floor($rem * [math]::Max($s.Consumed, 0.0) / $totalConsumed)
        $targets[$s.Region] = Clamp -Value ($MinCapacity + $extra) -Min $MinCapacity -Max $MaxCapacity
    }
    # 내림으로 남은 잔여 unit 을 소비가 큰 리전부터 채운다(합이 TOTAL 을 넘지 않게)
    $leftover = $TotalCapacityUnits - ($targets.Values | Measure-Object -Sum).Sum
    foreach ($s in ($States | Sort-Object -Property Consumed -Descending)) {
        while ($leftover -gt 0 -and $targets[$s.Region] -lt $MaxCapacity) {
            $targets[$s.Region] += 1
            $leftover -= 1
        }
    }
    return @{ Targets = $targets; Contention = $true }
}

function Get-RegionPlan {
    param([hashtable]$State, [int]$Target, [bool]$Contention)

    $util = $State.Utilization
    $withinBand = ($util -ge $TargetUtilLow -and $util -le $TargetUtilHigh)
    if ($withinBand -and -not $Contention) {
        # 편안한 구간이고 경합도 없음 → 불필요한 왕복(churn) 방지 위해 유지
        return @{ Decision = "hold"; Planned = $State.Current; Reason = "util $([math]::Round($util*100,2))% in dead-band" }
    }

    $delta = Clamp -Value ([int]($Target - $State.Current)) -Min (-$MaxStepUnits) -Max $MaxStepUnits
    $planned = $State.Current + $delta
    $tag = "util $([math]::Round($util*100,2))% -> target $Target (contention=$Contention)"
    if ($planned -gt $State.Current) { return @{ Decision = "up"; Planned = $planned; Reason = $tag } }
    if ($planned -lt $State.Current) { return @{ Decision = "down"; Planned = $planned; Reason = $tag } }
    return @{ Decision = "hold"; Planned = $State.Current; Reason = "util $([math]::Round($util*100,2))% bounded, no change" }
}

# ---------------------------------------------------------------------------
# 이력 기록
# ---------------------------------------------------------------------------

function New-RowKey {
    param([datetime]$Now, [string]$Region)
    return "$($Now.ToString('yyyyMMddTHHmmssffffff'))-$Region-$([guid]::NewGuid().ToString('N').Substring(0,8))"
}

function Write-Decision {
    param([datetime]$Now, [hashtable]$Res)
    $table = Get-CloudTable -TableName $DecisionTable
    Add-AzTableRow -Table $table `
        -PartitionKey $Now.ToString('yyyyMMdd') -RowKey (New-RowKey -Now $Now -Region $Res.Region) `
        -Property @{
            region         = $Res.Region
            utilization    = $Res.Utilization
            avgConsumedTpm = $Res.AvgConsumedTpm
            capacityBefore = $Res.CurrentCapacity
            capacityTarget = $Res.Target
            decision       = $Res.Decision
            reason         = $Res.Reason
            cooldownBlocked = $Res.CooldownBlocked
            executed       = $Res.Executed
        } | Out-Null
}

function Write-Action {
    param([datetime]$Now, [hashtable]$Res, [int]$DurationMs)
    $table = Get-CloudTable -TableName $ActionTable
    $changed = ($Res.Executed -and ($Res.Target -ne $Res.CurrentCapacity))
    Add-AzTableRow -Table $table `
        -PartitionKey $Now.ToString('yyyyMMdd') -RowKey (New-RowKey -Now $Now -Region $Res.Region) `
        -Property @{
            region         = $Res.Region
            requestPayload = "$($Res.Region) capacity $($Res.CurrentCapacity) to $($Res.Target)"
            capacityBefore = $Res.CurrentCapacity
            capacityTarget = $Res.Target
            changed        = $changed
            responseStatus = if ($Res.Error) { 500 } else { 200 }
            success        = [string]::IsNullOrEmpty($Res.Error)
            errorMessage   = $Res.Error
            durationMs     = $DurationMs
        } | Out-Null
}

# ---------------------------------------------------------------------------
# 메인 제어 사이클
# ---------------------------------------------------------------------------

Connect-Context
$now = (Get-Date).ToUniversalTime()

# --- Phase 1: 상태 수집 (리전별 현재 capacity + 이동평균 사용률) ---------------
$states = @()
foreach ($region in $Regions.Keys) {
    $cfg = $Regions[$region]
    $current = Get-DeploymentCapacity -Account $cfg.Account -Deployment $cfg.Deployment
    $rows = Get-RecentWindows -Region $region -Limit $SmoothingWindows
    $consumed = Get-AvgConsumedTpm -Rows $rows
    $provisioned = $current * $TpmPerCapacityUnit
    $util = if ($provisioned -gt 0) { [math]::Round($consumed / $provisioned, 4) } else { 0.0 }
    $states += @{
        Region = $region; Account = $cfg.Account; Deployment = $cfg.Deployment
        Current = $current; Consumed = $consumed; Utilization = $util
    }
}

# --- Phase 2: 목표 산출(총량 제약) + dead-band/스텝/쿨다운 완충 ----------------
$alloc = Get-Targets -States $states
$targets = $alloc.Targets
$contention = $alloc.Contention

$results = @{}
$plannedMap = @{}
$durations = @{}
foreach ($s in $states) {
    $p = Get-RegionPlan -State $s -Target ([int]$targets[$s.Region]) -Contention $contention
    $decision = $p.Decision
    $planned = $p.Planned
    $reason = $p.Reason

    $cooldownBlocked = $false
    if ($decision -ne "hold" -and (Test-InCooldown -Region $s.Region -Now $now)) {
        $cooldownBlocked = $true
        $planned = $s.Current
        $decision = "hold"
        $reason = "$reason | blocked by cooldown"
    }

    $plannedMap[$s.Region] = $planned
    $durations[$s.Region] = 0
    $results[$s.Region] = @{
        Region = $s.Region; Account = $s.Account; Deployment = $s.Deployment
        AvgConsumedTpm = $s.Consumed; CurrentCapacity = $s.Current; Utilization = $s.Utilization
        Decision = $decision; Target = $planned; Reason = $reason
        CooldownBlocked = $cooldownBlocked; Executed = $false; Contention = $contention; Error = ""
    }
}

# --- Phase 3: 총량 제약 실행 (감축 먼저 → 증설은 남은 headroom 한도) -----------
$free = $TotalCapacityUnits - (($states | ForEach-Object { $_.Current } | Measure-Object -Sum).Sum)

function Invoke-Apply {
    param([hashtable]$St, [hashtable]$Res, [int]$NewCap)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        if (-not $DryRun) {
            Set-DeploymentCapacity -Account $St.Account -Deployment $St.Deployment -Capacity $NewCap
        }
        $Res.Target = $NewCap
        $Res.Executed = ((-not $DryRun) -and ($NewCap -ne $St.Current))
    }
    catch {
        $msg = "$($_.Exception.Message)"
        $Res.Error = $msg.Substring(0, [math]::Min(500, $msg.Length))
        $Res.Target = $St.Current
    }
    $sw.Stop()
    return [int]$sw.ElapsedMilliseconds
}

# 3-1) 감축(donor) 먼저 → headroom 확보 (여유 리전에서 회수, loss 없음)
foreach ($s in $states) {
    $res = $results[$s.Region]
    $planned = $plannedMap[$s.Region]
    if (-not $res.CooldownBlocked -and $planned -lt $s.Current) {
        $durations[$s.Region] = Invoke-Apply -St $s -Res $res -NewCap $planned
        if (-not $res.Error) { $free += ($s.Current - $res.Target) }
    }
}

# 3-2) 증설(recipient): 사용률 높은 리전부터, 남은 headroom 한도로만
foreach ($s in ($states | Sort-Object -Property Utilization -Descending)) {
    $res = $results[$s.Region]
    $planned = $plannedMap[$s.Region]
    if ($res.CooldownBlocked -or $planned -le $s.Current) { continue }
    $inc = [math]::Min($planned - $s.Current, $free)
    if ($inc -le 0) {
        $res.Decision = "hold"
        $res.Reason = "$($res.Reason) | no headroom (Reserved 총량 소진)"
        continue
    }
    $newCap = $s.Current + $inc
    $durations[$s.Region] = Invoke-Apply -St $s -Res $res -NewCap $newCap
    if (-not $res.Error) {
        $free -= ($res.Target - $s.Current)
        if ($res.Target -lt $planned) { $res.Reason = "$($res.Reason) | headroom-limited to $($res.Target)" }
    }
}

# --- Phase 4: 이력 기록 ------------------------------------------------------
$results_ordered = @()
foreach ($s in $states) {
    $res = $results[$s.Region]
    Write-Decision -Now $now -Res $res
    Write-Action -Now $now -Res $res -DurationMs $durations[$s.Region]
    $results_ordered += $res
}
$results = $results_ordered

Write-Output "=== Adaptive TPM Quota Controller (PowerShell, dryRun=$DryRun) ==="
$totalAfter = 0
foreach ($r in $results) {
    $totalAfter += $r.Target
    $line = "[$($r.Region)] consumedTpm=$($r.AvgConsumedTpm) capacity=$($r.CurrentCapacity)->$($r.Target) " +
            "util=$([math]::Round($r.Utilization*100,2))% decision=$($r.Decision) contention=$($r.Contention) " +
            "cooldown=$($r.CooldownBlocked) executed=$($r.Executed) reason='$($r.Reason)'"
    if ($r.Error) { $line += " error='$($r.Error)'" }
    Write-Output $line
}
Write-Output "total capacity after=$totalAfter/$TotalCapacityUnits (Reserved cap)"
