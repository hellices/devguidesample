import shutil
import subprocess
from pathlib import Path

from azd_common_harness import run_common


COMMON_SH = Path(__file__).parents[1] / "common.sh"
DEPLOY_SH = Path(__file__).parents[1] / "deploy.sh"
CLEANUP_SH = Path(__file__).parents[1] / "cleanup.sh"
QUERY_EVIDENCE_SH = Path(__file__).parents[1] / "query-evidence.sh"

REQUIRED_ENV = {
    "AZURE_SUBSCRIPTION_ID": "11111111-2222-3333-4444-555555555555",
    "AZURE_RESOURCE_GROUP": "rg-sre-lab-test",
    "AZURE_ENV_NAME": "sre-lab-test",
}


def test_deployment_output_reads_the_current_azd_environment():
    """`deployment_output` used to look up a fixed subscription-scope
    deployment name; it must now read the values `load_lab_config` already
    resolved from the current azd environment, so a fresh `azd up` in any
    environment works without editing common.sh.
    """
    script = COMMON_SH.read_text()

    assert "FINAL_DEPLOYMENT_NAME" not in script
    assert "az deployment sub show" not in script
    assert "az deployment group show" not in script
    assert "azd env get-value" in script
    assert 'containerAppName) printf \'%s\\n\' "${AZURE_CONTAINER_APP_NAME}"' in script


def test_common_does_not_expose_personal_subscription_display_name():
    script = COMMON_SH.read_text()

    assert "SUBSCRIPTION_NAME" not in script
    assert "ME-MngEnvMCAP310512-inhwanhwang-3" not in script
    assert "inhwanhwang" not in script
    # The one true fixed subscription this task removed: common.sh must
    # never hardcode a subscription ID again, it must resolve one via
    # load_lab_config (explicit env > azd env > default) instead.
    assert "95933ae5-0201-4a21-a1fc-8051a7437982" not in script
    assert 'SUBSCRIPTION_ID="$(require_setting AZURE_SUBSCRIPTION_ID' in script
    # The subscription ID equality check is the real safety boundary and
    # must remain intact.
    assert '"${current_subscription}" != "${SUBSCRIPTION_ID}"' in script


def test_verify_subscription_reports_only_subscription_id_on_mismatch(tmp_path):
    """verify_subscription must not reference an undeclared SUBSCRIPTION_NAME.

    Regression guard for `set -u`: after removing SUBSCRIPTION_NAME, the
    mismatch message must only report the resolved SUBSCRIPTION_ID (now
    loaded via `load_lab_config`, not a hardcoded literal), or the function
    will crash under `set -u` when the variable no longer exists.
    """
    az_script = (
        'if [[ "$1 $2" == "account show" ]]; then\n'
        '  echo "wrong-subscription-id"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    result = run_common(
        tmp_path,
        env=dict(REQUIRED_ENV),
        azd_values=dict(REQUIRED_ENV),
        command="load_lab_config; verify_subscription",
        az_script=az_script,
    )

    assert result.returncode != 0
    assert "unbound variable" not in result.stderr
    assert "SUBSCRIPTION_NAME" not in result.stderr
    assert REQUIRED_ENV["AZURE_SUBSCRIPTION_ID"] in result.stderr


def test_deploy_delegates_to_azd_up():
    """The subscription-scope templates deploy.sh used to deploy were removed
    when the lab moved to azd, so deploy.sh must not reference them any more.
    It stays as a thin compatibility wrapper so the documented command keeps
    working.
    """
    script = DEPLOY_SH.read_text()

    assert "azd up" in script
    assert "subscription" + ".bicep" not in script
    assert "az deployment sub validate" not in script
    assert "az deployment sub create" not in script
    assert "az deployment group" not in script
    assert 'IMAGE_TAG="20260812.4"' not in script


def test_no_tracked_lab_file_references_the_deleted_subscription_templates():
    lab_root = Path(__file__).parents[2]
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=lab_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    needle = "subscription" + ".bicep"
    readable = {".sh", ".py", ".md", ".json", ".yaml", ".yml", ".bicep", ".bicepparam"}

    offenders = []
    for relative_path in tracked:
        path = lab_root / relative_path
        if path.suffix not in readable or not path.is_file():
            continue
        if needle in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(relative_path)

    assert offenders == [], f"tracked files still reference deleted templates: {offenders}"


def test_readme_documents_a_working_deployment_command():
    readme = (Path(__file__).parents[2] / "README.md").read_text()

    assert "azd up" in readme
    assert "az deployment sub show" not in readme
    assert "azd env get-value AZURE_CONTAINER_APP_FQDN" in readme


def test_readme_documents_scenario_scripts_read_the_current_azd_environment():
    """`run-scenario.sh` and `query-evidence.sh` now resolve deployment
    outputs through `common.sh`'s `load_lab_config` (explicit env > current
    `azd env get-value` > allowed default), so they work against whatever
    azd environment is currently selected -- not a fixed pre-azd resource
    group. The README's scenario-execution section must describe that
    mechanism instead of the old "legacy, not yet rewritten" caveat.
    """
    readme = (Path(__file__).parents[2] / "README.md").read_text()

    scenario_heading = "## 시나리오 실행"
    assert scenario_heading in readme
    section = readme.split(scenario_heading, 1)[1].split("##", 1)[0]

    assert "run-scenario.sh" in section
    assert "load_lab_config" in section
    assert "레거시" not in section, (
        "README's scenario-execution section must no longer describe "
        "run-scenario.sh/query-evidence.sh as reading a legacy, pre-azd "
        "deployment lookup -- load_lab_config now reads the current azd "
        "environment."
    )


def test_scenario_waits_for_new_revision_before_load():
    common = COMMON_SH.read_text()
    scenario = (Path(__file__).parents[1] / "run-scenario.sh").read_text()

    assert "wait_for_new_revision_ready()" in common
    assert 'OLD_REVISION="$(latest_revision_name "${APP_NAME}")"' in scenario
    assert 'wait_for_new_revision_ready "${APP_NAME}" "${OLD_REVISION}"' in scenario


def test_cleanup_removes_both_subscription_monitoring_assignments():
    script = CLEANUP_SH.read_text()

    assert "monitoring_contributor_assignment_id" in script
    assert "uami_monitoring_contributor_assignment_id" in script
    assert "agent_principal_id" in script
    assert "agent_user_assigned_principal_id" in script
    assert "749f88d5-cbae-40b8-bcfc-e573ddc772fa" in script
    assert "az rest --method get" in script
    assert "Agent setup evidence is required for cleanup" in script
    assert "Incomplete Agent setup evidence" in script


def test_s1_and_s2_record_injection_before_container_app_update():
    script = (Path(__file__).parents[1] / "run-scenario.sh").read_text()
    main_case = script.rsplit('case "${SCENARIO}" in', 1)[1]

    for branch, next_branch in (("  s1)", "  s2)"), ("  s2)", "  s3)")):
        section = main_case.split(branch, 1)[1].split(next_branch, 1)[0]
        assert section.index('INJECTED_AT="$(utc_now)"') < section.index(
            "az containerapp update"
        )
        assert 'REVISION_READY_AT="$(utc_now)"' in section


def test_s3_records_injection_before_role_deletion():
    script = (Path(__file__).parents[1] / "run-scenario.sh").read_text()
    main_case = script.rsplit('case "${SCENARIO}" in', 1)[1]
    section = main_case.split("  s3)", 1)[1].split("esac", 1)[0]

    assert section.index('INJECTED_AT="$(utc_now)"') < section.index(
        "az role assignment delete"
    )
    assert 'ROLE_DELETED_AT="$(utc_now)"' in section


def test_activity_log_export_projects_only_incident_fields():
    script = QUERY_EVIDENCE_SH.read_text()

    assert "operationName:" in script
    assert "correlationId:" in script
    assert "caller:" not in script
    assert "claims:" not in script


def test_cleanup_deletion_loop_tolerates_empty_role_assignments_on_bash32(tmp_path):
    """Regression test for the macOS Bash 3.2 empty-array bug.

    Bash 3.2 (macOS's default /bin/bash) raises "unbound variable" when
    expanding "${ARRAY[@]}" for an empty array under `set -u`, even though
    Bash 4+ treats it as an empty expansion. cleanup.sh must guard the
    ROLE_ASSIGNMENT_IDS deletion loop so a lab run with zero recorded role
    assignments still proceeds to delete the resource group instead of
    crashing.
    """
    bash_path = shutil.which("bash") or "/bin/bash"

    script = CLEANUP_SH.read_text()
    dry_run_marker = (
        'if [[ "${CONFIRMED}" -ne 1 ]]; then\n'
        '  echo "Dry run only. Re-run with --yes to execute."\n'
        "  exit 0\n"
        "fi\n"
    )
    assert dry_run_marker in script
    deletion_tail = script.split(dry_run_marker, 1)[1]

    call_log = tmp_path / "az-calls.log"
    harness = f"""
set -euo pipefail
RESOURCE_GROUP="rg-test-empty-assignments"
ROLE_ASSIGNMENT_IDS=()
az() {{
  echo "az $*" >> "{call_log}"
}}
{deletion_tail}
"""
    result = subprocess.run(
        [bash_path, "-c", harness],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "cleanup.sh's deletion loop must not crash on Bash 3.2 when "
        f"ROLE_ASSIGNMENT_IDS is empty. stderr:\n{result.stderr}"
    )
    calls = call_log.read_text() if call_log.exists() else ""
    assert "az role assignment delete" not in calls
    assert "az group delete" in calls


def test_scenario_query_capture_cleanup_scripts_load_lab_config_before_use():
    """Every script that reads SUBSCRIPTION_ID/RESOURCE_GROUP/deployment_output
    must resolve them via `load_lab_config` (through `require_lab_config`)
    first, and must do so before `verify_subscription`/`verify_lab_resource_group`
    or any deployment_output() call that depends on those values.
    """
    scripts_dir = Path(__file__).parents[1]
    for script_name in (
        "run-scenario.sh",
        "query-evidence.sh",
        "capture-scenario.sh",
        "cleanup.sh",
    ):
        script = (scripts_dir / script_name).read_text()
        assert "require_lab_config" in script, (
            f"{script_name} must call require_lab_config (which calls "
            "load_lab_config) before using SUBSCRIPTION_ID/RESOURCE_GROUP"
        )
        config_index = script.index("require_lab_config")

        for later_use in ("verify_subscription", "verify_lab_resource_group"):
            if later_use in script:
                assert config_index < script.index(later_use), (
                    f"{script_name} must call require_lab_config before {later_use}"
                )

        if "deployment_output " in script:
            first_output_call = script.index("deployment_output ")
            assert config_index < first_output_call, (
                f"{script_name} must call require_lab_config before reading "
                "any deployment_output() value"
            )

