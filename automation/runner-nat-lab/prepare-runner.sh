#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl jq git docker.io python3-venv
systemctl enable --now docker
id runner >/dev/null 2>&1 || useradd --create-home --shell /bin/bash runner
usermod -aG docker runner
install -d -o runner -g runner /opt/actions-runner
cd /opt/actions-runner
if [[ -f .runner ]]; then
  echo 'Runner already registered; preserving its identity.'
  exit 0
fi
curl --fail --silent --show-error --location \
  https://api.github.com/repos/actions/runner/releases/latest -o /tmp/runner-release.json
asset=$(jq -er '.assets[] | select(.name | test("^actions-runner-linux-x64-.*\\.tar\\.gz$")) | .browser_download_url' /tmp/runner-release.json)
digest=$(jq -er '.assets[] | select(.name | test("^actions-runner-linux-x64-.*\\.tar\\.gz$")) | .digest | select(startswith("sha256:"))' /tmp/runner-release.json)
curl --fail --silent --show-error --location "$asset" -o /tmp/actions-runner.tar.gz
printf '%s  %s\n' "${digest#sha256:}" /tmp/actions-runner.tar.gz | sha256sum --check
tar xzf /tmp/actions-runner.tar.gz
chown -R runner:runner /opt/actions-runner
./bin/installdependencies.sh
rm /tmp/actions-runner.tar.gz /tmp/runner-release.json
echo 'Runner dependencies and verified runner package installed.'
