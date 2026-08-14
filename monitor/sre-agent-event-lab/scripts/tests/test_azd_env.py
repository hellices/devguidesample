"""Behaviour tests for common.sh's azd-backed configuration loader.

`load_lab_config` must resolve every setting as: explicit process
environment > current `azd env get-value` > an allowed default -- and must
never fall back to a fixed subscription/resource group again. These tests
drive `common.sh` through a fake `azd`/`az` on PATH (see `azd_fake.py` for
the recorded azd 1.29.0 contract the fake reproduces); no real Azure CLI or
azd call is made.
"""
import re

import pytest

from azd_common_harness import COMMON_SH, LAB_ROOT, run_common
from azd_fake import MISSING_KEY_MODES


REQUIRED_ENV = {
    "AZURE_SUBSCRIPTION_ID": "azd-sub-11111111",
    "AZURE_RESOURCE_GROUP": "rg-azd-sub-lab",
    "AZURE_ENV_NAME": "sre-lab-dev",
}


def test_explicit_environment_wins_over_azd_value(tmp_path):
    result = run_common(
        tmp_path,
        env={**REQUIRED_ENV, "AZURE_SUBSCRIPTION_ID": "explicit-sub"},
        azd_values={
            "AZURE_SUBSCRIPTION_ID": "azd-sub",
            "AZURE_RESOURCE_GROUP": REQUIRED_ENV["AZURE_RESOURCE_GROUP"],
            "AZURE_ENV_NAME": REQUIRED_ENV["AZURE_ENV_NAME"],
        },
        command='load_lab_config; printf "%s" "${SUBSCRIPTION_ID}"',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "explicit-sub"


def test_current_azd_value_wins_over_default_when_no_explicit_env(tmp_path):
    result = run_common(
        tmp_path,
        env={k: v for k, v in REQUIRED_ENV.items() if k != "AZURE_SUBSCRIPTION_ID"},
        azd_values={
            **REQUIRED_ENV,
            "AZURE_LOCATION": "eastus",
        },
        command='load_lab_config; printf "%s" "${LOCATION}"',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "eastus"


@pytest.mark.parametrize("missing_key_mode", MISSING_KEY_MODES)
def test_allowed_default_applies_when_neither_explicit_env_nor_azd_value_exist(
    tmp_path, missing_key_mode
):
    """The default must win for a value azd does not have -- whatever azd
    printed on stdout while failing.

    azd 1.29.0 answers an unknown key with `ERROR: ...` on **stdout** and a
    non-zero exit status. Reading stdout unconditionally turns that error
    text into the setting's value, so `LOCATION` would become an `ERROR:`
    sentence instead of the documented default.
    """
    result = run_common(
        tmp_path,
        env=dict(REQUIRED_ENV),
        azd_values=dict(REQUIRED_ENV),
        command='load_lab_config; printf "%s" "${LOCATION}"',
        missing_key_mode=missing_key_mode,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "koreacentral"
    assert "ERROR" not in result.stdout


@pytest.mark.parametrize("missing_key_mode", MISSING_KEY_MODES)
def test_missing_required_setting_names_the_azd_command(tmp_path, missing_key_mode):
    """A required setting azd does not have must fail closed, even though
    azd's own failure output arrives on stdout looking like a value."""
    result = run_common(
        tmp_path,
        env={},
        azd_values={},
        command="load_lab_config",
        missing_key_mode=missing_key_mode,
    )
    assert result.returncode != 0
    assert "azd env set AZURE_SUBSCRIPTION_ID" in result.stderr


@pytest.mark.parametrize("missing_key_mode", MISSING_KEY_MODES)
def test_missing_azd_value_never_becomes_a_resolved_setting(tmp_path, missing_key_mode):
    """Nothing azd printed while failing may reach a resolved value."""
    result = run_common(
        tmp_path,
        env=dict(REQUIRED_ENV),
        azd_values=dict(REQUIRED_ENV),
        command=(
            "load_lab_config; "
            'printf "%s|%s|%s" "${AZURE_CONTAINER_APP_NAME}" '
            '"${SRE_AGENT_NAME}" "${SRE_LAB_EXPIRES_ON}"'
        ),
        missing_key_mode=missing_key_mode,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "||"


def test_missing_resource_group_names_the_azd_command_once_subscription_resolves(tmp_path):
    result = run_common(
        tmp_path,
        env={"AZURE_SUBSCRIPTION_ID": "explicit-sub"},
        azd_values={},
        command="load_lab_config",
    )
    assert result.returncode != 0
    assert "azd env set AZURE_RESOURCE_GROUP" in result.stderr


def test_azd_lookup_pins_the_lab_project_root_from_any_working_directory(tmp_path):
    """azd resolves its project from `--cwd`, else from the process working
    directory, and fails when that directory has no `azure.yaml`.

    The lab scripts are routinely started from the repository root (or any
    other directory), so every lookup has to pin the lab project root. The
    fake `azd` refuses a project directory without `azure.yaml` exactly as
    the real one does, and this run happens from a scratch directory that
    has none.
    """
    workdir = tmp_path / "somewhere-else"
    workdir.mkdir()
    azd_log = tmp_path / "azd-calls.log"

    result = run_common(
        tmp_path,
        env={k: v for k, v in REQUIRED_ENV.items() if k != "AZURE_SUBSCRIPTION_ID"},
        azd_values={**REQUIRED_ENV, "AZURE_LOCATION": "eastus"},
        command=(
            'load_lab_config; printf "%s|%s" "${SUBSCRIPTION_ID}" "${LOCATION}"'
        ),
        cwd=workdir,
        azd_log=azd_log,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{REQUIRED_ENV['AZURE_SUBSCRIPTION_ID']}|eastus"
    calls = azd_log.read_text()
    assert f"cwd={LAB_ROOT}" in calls, (
        "every azd lookup must run against the lab project root, not the "
        f"caller's working directory: {calls!r}"
    )


def test_azd_lookup_from_the_repository_root_still_resolves_settings(tmp_path):
    """The documented entry points are run from the repository root."""
    result = run_common(
        tmp_path,
        env={},
        azd_values={**REQUIRED_ENV, "AZURE_LOCATION": "westus2"},
        command='load_lab_config; printf "%s|%s" "${RESOURCE_GROUP}" "${LOCATION}"',
        cwd=LAB_ROOT.parents[1],
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{REQUIRED_ENV['AZURE_RESOURCE_GROUP']}|westus2"


def test_load_lab_config_resolves_sre_agent_settings_with_documented_defaults(tmp_path):
    result = run_common(
        tmp_path,
        env=dict(REQUIRED_ENV),
        azd_values=dict(REQUIRED_ENV),
        command=(
            'load_lab_config; '
            'printf "%s|%s" "${SRE_REPOSITORY_BRANCH}" "${SRE_KNOWLEDGE_PATH}"'
        ),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "main|runbooks/incident-response.md"


def test_load_lab_config_does_not_fix_subscription_or_resource_group_values(tmp_path):
    """Regression guard for the removed hardcoded values: two different azd
    environments (different subscription, resource group, env name) must
    each resolve to their own values -- nothing in common.sh may fall back
    to a value baked into the script.
    """
    other_env = {
        "AZURE_SUBSCRIPTION_ID": "22222222-3333-4444-5555-666666666666",
        "AZURE_RESOURCE_GROUP": "rg-some-other-lab",
        "AZURE_ENV_NAME": "sre-lab-other",
    }
    result = run_common(
        tmp_path,
        env=dict(other_env),
        azd_values=dict(other_env),
        command='load_lab_config; printf "%s|%s" "${SUBSCRIPTION_ID}" "${RESOURCE_GROUP}"',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "22222222-3333-4444-5555-666666666666|rg-some-other-lab"


def test_a_stored_setting_value_is_never_executed_as_shell_code(tmp_path):
    """Values arrive from an azd environment file an operator can edit, so
    resolution must treat them as data: no `eval`, no re-expansion.
    """
    marker = tmp_path / "pwned"
    injected = f'$(touch "{marker}")`touch "{marker}"`'
    result = run_common(
        tmp_path,
        env=dict(REQUIRED_ENV),
        azd_values={**REQUIRED_ENV, "AZURE_LOCATION": injected},
        command='load_lab_config; printf "%s" "${LOCATION}"',
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == injected
    assert not marker.exists(), "a stored setting value was executed as shell code"


def test_setting_helper_does_not_use_eval_or_variable_indirection():
    """Token-aware guard: `eval` as a command, `declare -n`, and `${!name}`
    indirection are all forbidden. Substring matching would fire on the word
    "evaluate" in a comment and miss `eval` in code, so comments are stripped
    and word boundaries are required.
    """
    code_lines = [
        line for line in COMMON_SH.read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]
    code = "\n".join(code_lines)

    assert not re.search(r"(?<![\w-])eval(?![\w-])", code), "common.sh must not use eval"
    assert not re.search(r"declare\s+-n\b", code)
    assert "${!" not in code


def test_resource_group_safety_requires_purpose_and_environment_tags():
    script = COMMON_SH.read_text()

    assert "tags.purpose" in script
    assert 'tags."azd-env-name"' in script


def test_verify_lab_resource_group_refuses_when_azd_env_name_tag_mismatches(tmp_path):
    az_script = """
case "$1 $2" in
  "group exists")
    echo true
    ;;
  "group show")
    if [[ "$*" == *'tags."azd-env-name"'* ]]; then
      echo "a-different-azd-environment"
    else
      echo "sre-agent-event-lab"
    fi
    ;;
esac
exit 0
"""
    result = run_common(
        tmp_path,
        env=dict(REQUIRED_ENV),
        azd_values=dict(REQUIRED_ENV),
        command="load_lab_config; verify_lab_resource_group",
        az_script=az_script,
    )
    assert result.returncode != 0
    assert "Refusing to operate on untagged resource group" in result.stderr


def test_require_lab_config_checks_commands_before_loading_config(tmp_path):
    """`require_lab_config` must fail on the missing CLI and never reach
    `load_lab_config`.

    PATH here holds every required fake except `jq`, so exactly one
    outcome is correct: the missing-command message, and no configuration
    error at all.
    """
    result = run_common(
        tmp_path,
        env={},
        azd_values={},
        command="require_lab_config",
        available_commands=("az", "azd", "curl", "python3"),
    )

    assert result.returncode != 0
    assert "Required command not found: jq" in result.stderr
    assert "azd env set" not in result.stderr, (
        "require_commands must fail before load_lab_config runs: "
        f"{result.stderr!r}"
    )
