import shutil
import subprocess
from pathlib import Path


COMMON_SH = Path(__file__).parents[1] / "common.sh"
DEPLOY_SH = Path(__file__).parents[1] / "deploy.sh"
CLEANUP_SH = Path(__file__).parents[1] / "cleanup.sh"
QUERY_EVIDENCE_SH = Path(__file__).parents[1] / "query-evidence.sh"


def test_outputs_come_from_latest_subscription_deployment():
    script = COMMON_SH.read_text()

    assert 'FINAL_DEPLOYMENT_NAME="sre-agent-event-lab-private"' in script
    assert "az deployment sub show" in script
    assert "az deployment group show" not in script


def test_deploy_uses_subscription_wrapper():
    script = DEPLOY_SH.read_text()

    assert 'TEMPLATE_FILE="${LAB_ROOT}/infra/subscription.bicep"' in script
    assert 'PARAMETER_FILE="${LAB_ROOT}/infra/subscription.bicepparam"' in script
    assert "az deployment sub validate" in script
    assert "az deployment sub create" in script
    assert "az deployment group" not in script
    assert 'IMAGE_TAG="20260812.4"' not in script
    assert "SRE_IMAGE_TAG" in script
    assert "date -u +%Y%m%dT%H%M%SZ" in script


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
