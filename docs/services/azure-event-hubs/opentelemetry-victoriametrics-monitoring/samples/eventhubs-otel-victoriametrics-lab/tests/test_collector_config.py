import re
import sys
from pathlib import Path

import pytest
import yaml

LAB_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(LAB_ROOT / "gateway"))

from render_collector import render_config  # noqa: E402

BASE_ENV = {
    "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
    "AZURE_RESOURCE_GROUP": "rg-example",
    "PREMIUM_NAMESPACE_NAME": "ehp-example",
    "TELEMETRY_NAMESPACE": "eht-example.servicebus.windows.net",
    "TELEMETRY_EVENTHUB_NAME": "platform-metrics",
    "CHECKPOINT_ACCOUNT_URL": "https://stexample.blob.core.windows.net/",
    "GATEWAY_CLIENT_ID": "11111111-1111-1111-1111-111111111111",
}
DEDICATED_ID = (
    "/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/rg-existing"
    "/providers/Microsoft.EventHub/clusters/ehd-existing"
)


def test_every_source_fans_out_to_both_delivery_paths():
    config = render_config(BASE_ENV)
    pipelines = config["service"]["pipelines"]

    expected_receivers = {
        "azure_monitor_api": ["azure_monitor/premium"],
        "diagnostic_eventhub": ["azure_event_hub/diagnostic"],
        "lag_exporter": ["prometheus/lag"],
        "collector_self": ["prometheus/self"],
    }
    assert set(pipelines) == {f"metrics/{source}-{delivery}" for source in expected_receivers
                              for delivery in ("scrape", "remote_write")}
    for source, receivers in expected_receivers.items():
        _assert_fans_out(pipelines, source, receivers)


def _assert_fans_out(pipelines, source, receivers):
    """The source reads its own receivers into exactly two pipelines that differ only in delivery."""
    scrape = pipelines[f"metrics/{source}-scrape"]
    push = pipelines[f"metrics/{source}-remote_write"]
    # Each source must read its own receiver, so data can never be labelled with another source.
    assert scrape["receivers"] == push["receivers"] == receivers
    assert scrape["exporters"] == ["prometheus"]
    assert push["exporters"] == ["prometheusremotewrite"]
    for pipeline, delivery in ((scrape, "scrape"), (push, "remote_write")):
        assert f"resource/source_{source}" in pipeline["processors"]
        # Exactly one delivery stamp, the right one: a second stamp would overwrite delivery_path.
        stamps = [p for p in pipeline["processors"] if p.startswith("resource/delivery_")]
        assert stamps == [f"resource/delivery_{delivery}"], (source, stamps)
    # Apart from the delivery stamp, both pipelines process data identically.
    strip = lambda processors: [p for p in processors if not p.startswith("resource/delivery_")]
    assert strip(scrape["processors"]) == strip(push["processors"])


def test_exporters_promote_only_lab_labels():
    exporters = render_config(BASE_ENV)["exporters"]

    assert exporters["prometheus"]["endpoint"] == "0.0.0.0:8889"
    assert exporters["prometheusremotewrite"]["endpoint"] == "http://10.42.2.250:8428/api/v1/write"
    for exporter in exporters.values():
        assert exporter["resource_constant_labels"] == {
            "included": ["source_path", "delivery_path", "azure.resource.id"]}
        assert "resource_to_telemetry_conversion" not in exporter


def test_api_receiver_uses_managed_identity_and_premium_allowlist():
    config = render_config(BASE_ENV)
    receiver = config["receivers"]["azure_monitor/premium"]

    assert config["extensions"]["azure_auth"] == {
        "managed_identity": {"client_id": BASE_ENV["GATEWAY_CLIENT_ID"]}
    }
    assert receiver["auth"] == {"authenticator": "azure_auth"}
    assert receiver["resource_tags"] == [{"name": "otel-metrics-source", "value": "premium"}]
    assert receiver["use_batch_api"] is False
    assert receiver["dimensions"]["overrides"]["Microsoft.EventHub/namespaces"]["ThrottledRequests"] == []
    metrics = receiver["metrics"]["microsoft.eventhub/namespaces"]
    assert metrics["NamespaceCpuUsage"] == ["Average", "Maximum"]
    assert "OutgoingRequests" not in metrics


def test_diagnostic_receiver_uses_blob_checkpoint_without_connection_string():
    receiver = render_config(BASE_ENV)["receivers"]["azure_event_hub/diagnostic"]

    assert receiver["auth"] == "azure_auth"
    assert "connection" not in receiver
    assert receiver["blob_checkpoint_store"] == {
        "storage_account_url": "https://stexample.blob.core.windows.net",
        "container_name": "collector-checkpoints",
    }


def test_without_diagnostic_settings_hubs_only_the_api_lag_and_self_sources_remain():
    # Default deployment: no metric Diagnostic Settings and logs off means no telemetry namespace.
    env = {k: v for k, v in BASE_ENV.items() if not k.startswith("TELEMETRY_")}
    config = render_config(env | {"TELEMETRY_NAMESPACE": "", "TELEMETRY_EVENTHUB_NAME": ""})

    assert not [r for r in config["receivers"] if r.startswith("azure_event_hub/")]
    sources = {name.split("/")[1].rsplit("-", 1)[0] for name in config["service"]["pipelines"]}
    assert sources == {"azure_monitor_api", "lag_exporter", "collector_self"}


def test_logs_alone_still_read_the_telemetry_namespace():
    env = BASE_ENV | {"TELEMETRY_EVENTHUB_NAME": "", "TELEMETRY_LOGS_EVENTHUB_NAME": "runtime-logs"}
    receivers = render_config(env)["receivers"]

    assert "azure_event_hub/diagnostic" not in receivers
    assert receivers["azure_event_hub/runtime_logs"]["event_hub"]["namespace"] == "eht-example.servicebus.windows.net"


def test_a_diagnostic_hub_without_its_namespace_is_rejected():
    with pytest.raises(ValueError, match="TELEMETRY_NAMESPACE"):
        render_config(BASE_ENV | {"TELEMETRY_NAMESPACE": ""})


def test_dedicated_profile_is_absent_by_default():
    serialized = yaml.safe_dump(render_config(BASE_ENV))

    assert "microsoft.eventhub/clusters" not in serialized
    assert "ClusterUtilization" not in serialized


def test_dedicated_profile_requires_existing_cluster_id():
    config = render_config(BASE_ENV | {"EXISTING_DEDICATED_CLUSTER_RESOURCE_ID": DEDICATED_ID})
    receiver = config["receivers"]["azure_monitor/dedicated"]

    assert receiver["subscription_ids"] == ["22222222-2222-2222-2222-222222222222"]
    assert receiver["resource_groups"] == ["rg-existing"]
    metrics = receiver["metrics"]["microsoft.eventhub/clusters"]
    assert metrics["AvailableMemory"] == ["Maximum"]
    assert "NamespaceMemoryUsage" not in metrics
    pipelines = config["service"]["pipelines"]
    assert pipelines["metrics/azure_monitor_api-scrape"]["receivers"] == ["azure_monitor/premium"]
    _assert_fans_out(pipelines, "azure_monitor_dedicated", ["azure_monitor/dedicated"])
    for delivery in ("scrape", "remote_write"):
        assert "filter/dedicated" in pipelines[f"metrics/azure_monitor_dedicated-{delivery}"]["processors"]
        # The cluster filter would drop every namespace data point if it leaked into the Premium path.
        assert "filter/dedicated" not in pipelines[f"metrics/azure_monitor_api-{delivery}"]["processors"]
    # The filter drops a data point when this is true, so it must be exactly "not the chosen cluster".
    assert config["processors"]["filter/dedicated"]["metric_conditions"] == [
        f'ConvertCase(datapoint.attributes["azuremonitor.resource_id"], "lower") != "{DEDICATED_ID.lower()}"'
    ]
    assert "azure_monitor_api" not in yaml.safe_dump(pipelines["metrics/azure_monitor_dedicated-scrape"])


@pytest.mark.parametrize("resource_id", [
    "/subscriptions/x",
    DEDICATED_ID.rsplit("/", 1)[0],
    DEDICATED_ID.rsplit("/", 1)[0] + "/",
    DEDICATED_ID + "/eventhubs/hub",
    DEDICATED_ID.replace("Microsoft.EventHub", "Microsoft.Other"),
    DEDICATED_ID.replace("/clusters/", "/namespaces/"),
    DEDICATED_ID.lstrip("/"),
])
def test_dedicated_profile_rejects_non_cluster_ids(resource_id):
    with pytest.raises(ValueError):
        render_config(BASE_ENV | {"EXISTING_DEDICATED_CLUSTER_RESOURCE_ID": resource_id})


def test_dedicated_profile_accepts_case_insensitive_cluster_ids():
    config = render_config(BASE_ENV | {"EXISTING_DEDICATED_CLUSTER_RESOURCE_ID": DEDICATED_ID.lower()})
    assert config["receivers"]["azure_monitor/dedicated"]["resource_groups"] == ["rg-existing"]


def test_fallback_replaces_api_source_only_when_requested():
    config = render_config(BASE_ENV | {"ENABLE_API_RECEIVER": "false", "ENABLE_FALLBACK_EXPORTER": "true"})
    pipelines = config["service"]["pipelines"]

    assert "azure_monitor/premium" not in config["receivers"]
    assert not any(name.startswith("metrics/azure_monitor_api") for name in pipelines)
    _assert_fans_out(pipelines, "fallback_exporter", ["prometheus/fallback"])
    scrape_configs = config["receivers"]["prometheus/fallback"]["config"]["scrape_configs"]
    assert len(scrape_configs) == 1  # a second, unfiltered job would admit other namespaces
    scrape = scrape_configs[0]
    assert len(scrape["metric_relabel_configs"]) == 1
    assert scrape["metric_relabel_configs"][0]["action"] == "keep"
    # azure-metrics-exporter puts the ARM resource ID in resourceID; the regex must apply to it.
    assert scrape["metric_relabel_configs"][0]["source_labels"] == ["resourceID"]
    # Prometheus anchors relabel regexes: emulate that to prove only this namespace is kept.
    regex = scrape["metric_relabel_configs"][0]["regex"]
    assert regex.startswith("(?i)")
    keep = re.compile(f"^(?:{regex[4:]})$", re.IGNORECASE)
    prefix = "/subscriptions/s/resourceGroups/g/providers/Microsoft.EventHub/namespaces/"
    assert keep.match(prefix + "ehp-example") and keep.match(prefix.lower() + "EHP-EXAMPLE")
    assert not keep.match(prefix + "ehp-example-copy")
    assert not keep.match(prefix + "ehpXexample")
    assert "$" not in scrape["metric_relabel_configs"][0]["regex"]


def test_fallback_requires_the_premium_namespace_name():
    env = {k: v for k, v in BASE_ENV.items() if k != "PREMIUM_NAMESPACE_NAME"}
    with pytest.raises(ValueError, match="PREMIUM_NAMESPACE_NAME"):
        render_config(env | {"ENABLE_FALLBACK_EXPORTER": "true"})


def test_missing_settings_fail_closed():
    with pytest.raises(ValueError, match="GATEWAY_CLIENT_ID"):
        render_config({k: v for k, v in BASE_ENV.items() if k != "GATEWAY_CLIENT_ID"})


def test_lag_pipelines_drop_python_runtime_metrics():
    config = render_config(BASE_ENV)
    pipelines = config["service"]["pipelines"]

    for delivery in ("scrape", "remote_write"):
        assert "filter/lag" in pipelines[f"metrics/lag_exporter-{delivery}"]["processors"]
        # The self filter must be wired into both collector_self pipelines, not merely defined.
        assert "filter/self" in pipelines[f"metrics/collector_self-{delivery}"]["processors"]
    assert "filter/lag" not in pipelines["metrics/azure_monitor_api-scrape"]["processors"]
    # The filter drops a metric when the condition is true: keep eventhubs_* and up, drop the rest.
    assert config["processors"]["filter/lag"]["metric_conditions"] == [
        'not IsMatch(metric.name, "^(eventhubs_.*|up)$")'
    ]
    assert config["processors"]["filter/self"]["metric_conditions"] == [
        'not IsMatch(metric.name, "^otelcol_(receiver|exporter)_.*")'
    ]


def test_resource_logs_become_metrics_only_when_a_logs_hub_is_set():
    assert "connectors" not in render_config(BASE_ENV)
    config = render_config(BASE_ENV | {"TELEMETRY_LOGS_EVENTHUB_NAME": "runtime-logs"})

    receiver = config["receivers"]["azure_event_hub/runtime_logs"]
    assert receiver["event_hub"]["name"] == "runtime-logs"
    # The messaging log family needs the encoding extension; format and encoding are exclusive.
    assert receiver["encoding"] == "azure_encoding" and "format" not in receiver
    assert config["extensions"]["azure_encoding"] == {
        "logs": {"include_categories": ["ApplicationMetricsLogs", "RuntimeAuditLogs"]}}
    assert "azure_encoding" in config["service"]["extensions"]
    pipelines = config["service"]["pipelines"]
    assert pipelines["logs/runtime_logs"] == {
        "receivers": ["azure_event_hub/runtime_logs"],
        "processors": ["memory_limiter", "transform/runtime_logs"],
        "exporters": ["signal_to_metrics/runtime_logs"],
    }
    _assert_fans_out(pipelines, "diagnostic_logs", ["signal_to_metrics/runtime_logs"])
    for delivery in ("scrape", "remote_write"):
        assert "delta_to_cumulative" in pipelines[f"metrics/diagnostic_logs-{delivery}"]["processors"]
    log_metrics = config["connectors"]["signal_to_metrics/runtime_logs"]["logs"]
    # Exactly five definitions with unique names; a duplicate would be hidden by the dict below.
    assert len(log_metrics) == 5
    assert len({m["name"] for m in log_metrics}) == len(log_metrics)
    metrics = {m["name"]: m for m in log_metrics}
    assert set(metrics) == {"eventhubs_log_consumer_lag", "eventhubs_log_application_count",
                            "eventhubs_log_runtime_operations", "eventhubs_log_records",
                            "eventhubs_log_arrival_delay_seconds"}
    # Identifiers such as client IP or auth ID never become labels.
    keys = {a.get("key") for m in metrics.values() for a in m.get("attributes", [])}
    assert not keys & {"client.address", "azure.auth.id"}
    # Only a harmless resource attribute is kept, so service.name never turns into the job label.
    assert all(m["include_resource_attributes"] == [{"key": "cloud.provider"}] for m in metrics.values())
