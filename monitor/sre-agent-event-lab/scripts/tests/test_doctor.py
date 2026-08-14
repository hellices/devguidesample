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
    RESOURCE_GROUP,
    SUBSCRIPTION_SCOPE,
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


def _rows_of(result):
    return dict(line.split("\t", 2)[0:2] for line in result.stdout.splitlines() if "\t" in line)


def _detail_of(result, check_name):
    row = next(
        line for line in result.stdout.splitlines() if line.startswith(f"{check_name}\t")
    )
    return row.split("\t", 2)[2]


def _analytics_queries(fake_az):
    return [
        line for line in az_calls_for(fake_az).splitlines() if "monitor log-analytics" in line
    ]


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
    rows = _rows_of(result)
    assert rows["Required commands"] == "PASS"
    assert rows["Python environment"] == "PASS"
    assert rows["Log Analytics CLI extension"] == "PASS"
    assert rows["Azure CLI login"] == "PASS"
    assert rows["azd authentication"] == "PASS"
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


def test_doctor_fails_when_venv_is_missing(fake_az):
    """Finding #1: doctor must report on the venv `setup-venv.sh` (run from
    `postprovision`) is responsible for creating, with a remedy pointing at
    that exact script -- not just a generic "python3 missing" message,
    since `python3` itself is still on PATH."""
    fake_az.venv_present = False

    result = run_doctor(fake_az)

    assert result.returncode == 1
    assert "Python environment\tFAIL" in result.stdout
    assert "setup-venv.sh" in _detail_of(result, "Python environment")


def test_doctor_fails_when_pillow_is_not_importable_from_the_venv(fake_az):
    """A venv that exists but never finished installing (or was created by
    something other than `setup-venv.sh`) must fail this check too, not
    just an absent venv directory."""
    fake_az.pillow_importable = False

    result = run_doctor(fake_az)

    assert result.returncode == 1
    assert "Python environment\tFAIL" in result.stdout
    assert "setup-venv.sh" in _detail_of(result, "Python environment")


def test_doctor_passes_venv_check_independently_of_azure_reachability(fake_az):
    """The venv/Pillow readiness check is a local precondition, not an
    Azure fact: it must still report accurately (and PASS when the venv is
    fine) even when every Azure-dependent check is blocked."""
    fake_az.logged_in = False

    result = run_doctor(fake_az)

    assert "Python environment\tPASS" in result.stdout
    assert "Azure CLI login\tFAIL" in result.stdout


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



# --- Application Insights telemetry: the real `az monitor log-analytics
# query` output contract ------------------------------------------------
#
# The extension flattens the REST envelope into a JSON array of row objects
# (`{"tables": [...]}` is never printed), and KQL's `count` operator always
# returns exactly one row -- so "the result had rows" only distinguishes
# data from no data when the query itself is not a `| count`.


def test_doctor_reports_telemetry_pass_from_flat_query_output(fake_az):
    """A workspace that has data answers with a non-empty flat array."""
    fake_az.app_insights_has_recent_requests = True

    result = run_doctor(fake_az)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Application Insights telemetry\tPASS" in result.stdout
    assert _analytics_queries(fake_az), "doctor never queried the workspace"


def test_doctor_reports_telemetry_fail_from_empty_flat_query_output(fake_az):
    """A workspace with no matching rows answers with exactly `[]`."""
    fake_az.app_insights_has_recent_requests = False

    result = run_doctor(fake_az)

    assert result.returncode == 1
    assert "Application Insights telemetry\tFAIL" in result.stdout
    assert "lab.sh baseline" in _detail_of(result, "Application Insights telemetry")


def test_doctor_telemetry_query_does_not_count_rows_of_a_count(fake_az):
    """`| count` returns one row even for an empty table, so counting its
    rows can never distinguish data from no data."""
    run_doctor(fake_az)

    queries = _analytics_queries(fake_az)
    assert queries
    for query in queries:
        assert "| count" not in query, f"telemetry query relies on `| count`: {query}"


def test_doctor_telemetry_does_not_parse_the_rest_tables_envelope(fake_az):
    """Regression guard for the shape defect itself: with the real flat
    output faked, a `.tables[0].rows` parse always yields zero rows and can
    only ever report FAIL, so a healthy workspace must still PASS."""
    fake_az.app_insights_has_recent_requests = True
    fake_az.app_insights_orders_seen = True

    result = run_doctor(fake_az)

    assert "Application Insights telemetry\tPASS" in result.stdout


# --- Prerequisite: the `log-analytics` CLI extension ---------------------


def test_doctor_fails_when_log_analytics_extension_is_missing(fake_az):
    """`az monitor log-analytics query` lives in an extension that is not
    installed by default; without it every telemetry check is meaningless."""
    fake_az.log_analytics_extension_installed = False

    result = run_doctor(fake_az)

    assert result.returncode == 1
    assert "Log Analytics CLI extension\tFAIL" in result.stdout
    assert "az extension add --name log-analytics" in _detail_of(
        result, "Log Analytics CLI extension"
    )


def test_doctor_does_not_query_the_workspace_without_the_extension(fake_az):
    """Fail closed: no point issuing a query the CLI cannot run."""
    fake_az.log_analytics_extension_installed = False

    run_doctor(fake_az)

    assert "monitor log-analytics" not in az_calls_for(fake_az)


def test_doctor_checks_the_extension_with_a_stable_command(fake_az):
    run_doctor(fake_az)

    assert "extension show --name log-analytics" in az_calls_for(fake_az)


# --- Prerequisite: azd authentication ------------------------------------


def test_doctor_reports_azd_authentication_from_check_status(fake_az):
    """`azd auth login --check-status` is azd's only non-interactive login
    read, and it is queried with `--output json` so the machine-readable
    status -- not a human sentence -- decides the row."""
    run_doctor(fake_az)

    azd_calls = azd_calls_for(fake_az)
    assert "auth login --check-status" in azd_calls
    assert "--output json" in azd_calls


def test_doctor_fails_when_azd_is_not_authenticated(fake_az):
    fake_az.azd_logged_in = False

    result = run_doctor(fake_az)

    assert result.returncode == 1
    assert "azd authentication\tFAIL" in result.stdout
    assert "azd auth login" in _detail_of(result, "azd authentication")


def test_doctor_does_not_trust_azd_check_status_exit_code(fake_az):
    """`azd auth login --check-status` always exits 0. A doctor that reads
    the exit status would report a signed-out operator as authenticated and
    then charge on into Azure calls."""
    fake_az.azd_logged_in = False

    result = run_doctor(fake_az)

    assert "azd authentication\tPASS" not in result.stdout
    assert "containerapp revision" not in az_calls_for(fake_az)


# --- Reader role assignment: direct vs inherited -------------------------


def test_doctor_reports_reader_assigned_directly_on_the_resource_group(fake_az):
    result = run_doctor(fake_az)

    assert result.returncode == 0, result.stdout + result.stderr
    detail = _detail_of(result, "Reader role assignment")
    assert "directly" in detail
    assert RESOURCE_GROUP in detail


def test_doctor_accepts_reader_inherited_from_the_subscription(fake_az):
    """Reader granted on the subscription gives the Agent the same effective
    read access on the lab resource group, so it must not be a false FAIL --
    but the detail has to say it is inherited, not a direct assignment."""
    fake_az.reader_role_assigned[AGENT_UAMI_PRINCIPAL_ID] = False
    fake_az.reader_role_inherited[AGENT_UAMI_PRINCIPAL_ID] = True

    result = run_doctor(fake_az)

    assert result.returncode == 0, result.stdout + result.stderr
    detail = _detail_of(result, "Reader role assignment")
    assert "inherited" in detail
    assert AGENT_UAMI_PRINCIPAL_ID in detail
    assert SUBSCRIPTION_SCOPE in detail


def test_doctor_asks_azure_for_inherited_role_assignments(fake_az):
    """Without `--include-inherited`, `az role assignment list` hides
    parent-scope grants entirely."""
    run_doctor(fake_az)

    role_calls = [
        line for line in az_calls_for(fake_az).splitlines() if line.startswith("role assignment")
    ]
    assert role_calls
    for call in role_calls:
        assert "--include-inherited" in call


def test_doctor_still_fails_when_no_reader_exists_at_any_scope(fake_az):
    fake_az.reader_role_assigned[AGENT_PRINCIPAL_ID] = False
    fake_az.reader_role_inherited[AGENT_PRINCIPAL_ID] = False

    result = run_doctor(fake_az)

    assert result.returncode == 1
    detail = _detail_of(result, "Reader role assignment")
    assert AGENT_PRINCIPAL_ID in detail
    assert "az role assignment create" in detail


# --- Malformed agent-setup.json ------------------------------------------


def test_doctor_fails_gracefully_on_malformed_agent_setup_evidence(fake_az):
    """A truncated/hand-edited evidence file must be one FAIL row, not a raw
    `jq` abort that kills the run mid-report."""
    fake_az.agent_setup_body = '{"agent_principal_id": "8c8a4f0e"'

    result = run_doctor(fake_az)

    assert result.returncode == 1
    assert "Reader role assignment\tFAIL" in result.stdout
    detail = _detail_of(result, "Reader role assignment")
    assert "valid JSON" in detail
    assert "lab.sh acknowledge agent-setup" in detail


def test_doctor_finishes_the_report_after_malformed_agent_setup_evidence(fake_az):
    """The rows after the failing check still have to be printed, and the
    raw parser error must not leak to stderr."""
    fake_az.agent_setup_body = "not json at all"

    result = run_doctor(fake_az)

    assert "Response plan\tMANUAL" in result.stdout
    assert "parse error" not in result.stderr
    assert "jq:" not in result.stderr


def test_doctor_fails_when_agent_setup_evidence_is_valid_json_but_empty(fake_az):
    fake_az.agent_setup_body = "{}"

    result = run_doctor(fake_az)

    assert result.returncode == 1
    assert "Reader role assignment\tFAIL" in result.stdout
    assert "agent_principal_id" in _detail_of(result, "Reader role assignment")
