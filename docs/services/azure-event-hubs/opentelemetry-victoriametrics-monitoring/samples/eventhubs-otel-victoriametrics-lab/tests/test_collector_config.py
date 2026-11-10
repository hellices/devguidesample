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

    for source in ("azure_monitor_api", "diagnostic_eventhub", "lag_exporter", "collector_self"):
        scrape = pipelines[f"metrics/{source}-scrape"]
        push = pipelines[f"metrics/{source}-remote_write"]
        assert scrape["receivers"] == push["receivers"]
        assert scrape["exporters"] == ["prometheus"]
        assert push["exporters"] == ["prometheusremotewrite"]
        assert f"resource/source_{source}" in scrape["processors"]
        assert f"resource/source_{source}" in push["processors"]
        assert "resource/delivery_scrape" in scrape["processors"]
        assert "resource/delivery_remote_write" in push["processors"]
        # Apart from the delivery stamp, both pipelines process data identically.
        strip = lambda processors: [p for p in processors if not p.startswith("resource/delivery_")]
        assert strip(scrape["processors"]) == strip(push["processors"])


def test_exporters_promote_only_lab_labels():
    exporters = render_config(BASE_ENV)["exporters"]

    assert exporters["prometheus"]["endpoint"] == "0.0.0.0:8889"
    assert exporters["prometheusremotewrite"]["endpoint"] == "http://10.42.2.20:8428/api/v1/write"
    for exporter in exporters.values():
        assert exporter["resource_constant_labels"] == {"included": ["source_path", "delivery_path"]}
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
    for delivery in ("scrape", "remote_write"):
        dedicated = pipelines[f"metrics/azure_monitor_dedicated-{delivery}"]
        assert dedicated["receivers"] == ["azure_monitor/dedicated"]
        assert "filter/dedicated" in dedicated["processors"]
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
    for delivery, exporter in (("scrape", "prometheus"), ("remote_write", "prometheusremotewrite")):
        pipeline = pipelines[f"metrics/fallback_exporter-{delivery}"]
        assert pipeline["receivers"] == ["prometheus/fallback"]
        assert pipeline["exporters"] == [exporter]
        assert "resource/source_fallback_exporter" in pipeline["processors"]
    scrape = config["receivers"]["prometheus/fallback"]["config"]["scrape_configs"][0]
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

    assert "filter/lag" in pipelines["metrics/lag_exporter-scrape"]["processors"]
    assert "filter/lag" not in pipelines["metrics/azure_monitor_api-scrape"]["processors"]
    assert "eventhubs_" in config["processors"]["filter/lag"]["metric_conditions"][0]
