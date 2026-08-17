import re
from pathlib import Path


INFRA = Path(__file__).parents[1]
CASE_BICEP = INFRA / "dynamic-threshold-case.bicep"
LAB_BICEP = INFRA / "lab.bicep"
MAIN_BICEP = INFRA / "main.bicep"


def test_standard_web_test_produces_one_bounded_baseline_request():
    template = CASE_BICEP.read_text()

    assert "Microsoft.Insights/webTests@2022-06-15" in template
    assert "kind: 'standard'" in template
    assert "Frequency: 300" in template
    assert "Timeout: 15" in template
    assert "RetryEnabled: false" in template
    assert "RequestUrl: 'https://${containerAppFqdn}/api/orders'" in template
    assert "ExpectedHttpStatusCode: 200" in template
    assert "'hidden-link:${appInsightsResourceId}': 'Resource'" in template
    assert template.count("Id: 'us-va-ash-azr'") == 1
    assert "DurationMs is measured server-side" in template


def test_dynamic_rule_uses_the_s2_numeric_p95_signal():
    template = CASE_BICEP.read_text()

    assert "Microsoft.Insights/scheduledQueryRules@2025-01-01-preview" in template
    assert "criterionType: 'DynamicThresholdCriterion'" in template
    assert "alertSensitivity: 'Medium'" in template
    assert "operator: 'GreaterThan'" in template
    assert "metricMeasureColumn: 'P95DurationMs'" in template
    assert "percentile(DurationMs, 95)" in template
    assert "by bin(TimeGenerated, 5m)" in template
    assert 'AppRoleName == "{0}"' in template
    assert '| where Name has "/api/orders"' in template
    assert "timeAggregation: 'Average'" in template
    assert "timeAggregation: 'Maximum'" not in template
    assert "threshold:" not in template


def test_dynamic_rule_uses_five_minute_evaluation_and_two_of_four_failures():
    template = CASE_BICEP.read_text()

    assert "evaluationFrequency: 'PT5M'" in template
    assert "windowSize: 'PT20M'" in template
    assert "minFailingPeriodsToAlert: 2" in template
    assert "numberOfEvaluationPeriods: 4" in template
    assert re.search(r"actions:\s*\{\s*actionGroups:\s*\[\]\s*\}", template)


def test_dynamic_rule_targets_the_existing_workspace():
    template = CASE_BICEP.read_text()

    assert re.search(r"scopes:\s*\[\s*workspaceResourceId\s*\]", template)
    assert re.search(
        r"targetResourceTypes:\s*\[\s*'Microsoft\.OperationalInsights/workspaces'\s*\]",
        template,
    )


def test_case_module_is_wired_and_outputs_are_reexported():
    lab = LAB_BICEP.read_text()
    main = MAIN_BICEP.read_text()

    for value in (
        "workspaceResourceId: observability.outputs.workspaceId",
        "appInsightsResourceId: observability.outputs.appInsightsResourceId",
        "containerAppFqdn: workload.outputs.containerAppFqdn",
        "serviceName: workload.outputs.telemetryServiceName",
    ):
        assert value in lab

    assert "output baselineWebTestName string" in lab
    assert "output dynamicThresholdAlertName string" in lab
    assert "output AZURE_BASELINE_WEB_TEST_NAME string" in main
    assert "output AZURE_DYNAMIC_THRESHOLD_ALERT_NAME string" in main
