"""Fake-CLI harness for `doctor.sh`, `baseline.sh`, and `lab.sh`.

`lab_script_harness.py`'s generic `az` fake models `run-scenario.sh` /
`query-evidence.sh` / `capture-scenario.sh` / `cleanup.sh`'s call surface. It
does not model the surfaces `doctor.sh` and `baseline.sh` add: a container
app's *current* health state (no polling loop), a `curl` probe of
`/healthz`, `az extension show` for the `log-analytics` extension,
`az resource show` for the SRE Agent resource, a per-rule `az rest` read of
`Microsoft.Insights/scheduledQueryRules`, and `az role assignment list`
keyed by a specific `--assignee-object-id`. This module gives each test
full, mutable control over that state through a single `FakeAz` object so
`doctor.sh`/`baseline.sh`/`lab.sh` are driven as real programs -- not
grepped as text -- exactly like the other lab scripts.

Three observable contracts here were re-verified against the *real* CLIs on
2026-08-14 (azure-cli 2.86.0 / log-analytics 1.0.0b1 / azd 1.29.0) rather
than assumed, because each one had been modelled incorrectly before:

1. `az monitor log-analytics query -o json` prints a flat JSON array of row
   objects, not the `{"tables": [...]}` REST envelope (see `_rows`).
2. `az role assignment list` hides parent-scope assignments unless
   `--include-inherited` is passed.
3. `azd auth login --check-status` always exits 0 and reports the real
   answer only in its output (see `azd_fake.py`).
"""
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from azd_fake import write_azd_stub, write_executable
from lab_script_harness import ENV_NAME, RESOURCE_GROUP, SCRIPTS_DIR, SUBSCRIPTION_ID


BASH = shutil.which("bash") or "/bin/bash"

APP_NAME = "ca-sre-lab"
APP_FQDN = "ca-sre-lab.example.azurecontainerapps.io"
WORKSPACE_CUSTOMER_ID = "9d1a0b2c-3d4e-5f60-7182-93a4b5c6d7e8"
TELEMETRY_SERVICE_NAME = "sre-lab-order-api"
AGENT_PRINCIPAL_ID = "8c8a4f0e-0000-4000-8000-2b1f9a0c1234"
AGENT_UAMI_PRINCIPAL_ID = "9c8a4f0e-1111-4000-8000-2b1f9a0c5678"

ALERT_RULE_NAMES = (
    "alert-sre-lab-s1-http500",
    "alert-sre-lab-s2-latency",
    "alert-sre-lab-s3-storage-rbac",
)

RESOURCE_GROUP_SCOPE = f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
SUBSCRIPTION_SCOPE = f"/subscriptions/{SUBSCRIPTION_ID}"

# `az monitor log-analytics query -o json` does NOT print the REST envelope
# (`{"tables": [...]}`). The `log-analytics` extension's `Query._output`
# flattens every table into one JSON array with a single object per row --
# `TableName` plus one *stringified* value per projected column -- so an
# empty result set prints exactly `[]`. Verified against the installed
# extension source (log-analytics 1.0.0b1, azure-cli 2.86.0):
# `~/.azure/cliextensions/log-analytics/azext_loganalytics/custom.py`.
def _rows(*rows) -> str:
    return json.dumps(list(rows))


APP_REQUESTS_ROW = {
    "TableName": "PrimaryResult",
    "TimeGenerated": "2026-08-14T00:05:00Z",
    "Name": "GET /api/orders",
}
DOCUMENT_REQUESTS_ROW = {
    "TableName": "PrimaryResult",
    "TimeGenerated": "2026-08-14T00:06:00Z",
    "Name": "GET /api/documents",
}
EMPTY_RESULT = "[]"

# What KQL's `count` operator really returns: exactly one row, whatever the
# data looks like. A fake that answers `| count` with an empty array would
# hide the very defect the doctor/baseline telemetry checks must not have.
COUNT_ZERO_RESULT = _rows({"TableName": "PrimaryResult", "Count": "0"})


def _default_alert_rules_enabled() -> Dict[str, bool]:
    return {name: True for name in ALERT_RULE_NAMES}


def _no_inherited_reader() -> Dict[str, bool]:
    return {AGENT_PRINCIPAL_ID: False, AGENT_UAMI_PRINCIPAL_ID: False}


@dataclass
class FakeAz:
    """Mutable state for the fake `az`/`azd`/`curl`/`python3` a run uses.

    Every field defaults to a fully healthy lab so a test only has to set
    the one attribute it wants to exercise. `workdir` is normally the
    fixture's `tmp_path`. State is (re)materialized each time
    `run_doctor`/`run_baseline`/`run_lab_cli` is called, so mutating a
    field *after* the fixture is created (as the brief's examples do) is
    honoured; a lab directory that already exists for `workdir` is reused
    (not wiped), so evidence a test or a prior call wrote survives.
    """

    workdir: Path
    logged_in: bool = True
    azd_logged_in: bool = True
    log_analytics_extension_installed: bool = True
    active_subscription_id: str = SUBSCRIPTION_ID
    resource_group_exists: bool = True
    resource_group_purpose: str = "sre-agent-event-lab"
    resource_group_env_tag: str = ENV_NAME
    container_app_health: str = "Healthy"
    healthz_status: int = 200
    app_insights_has_recent_requests: bool = True
    app_insights_orders_seen: bool = True
    app_insights_documents_seen: bool = True
    alert_rules_present: Dict[str, bool] = field(default_factory=_default_alert_rules_enabled)
    alert_rules_enabled: Dict[str, bool] = field(default_factory=_default_alert_rules_enabled)
    sre_agent_resource_exists: bool = True
    agent_setup_present: bool = True
    agent_setup_body: "str | None" = None
    agent_principal_id: str = AGENT_PRINCIPAL_ID
    agent_uami_principal_id: str = AGENT_UAMI_PRINCIPAL_ID
    # Reader assigned *directly* on the lab resource group.
    reader_role_assigned: Dict[str, bool] = field(
        default_factory=lambda: {AGENT_PRINCIPAL_ID: True, AGENT_UAMI_PRINCIPAL_ID: True}
    )
    # Reader assigned on the subscription and therefore only visible to a
    # lookup that asks for inherited assignments.
    reader_role_inherited: Dict[str, bool] = field(default_factory=_no_inherited_reader)
    baseline_orders_succeed: bool = True
    baseline_documents_succeed: bool = True
    # None means "use the module default AZD_VALUES"; a test passes {} (or
    # a partial dict) to exercise the missing/partial-configuration paths.
    azd_values: "Dict[str, str] | None" = None


def _bool_json(value: bool) -> str:
    return "true" if value else "false"


def _az_stub_source(fake_az: FakeAz, log_path: Path) -> str:
    rule_branches = []
    for rule_name in ALERT_RULE_NAMES:
        present = fake_az.alert_rules_present.get(rule_name, True)
        enabled = fake_az.alert_rules_enabled.get(rule_name, True)
        if not present:
            rule_branches.append(f'  *"/scheduledqueryrules/{rule_name}?"*) exit 1 ;;')
        else:
            rule_branches.append(
                f'  *"/scheduledqueryrules/{rule_name}?"*) '
                f'printf \'{{"properties": {{"enabled": {_bool_json(enabled)}}}}}\\n\' ;;'
            )
    rule_case = "\n".join(rule_branches)

    # `az role assignment list` only returns assignments made at *parent*
    # scopes when `--include-inherited` is passed; without it, a Reader
    # granted on the subscription is invisible to a resource-group scoped
    # lookup. The fake reproduces that, so a doctor that drops the flag
    # cannot pass the inherited-Reader test by accident.
    principal_ids = set(fake_az.reader_role_assigned) | set(fake_az.reader_role_inherited)
    reader_branches = []
    for principal_id in sorted(principal_ids):
        direct = []
        inherited = []
        if fake_az.reader_role_assigned.get(principal_id, False):
            direct.append(
                {
                    "principalId": principal_id,
                    "roleDefinitionName": "Reader",
                    "scope": RESOURCE_GROUP_SCOPE,
                }
            )
        if fake_az.reader_role_inherited.get(principal_id, False):
            inherited.append(
                {
                    "principalId": principal_id,
                    "roleDefinitionName": "Reader",
                    "scope": SUBSCRIPTION_SCOPE,
                }
            )
        reader_branches.append(
            f'    "{principal_id}")\n'
            f"      if [[ \"${{all_args}}\" == *--include-inherited* ]]; then\n"
            f"        printf '%s\\n' '{json.dumps(direct + inherited)}'\n"
            f"      else\n"
            f"        printf '%s\\n' '{json.dumps(direct)}'\n"
            f"      fi ;;"
        )
    reader_branches.append("    *) printf '[]\\n' ;;")
    reader_case = "\n".join(reader_branches)

    orders_rows = _rows(APP_REQUESTS_ROW) if fake_az.app_insights_orders_seen else EMPTY_RESULT
    documents_rows = (
        _rows(DOCUMENT_REQUESTS_ROW) if fake_az.app_insights_documents_seen else EMPTY_RESULT
    )
    any_rows = _rows(APP_REQUESTS_ROW) if fake_az.app_insights_has_recent_requests else EMPTY_RESULT
    account_show = (
        f"printf '%s\\n' '{fake_az.active_subscription_id}'" if fake_az.logged_in else "exit 1"
    )
    group_exists = "printf 'true\\n'" if fake_az.resource_group_exists else "printf 'false\\n'"
    resource_show = "exit 0" if fake_az.sre_agent_resource_exists else "exit 1"
    log_analytics_extension = "exit 0" if fake_az.log_analytics_extension_installed else (
        "printf 'ERROR: The extension log-analytics is not installed.\\n' >&2\n    exit 1"
    )

    return f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{log_path}"
all_args="$*"
case "${{1:-}} ${{2:-}}" in
  "account show")
    {account_show}
    ;;
  "extension show")
    if [[ "${{all_args}}" == *"--name log-analytics"* ]]; then
    {log_analytics_extension}
    fi
    ;;
  "group exists")
    {group_exists}
    ;;
  "group show")
    if [[ "$*" == *"azd-env-name"* ]]; then
      printf '%s\\n' "{fake_az.resource_group_env_tag}"
    else
      printf '%s\\n' "{fake_az.resource_group_purpose}"
    fi
    ;;
  "containerapp revision")
    printf '%s\\n' "{fake_az.container_app_health}"
    ;;
  "monitor log-analytics")
    # KQL's `count` operator always returns exactly one row, even for an
    # empty table -- reproduced here so any caller that infers "data
    # exists" from a `| count` result's row count fails loudly.
    if [[ "${{all_args}}" == *"| count"* ]]; then
      printf '%s\\n' '{COUNT_ZERO_RESULT}'
    elif [[ "${{all_args}}" == *"/api/orders"* ]]; then
      printf '%s\\n' '{orders_rows}'
    elif [[ "${{all_args}}" == *"/api/documents"* ]]; then
      printf '%s\\n' '{documents_rows}'
    else
      printf '%s\\n' '{any_rows}'
    fi
    ;;
  "rest --method")
    case "$*" in
{rule_case}
      *) printf '{{}}\\n' ;;
    esac
    ;;
  "resource show")
    {resource_show}
    ;;
  "role assignment")
    principal="${{all_args##*--assignee-object-id }}"
    principal="${{principal%% *}}"
    case "${{principal}}" in
{reader_case}
    esac
    ;;
  *)
    : ;;
esac
exit 0
"""


def _curl_stub_source(fake_az: FakeAz) -> str:
    return f"""#!/usr/bin/env bash
printf '%s' "{fake_az.healthz_status}"
"""


def _python3_stub_source(fake_az: FakeAz, log_path: Path) -> str:
    """Fake `python3`/`.venv/bin/python` for `loadgen.py`: writes a minimal,
    valid summary and exits with loadgen's real contract (0 success, 2 a
    request mismatch), keyed by the target URL so orders/documents can be
    made to succeed or fail independently."""
    orders_ok = 1 if fake_az.baseline_orders_succeed else 0
    documents_ok = 1 if fake_az.baseline_documents_succeed else 0
    return f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{log_path}"
output=""
requests=1
args=("$@")
for ((i=0; i<${{#args[@]}}; i++)); do
  case "${{args[$i]}}" in
    --output) output="${{args[$((i+1))]}}" ;;
    --requests) requests="${{args[$((i+1))]}}" ;;
  esac
done
succeed=1
if [[ "$*" == *"/api/orders"* ]]; then
  succeed={orders_ok}
elif [[ "$*" == *"/api/documents"* ]]; then
  succeed={documents_ok}
fi
if [[ -n "${{output}}" ]]; then
  mkdir -p "$(dirname "${{output}}")"
  printf '{{"total": %s, "errors": 0}}\\n' "${{requests}}" > "${{output}}"
fi
if [[ "${{succeed}}" -eq 1 ]]; then
  exit 0
else
  exit 2
fi
"""


AZD_VALUES = {
    "AZURE_SUBSCRIPTION_ID": SUBSCRIPTION_ID,
    "AZURE_RESOURCE_GROUP": RESOURCE_GROUP,
    "AZURE_ENV_NAME": ENV_NAME,
    "AZURE_LOCATION": "koreacentral",
    "AZURE_CONTAINER_APP_NAME": APP_NAME,
    "AZURE_CONTAINER_APP_FQDN": APP_FQDN,
    "AZURE_STORAGE_CONTAINER_SCOPE": (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
        "/providers/Microsoft.Storage/storageAccounts/stsrelab/blobServices/default"
        "/containers/documents"
    ),
    "AZURE_BLOB_ROLE_ASSIGNMENT_NAME": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    "AZURE_WORKSPACE_ID": (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
        "/providers/Microsoft.OperationalInsights/workspaces/log-sre-lab"
    ),
    "AZURE_APP_INSIGHTS_NAME": "appi-sre-lab",
    "AZURE_TELEMETRY_SERVICE_NAME": TELEMETRY_SERVICE_NAME,
    "containerAppPrincipalId": "8c8a4f0e-aaaa-4000-8000-2b1f9a0c1234",
    "workspaceCustomerId": WORKSPACE_CUSTOMER_ID,
}


class LabRun:
    def __init__(
        self,
        lab: Path,
        bin_dir: Path,
        workdir: Path,
        az_log: Path,
        python_log: Path,
        azd_log: Path,
    ):
        self.lab = lab
        self.bin_dir = bin_dir
        self.workdir = workdir
        self.az_log = az_log
        self.python_log = python_log
        self.azd_log = azd_log

    def run(self, script_name, args=(), env=None):
        process_env = {
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "HOME": os.environ.get("HOME", str(self.lab)),
        }
        process_env.update(env or {})
        return subprocess.run(
            [BASH, str(self.lab / "scripts" / script_name), *args],
            capture_output=True,
            text=True,
            env=process_env,
            cwd=str(self.workdir),
        )

    def az_calls(self):
        return self.az_log.read_text() if self.az_log.exists() else ""

    def azd_calls(self):
        return self.azd_log.read_text() if self.azd_log.exists() else ""

    def evidence_dir(self):
        return self.lab / "evidence"


def _write_agent_setup(lab: Path, fake_az: FakeAz) -> None:
    agent_setup_path = lab / "evidence" / "agent-setup.json"
    if not fake_az.agent_setup_present:
        agent_setup_path.unlink(missing_ok=True)
        return
    if fake_az.agent_setup_body is not None:
        agent_setup_path.write_text(fake_az.agent_setup_body)
        return
    setup = {
        "agent_endpoint": "https://sre-agent.example.com/api/incidents",
        "monitoring_contributor_assignment_id": (
            f"/subscriptions/{SUBSCRIPTION_ID}/providers"
            "/Microsoft.Authorization/roleAssignments/principal-one"
        ),
        "agent_principal_id": fake_az.agent_principal_id,
        "uami_monitoring_contributor_assignment_id": (
            f"/subscriptions/{SUBSCRIPTION_ID}/providers"
            "/Microsoft.Authorization/roleAssignments/principal-two"
        ),
        "agent_user_assigned_principal_id": fake_az.agent_uami_principal_id,
    }
    agent_setup_path.write_text(json.dumps(setup))


def _materialize(fake_az: FakeAz) -> LabRun:
    """Create (once) or refresh the throwaway lab + fake CLIs for `fake_az`.

    The lab's `scripts/` and `evidence/` directories are only created the
    first time a given `fake_az.workdir` is used, so evidence written by an
    earlier call (or by the test itself) survives across repeated
    `run_doctor`/`run_lab_cli` calls with the same `fake_az`. The fake
    `az`/`curl`/`python3` executables are always rewritten so the latest
    mutations to `fake_az` take effect immediately.
    """
    tmp_path = fake_az.workdir
    lab = tmp_path / "lab"
    if not lab.exists():
        shutil.copytree(
            SCRIPTS_DIR,
            lab / "scripts",
            ignore=shutil.ignore_patterns("tests", "__pycache__"),
        )
        (lab / "azure.yaml").write_text("name: sre-agent-event-lab\n")
        (lab / "evidence").mkdir()

    _write_agent_setup(lab, fake_az)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    az_log = tmp_path / "az-calls.log"
    python_log = tmp_path / "python-calls.log"
    azd_log = tmp_path / "azd-calls.log"

    write_executable(bin_dir / "az", _az_stub_source(fake_az, az_log))
    azd_values = fake_az.azd_values if fake_az.azd_values is not None else AZD_VALUES
    write_azd_stub(bin_dir, azd_values, "azd_1_29", azd_log, logged_in=fake_az.azd_logged_in)
    write_executable(bin_dir / "curl", _curl_stub_source(fake_az))
    write_executable(bin_dir / "python3", _python3_stub_source(fake_az, python_log))

    venv_bin = lab / "app" / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    write_executable(venv_bin / "python", _python3_stub_source(fake_az, python_log))

    workdir = tmp_path / "elsewhere"
    workdir.mkdir(exist_ok=True)

    return LabRun(lab, bin_dir, workdir, az_log, python_log, azd_log)


def _split_env(env_overrides):
    env = {key.upper(): value for key, value in env_overrides.items() if key != "env"}
    if "env" in env_overrides:
        env.update(env_overrides["env"])
    return env


def run_doctor(fake_az: FakeAz, **env_overrides) -> subprocess.CompletedProcess:
    """Run `doctor.sh` against `fake_az`'s current state.

    `env_overrides` keys use the process-environment names `common.sh`
    reads, lower-cased for readability (e.g. `sre_agent_resource_id="..."`
    becomes `SRE_AGENT_RESOURCE_ID`).
    """
    run = _materialize(fake_az)
    return run.run("doctor.sh", env=_split_env(env_overrides))


def run_baseline(fake_az: FakeAz, **env_overrides) -> subprocess.CompletedProcess:
    run = _materialize(fake_az)
    return run.run("baseline.sh", env=_split_env(env_overrides))


def run_lab_cli(fake_az: FakeAz, args, **env_overrides) -> subprocess.CompletedProcess:
    run = _materialize(fake_az)
    return run.run("lab.sh", args=args, env=_split_env(env_overrides))


def lab_dir_for(fake_az: FakeAz) -> Path:
    """The lab directory `run_doctor`/`run_baseline`/`run_lab_cli` will use
    for `fake_az`. A test can call this *before* the first run to pre-seed
    evidence (e.g. a scenario's `timeline.json`) once the directory exists,
    or after a run to inspect what the script produced."""
    return fake_az.workdir / "lab"


def az_calls_for(fake_az: FakeAz) -> str:
    """Every `az` invocation logged for `fake_az.workdir`'s most recent
    run, in order, one `argv` per line."""
    log_path = fake_az.workdir / "az-calls.log"
    return log_path.read_text() if log_path.exists() else ""


def azd_calls_for(fake_az: FakeAz) -> str:
    """Every `azd` invocation logged for `fake_az.workdir`'s most recent
    run (argv, then `cwd=...`, one per line -- see `azd_fake.py`)."""
    log_path = fake_az.workdir / "azd-calls.log"
    return log_path.read_text() if log_path.exists() else ""
