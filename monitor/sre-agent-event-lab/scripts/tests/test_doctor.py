"""Behavioural tests for `doctor.sh`.

Every test drives `doctor.sh` as a real program against a fake `az`/`azd`/
`curl` on PATH (see `doctor_harness.py`), not by grepping its text: the
output-contract tests below prove PASS/FAIL/MANUAL rows are produced from
actual (faked) CLI responses, that a single unhealthy signal both flips the
exit code and is distinguishable from a portal-only MANUAL check, and that
the script never queries Azure once its own safety gate (commands, login,
azd configuration, subscription equality, resource-group tags) has failed.
"""
import pytest

from doctor_harness import (
    AGENT_PRINCIPAL_ID,
    AGENT_UAMI_PRINCIPAL_ID,
    FakeAz,
    az_calls_for,
    azd_calls_for,
    lab_dir_for,
    run_doctor,
)


MANUAL_CHECKS = (
    "Repository connection",
    "Knowledge source",
    "Incident platform",
    "Response plan",
)


@pytest.fixture
def fake_az(tmp_path):
    return FakeAz(workdir=tmp_path)


def test_doctor_reports_manual_for_unverifiable_portal_settings(fake_az):
    result = run_doctor(fake_az, sre_agent_resource_id="/subscriptions/sub/...")

    assert "Repository connection\tMANUAL" in result.stdout
    assert "Response plan\tMANUAL" in result.stdout


def test_doctor_fails_when_workload_is_unhealthy(fake_az):
    fake_az.container_app_health = "Unhealthy"

    result = run_doctor(fake_az)

    assert result.returncode == 1
    assert "Container App health\tFAIL" in result.stdout


def test_doctor_passes_fully_healthy_environment(fake_az):
    """Every gating and diagnostic check reaches PASS; only the four
    portal-only settings are MANUAL, and the overall exit code is 0."""
    result = run_doctor(fake_az, sre_agent_resource_id="/subscriptions/sub/.../sreAgents/a")

    assert result.returncode == 0, result.stdout + result.stderr
    rows = dict(line.split("\t", 2)[0:2] for line in result.stdout.splitlines() if "\t" in line)
    assert rows["Required commands"] == "PASS"
    assert rows["Azure CLI login"] == "PASS"
    assert rows["azd configuration"] == "PASS"
    assert rows["Subscription match"] == "PASS"
    assert rows["Resource group tags"] == "PASS"
    assert rows["Container App health"] == "PASS"
    assert rows["Health endpoint"] == "PASS"
    assert rows["Application Insights telemetry"] == "PASS"
    assert rows["Alert rules enabled"] == "PASS"
    assert rows["SRE Agent resource"] == "PASS"
    assert rows["Reader role assignment"] == "PASS"
    for manual_check in MANUAL_CHECKS:
        assert rows[manual_check] == "MANUAL"


def test_doctor_omits_sre_agent_resource_row_when_not_configured(fake_az):
    """The check is only meaningful -- and only printed -- once an operator
    has recorded SRE_AGENT_RESOURCE_ID; otherwise nothing has been created
    yet, and there is nothing to verify."""
    result = run_doctor(fake_az)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "SRE Agent resource" not in result.stdout


def test_doctor_fails_when_sre_agent_resource_is_missing(fake_az):
    fake_az.sre_agent_resource_exists = False

    result = run_doctor(fake_az, sre_agent_resource_id="/subscriptions/sub/.../sreAgents/missing")

    assert result.returncode == 1
    assert "SRE Agent resource\tFAIL" in result.stdout


def test_doctor_fails_when_healthz_does_not_return_200(fake_az):
    fake_az.healthz_status = 503

    result = run_doctor(fake_az)

    assert result.returncode == 1
    assert "Health endpoint\tFAIL" in result.stdout
    assert "503" in result.stdout


def test_doctor_fails_when_app_insights_has_no_recent_requests(fake_az):
    fake_az.app_insights_has_recent_requests = False

    result = run_doctor(fake_az)

    assert result.returncode == 1
    assert "Application Insights telemetry\tFAIL" in result.stdout


def test_doctor_fails_when_an_alert_rule_is_disabled(fake_az):
    fake_az.alert_rules_enabled["alert-sre-lab-s2-latency"] = False

    result = run_doctor(fake_az)

    assert result.returncode == 1
    row = next(line for line in result.stdout.splitlines() if line.startswith("Alert rules enabled\t"))
    assert "FAIL" in row
    assert "alert-sre-lab-s2-latency" in row


def test_doctor_fails_when_an_alert_rule_is_missing(fake_az):
    fake_az.alert_rules_present["alert-sre-lab-s3-storage-rbac"] = False

    result = run_doctor(fake_az)

    assert result.returncode == 1
    row = next(line for line in result.stdout.splitlines() if line.startswith("Alert rules enabled\t"))
    assert "FAIL" in row
    assert "alert-sre-lab-s3-storage-rbac" in row


def test_doctor_fails_when_agent_setup_evidence_is_missing(fake_az):
    """Unlike the repository/knowledge/response-plan settings, Reader is a
    real RBAC role assignment a stable API can check -- so a missing
    prerequisite is FAIL, never a shrug-and-guess MANUAL."""
    fake_az.agent_setup_present = False

    result = run_doctor(fake_az)

    assert result.returncode == 1
    assert "Reader role assignment\tFAIL" in result.stdout
    assert "lab.sh acknowledge agent-setup" in result.stdout


def test_doctor_fails_when_one_recorded_identity_lacks_reader(fake_az):
    fake_az.reader_role_assigned[AGENT_UAMI_PRINCIPAL_ID] = False

    result = run_doctor(fake_az)

    assert result.returncode == 1
    row = next(
        line for line in result.stdout.splitlines() if line.startswith("Reader role assignment\t")
    )
    assert "FAIL" in row
    assert AGENT_UAMI_PRINCIPAL_ID in row


def test_doctor_never_calls_azure_once_subscription_mismatches(fake_az):
    """Fail closed: once the pinned-subscription check fails, no further
    Azure resource lookups may happen, even to produce diagnostics."""
    result = run_doctor(fake_az, azure_subscription_id="99999999-9999-9999-9999-999999999999")

    assert result.returncode == 1
    assert "Subscription match\tFAIL" in result.stdout
    assert "Blocked: resolve the failing check above first." in result.stdout
    assert "containerapp revision" not in az_calls_for(fake_az)
    assert "role assignment" not in az_calls_for(fake_az)


def test_doctor_never_calls_azure_when_azd_configuration_is_missing(fake_az):
    """No azd value and no explicit environment: doctor must stop with the
    actionable `azd env set` message before touching Azure, exactly like
    every other entry point."""
    fake_az.azd_values = {}

    result = run_doctor(fake_az)

    assert result.returncode == 1
    assert "azd configuration\tFAIL" in result.stdout
    assert "azd env set AZURE_SUBSCRIPTION_ID" in result.stdout
    assert "containerapp revision" not in az_calls_for(fake_az)


def test_doctor_pins_azd_lookups_to_the_lab_project_root(fake_az):
    """`azd env get-value` must be pinned with `--cwd` to this lab's own
    project root, exactly as `common.sh`'s other callers already are."""
    result = run_doctor(fake_az)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"cwd={lab_dir_for(fake_az)}" in azd_calls_for(fake_az)

