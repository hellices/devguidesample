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
