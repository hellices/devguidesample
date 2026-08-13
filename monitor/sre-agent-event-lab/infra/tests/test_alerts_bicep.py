from pathlib import Path


ALERTS_BICEP = Path(__file__).parents[1] / "alerts.bicep"


def test_auto_mitigation_does_not_enable_action_suppression():
    template = ALERTS_BICEP.read_text()

    assert "autoMitigate: true" in template
    assert "muteActionsDuration:" not in template


def test_queries_use_application_insights_resource_schema():
    template = ALERTS_BICEP.read_text()

    assert "AppRequests" not in template
    assert "AppDependencies" not in template
    assert "\nrequests\n" in template
    assert "\ndependencies\n" in template


def test_request_duration_is_used_as_numeric_milliseconds():
    template = ALERTS_BICEP.read_text()

    assert "duration / 1ms" not in template
    assert "percentile(duration, 95)" in template


def test_blob_authorization_alert_matches_http_403_result_code():
    template = ALERTS_BICEP.read_text()

    assert '| where resultCode == "403"' in template


def test_http500_alert_isolated_to_orders_and_exact_500():
    template = ALERTS_BICEP.read_text()

    assert '| where name has "/api/orders"' in template
    assert '| where resultCode == "500"' in template
    assert 'param serviceName string' in template
    assert 'cloud_RoleName == "{0}"' in template
    assert "''', serviceName)" in template
