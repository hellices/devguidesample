#!/usr/bin/env bash
set -euo pipefail
# Supply registrationToken as an Azure Managed Run Command protected parameter.
cd /opt/actions-runner
if [[ -f .runner ]]; then
  echo 'Runner already registered; preserving its identity.'
else
  : "${registrationToken:?A short-lived registration token is required}"
  runuser -u runner -- ./config.sh --unattended \
    --url https://github.com/hellices/devguidesample \
    --token "$registrationToken" \
    --name nat-ip-lab-20260907 \
    --labels nat-ip-lab-20260907 \
    --work _work
fi
if [[ ! -f .service ]]; then
  ./svc.sh install runner
fi
./svc.sh start
jq '{agentId, agentName, gitHubUrl}' .runner
