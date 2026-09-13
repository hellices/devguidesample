import re
from pathlib import Path


INFRA = Path(__file__).parents[1]
ALERTS_BICEP = INFRA / "alerts.bicep"
LAB_BICEP = INFRA / "lab.bicep"
MAIN_BICEP = INFRA / "main.bicep"
OBSERVABILITY_BICEP = INFRA / "observability.bicep"


def _alerts_module_block():
    """The `module alerts 'alerts.bicep'` declaration in lab.bicep."""
    template = LAB_BICEP.read_text()
    match = re.search(r"^module alerts 'alerts\.bicep'.*?^}$", template, re.MULTILINE | re.DOTALL)
    assert match, "lab.bicep must still declare the alerts module"
    return match.group(0)


def test_auto_mitigation_does_not_enable_action_suppression():
    template = ALERTS_BICEP.read_text()

    assert "autoMitigate: true" in template
    assert "muteActionsDuration:" not in template


def test_queries_use_workspace_schema_known_tables():
    """Live evidence (2026-08-14, `az deployment group validate` against the
    lab's real Log Analytics workspace): a
    Microsoft.Insights/scheduledQueryRules@2023-12-01 rule whose query reads
    the workspace-schema tables `AppRequests`/`AppDependencies`, scoped to the
    `Microsoft.OperationalInsights/workspaces` resource, validates at
    `evaluationFrequency: PT1M`. The same rule scoped to the Application
    Insights component with the legacy resource-centric tables
    `requests`/`dependencies` is rejected with `QueryNotContainKnownTable`,
    because those are not known tables for one-minute frequency.
    """
    template = ALERTS_BICEP.read_text()

    assert "\nAppRequests\n" in template
    assert "\nAppDependencies\n" in template
    assert "\nrequests\n" not in template
    assert "\ndependencies\n" not in template


def test_alert_rules_scope_and_target_the_log_analytics_workspace():
    """The known workspace tables live in the Log Analytics workspace, so the
    rule must be scoped to the workspace resource ID and declare the workspace
    resource type. Keeping the Application Insights component scope with those
    queries is what produced `QueryNotContainKnownTable` live.
    """
    template = ALERTS_BICEP.read_text()

    assert "param workspaceResourceId string" in template
    assert "appInsightsResourceId" not in template
    assert re.search(r"scopes:\s*\[\s*workspaceResourceId\s*\]", template)
    assert re.search(
        r"targetResourceTypes:\s*\[\s*'Microsoft\.OperationalInsights/workspaces'\s*\]",
        template,
    )
    assert "'Microsoft.Insights/components'" not in template


def test_queries_use_exact_workspace_column_casing():
    """`scripts/query-evidence.sh` already reads the same tables with the
    workspace schema's exact casing (TimeGenerated, AppRoleName, Name,
    ResultCode, DurationMs, Target). KQL column names are case sensitive, so
    the alert queries must not keep the legacy lowercase Application Insights
    column names.
    """
    template = ALERTS_BICEP.read_text()

    for column in (
        "| where TimeGenerated > ago(5m)",
        'AppRoleName == "{0}"',
        "| where Name has",
        "| where ResultCode ==",
        "DurationMs",
        "| where Target has",
    ):
        assert column in template, column

    for legacy in (
        "timestamp >",
        "cloud_RoleName",
        "| where name has",
        "| where resultCode ==",
        "| where target has",
        "percentile(duration,",
    ):
        assert legacy not in template, legacy


def test_request_duration_is_used_as_numeric_milliseconds():
    """AppRequests.DurationMs is already a numeric millisecond value, so the
    p95 aggregation needs no timespan conversion.
    """
    template = ALERTS_BICEP.read_text()

    assert "DurationMs / 1ms" not in template
    assert "percentile(DurationMs, 95)" in template


def test_blob_authorization_alert_matches_http_403_result_code():
    template = ALERTS_BICEP.read_text()

    assert '| where ResultCode == "403"' in template


def test_http500_alert_isolated_to_orders_and_exact_500():
    template = ALERTS_BICEP.read_text()

    assert '| where Name has "/api/orders"' in template
    assert '| where ResultCode == "500"' in template
    assert 'param serviceName string' in template
    assert 'AppRoleName == "{0}"' in template
    assert "''', serviceName)" in template


def test_evaluation_frequency_is_one_minute_over_a_five_minute_window():
    """PT1M was never the defect: the live validation that failed used the
    legacy Application Insights schema on the component scope. With the
    workspace-schema query and workspace scope, `az deployment group validate`
    accepts `evaluationFrequency: PT1M` with `windowSize: PT5M`, which is the
    cadence the lab's fire/resolve timeouts and the guides assume.
    """
    template = ALERTS_BICEP.read_text()

    assert "evaluationFrequency: 'PT1M'" in template
    assert "evaluationFrequency: 'PT5M'" not in template
    assert "windowSize: 'PT5M'" in template


def test_lab_bicep_wires_the_workspace_resource_id_into_the_alert_rules():
    """The alert scope now comes from the observability module's workspace,
    not from the Application Insights component.
    """
    module = _alerts_module_block()

    assert "workspaceResourceId: observability.outputs.workspaceId" in module
    assert "appInsightsResourceId" not in module


def test_workspace_resource_id_is_exposed_through_every_module():
    """observability -> lab -> main must keep publishing the workspace
    resource ID the alert rules are scoped to, so an operator can look the
    rule scope up from the deployment outputs.
    """
    assert "output workspaceId string = workspace.id" in OBSERVABILITY_BICEP.read_text()
    assert "output workspaceId string = observability.outputs.workspaceId" in LAB_BICEP.read_text()
    assert "output workspaceId string = lab.outputs.workspaceId" in MAIN_BICEP.read_text()


def test_alert_rules_require_and_pass_through_caller_tags():
    """azure.yaml's azd main.bicep now centralizes tag construction
    (purpose, azd-env-name, expiresOn) and passes the merged object down
    through lab.bicep. alerts.bicep must keep accepting an arbitrary,
    required tags object and applying it verbatim to each alert rule
    rather than defaulting or hardcoding its own tags.
    """
    template = ALERTS_BICEP.read_text()

    assert "param tags object\n" in template
    assert "tags: tags" in template

