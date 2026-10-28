#!/usr/bin/env bash
# Installs scripts/vm/load.ps1 on the SQL VM and starts one demo workload in the
# background as a scheduled task. Several modes can run at the same time.
#
# Usage: scripts/generate-load.sh [cpu|blocking|longrun|badlogin|growth] [minutes]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

MODE="${1:-cpu}"
MINUTES="${2:-15}"
[[ "$MODE" =~ ^(cpu|blocking|longrun|badlogin|growth)$ ]] || { echo "mode must be cpu, blocking, longrun, badlogin, or growth" >&2; exit 1; }
[[ "$MINUTES" =~ ^[0-9]+$ ]] || { echo "minutes must be an integer" >&2; exit 1; }
MINUTES=$((10#$MINUTES))
LOAD_B64="$(base64 < "$SAMPLE_DIR/scripts/vm/load.ps1" | tr -d '\n')"

# A scheduled task keeps the workload running after Run Command returns.
SCRIPT=$(cat <<EOF2
New-Item -ItemType Directory -Path 'C:\SreLab' -Force | Out-Null
[IO.File]::WriteAllBytes('C:\SreLab\load.ps1', [Convert]::FromBase64String('${LOAD_B64}'))
\$task = 'SreDemoLoad-${MODE}'
\$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\SreLab\load.ps1 -Mode ${MODE} -Minutes ${MINUTES}'
\$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
\$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes $((MINUTES + 5)))
Register-ScheduledTask -TaskName \$task -Action \$action -Principal \$principal -Settings \$settings -Force | Out-Null
Stop-ScheduledTask -TaskName \$task -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName \$task
Get-ScheduledTask -TaskName \$task | Select-Object -ExpandProperty State
EOF2
)

echo "==> Starting ${MODE} workload for ${MINUTES} minutes on ${VM_NAME}"
az vm run-command invoke -g "$RG" -n "$VM_NAME" --command-id RunPowerShellScript \
  --scripts "$SCRIPT" --query "value[0].message" -o tsv
