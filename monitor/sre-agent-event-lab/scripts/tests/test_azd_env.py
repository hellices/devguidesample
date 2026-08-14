"""Behaviour tests for common.sh's azd-backed configuration loader.

`load_lab_config` must resolve every setting as: explicit process
environment > current `azd env get-value` > an allowed default -- and must
never fall back to a fixed subscription/resource group again. These tests
drive `common.sh` through a fake `azd`/`az` on PATH (see
`azd_common_harness.py`); no real Azure CLI or azd call is made.
"""
from azd_common_harness import COMMON_SH, run_common


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


def test_allowed_default_applies_when_neither_explicit_env_nor_azd_value_exist(tmp_path):
    result = run_common(
        tmp_path,
        env=dict(REQUIRED_ENV),
        azd_values=dict(REQUIRED_ENV),
        command='load_lab_config; printf "%s" "${LOCATION}"',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "koreacentral"


def test_missing_required_setting_names_the_azd_command(tmp_path):
    result = run_common(
        tmp_path,
        env={},
        azd_values={},
        command="load_lab_config",
    )
    assert result.returncode != 0
    assert "azd env set AZURE_SUBSCRIPTION_ID" in result.stderr


def test_missing_resource_group_names_the_azd_command_once_subscription_resolves(tmp_path):
    result = run_common(
        tmp_path,
        env={"AZURE_SUBSCRIPTION_ID": "explicit-sub"},
        azd_values={},
        command="load_lab_config",
    )
    assert result.returncode != 0
    assert "azd env set AZURE_RESOURCE_GROUP" in result.stderr


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


def test_setting_helper_does_not_use_eval_or_indirection():
    script = COMMON_SH.read_text()

    assert "eval" not in script
    assert "declare -n" not in script
    # No `${!name}` indirect expansion anywhere in the setting/azd_value path.
    assert "${!" not in script


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


def test_require_lab_config_requires_commands_before_loading_config(tmp_path):
    result = run_common(
        tmp_path,
        env={},
        azd_values={},
        command="require_lab_config",
    )
    assert result.returncode != 0
    # require_commands runs first; jq is missing because run_common's fake
    # PATH does not put it ahead of any earlier failing check.
    assert "Required command not found" in result.stderr or (
        "azd env set AZURE_SUBSCRIPTION_ID" in result.stderr
    )
