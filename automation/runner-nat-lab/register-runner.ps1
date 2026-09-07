param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$ResourceGroup,
    [string]$VmName = 'vm-runner',
    [string]$Location = 'koreacentral'
)

$ErrorActionPreference = 'Stop'
$registration = gh api -X POST repos/hellices/devguidesample/actions/runners/registration-token |
    ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or !$registration.token) {
    throw 'Could not obtain a short-lived runner registration token.'
}
$access = az account get-access-token --subscription $SubscriptionId --resource https://management.azure.com/ |
    ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or !$access.accessToken) {
    throw 'Azure authentication failed.'
}
$headers = @{ Authorization = "Bearer $($access.accessToken)" }
$script = (Get-Content (Join-Path $PSScriptRoot 'register-runner.sh') -Raw).Replace("`r`n", "`n")
$body = @{
    location = $Location
    properties = @{
        source = @{ script = $script }
        protectedParameters = @(@{ name = 'registrationToken'; value = $registration.token })
        timeoutInSeconds = 600
    }
} | ConvertTo-Json -Depth 10
$resource = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Compute/virtualMachines/$VmName/runCommands/register-runner"
$null = Invoke-RestMethod -Method Put -Uri "${resource}?api-version=2025-04-01" `
    -Headers $headers -ContentType application/json -Body $body
$registration = $null
$body = $null
$deadline = (Get-Date).AddMinutes(12)
do {
    Start-Sleep -Seconds 10
    $result = Invoke-RestMethod -Uri "${resource}?api-version=2025-04-01&`$expand=instanceView" -Headers $headers
    $state = $result.properties.instanceView.executionState
    if ($state -in @('Failed', 'TimedOut', 'Canceled') -or $result.properties.provisioningState -eq 'Failed') {
        throw "Registration failed: $($result.properties.instanceView | ConvertTo-Json -Compress)"
    }
    if ((Get-Date) -gt $deadline) {
        throw "Timed out waiting for runner registration. Last state: $state"
    }
} until ($state -eq 'Succeeded')
if ($result.properties.instanceView.exitCode -ne 0) {
    throw "Registration exited with code $($result.properties.instanceView.exitCode)."
}
$result.properties.instanceView | Select-Object executionState, exitCode, startTime, endTime, output, error
