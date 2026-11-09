"""Render the OpenTelemetry Collector configuration for the Event Hubs gateway.

Every source is fanned out into two pipelines so that the Prometheus scrape path and the
Prometheus remote write path receive the same receiver output. Each pipeline stamps
``source_path`` and ``delivery_path`` resource attributes, and both exporters promote only
those two attributes to labels.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path

import yaml

PREMIUM_METRICS = {
    "NamespaceCpuUsage": ["Average", "Maximum"],
    "NamespaceMemoryUsage": ["Average", "Maximum"],
    "IncomingRequests": ["Total"],
    "SuccessfulRequests": ["Total"],
    "ThrottledRequests": ["Total"],
    "IncomingMessages": ["Total"],
    "OutgoingMessages": ["Total"],
    "IncomingBytes": ["Total"],
    "OutgoingBytes": ["Total"],
}

# Dedicated cluster metrics differ in meaning: CPU and AvailableMemory use the Role
# dimension and Maximum aggregation, and ClusterUtilization is preview.
DEDICATED_METRICS = {
    "CPU": ["Maximum"],
    "AvailableMemory": ["Maximum"],
    "ClusterUtilization": ["Average"],
    "IncomingMessages": ["Total"],
    "OutgoingMessages": ["Total"],
    "IncomingBytes": ["Total"],
    "OutgoingBytes": ["Total"],
}

DELIVERY_EXPORTERS = {
    "scrape": "prometheus",
    "remote_write": "prometheusremotewrite",
}

LABELS = ["source_path", "delivery_path"]
REQUIRED = (
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP",
    "TELEMETRY_NAMESPACE",
    "TELEMETRY_EVENTHUB_NAME",
    "CHECKPOINT_ACCOUNT_URL",
    "GATEWAY_CLIENT_ID",
)


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _resource_processor(key: str, value: str) -> dict:
    return {"attributes": [{"key": key, "action": "upsert", "value": value}]}


def _dedicated_parts(resource_id: str) -> tuple[str, str]:
    parts = resource_id.strip("/").split("/")
    lowered = [part.lower() for part in parts]
    try:
        subscription = parts[lowered.index("subscriptions") + 1]
        resource_group = parts[lowered.index("resourcegroups") + 1]
    except (ValueError, IndexError) as error:
        raise ValueError("EXISTING_DEDICATED_CLUSTER_RESOURCE_ID is not a resource ID") from error
    if "microsoft.eventhub/clusters" not in "/".join(lowered):
        raise ValueError("EXISTING_DEDICATED_CLUSTER_RESOURCE_ID must be a Microsoft.EventHub/clusters ID")
    return subscription, resource_group


def render_config(env: Mapping[str, str]) -> dict:
    missing = [name for name in REQUIRED if not env.get(name)]
    if missing:
        raise ValueError(f"missing collector settings: {', '.join(missing)}")

    api_enabled = _flag(env, "ENABLE_API_RECEIVER", True)
    fallback_enabled = _flag(env, "ENABLE_FALLBACK_EXPORTER", False)
    vmsingle_url = env.get("VMSINGLE_URL", "http://10.42.2.20:8428").rstrip("/")
    dedicated_id = env.get("EXISTING_DEDICATED_CLUSTER_RESOURCE_ID", "").strip()

    extensions = {
        "health_check": {"endpoint": "0.0.0.0:13133"},
        "azure_auth": {"managed_identity": {"client_id": env["GATEWAY_CLIENT_ID"]}},
    }
    receivers: dict[str, dict] = {}
    # source_path -> receiver IDs
    sources: dict[str, list[str]] = {}

    if api_enabled:
        receivers["azure_monitor/premium"] = {
            "subscription_ids": [env["AZURE_SUBSCRIPTION_ID"]],
            "resource_groups": [env["AZURE_RESOURCE_GROUP"]],
            "services": ["Microsoft.EventHub/namespaces"],
            "resource_tags": [{"name": "otel-metrics-source", "value": "premium"}],
            "collection_interval": "60s",
            "initial_delay": "5s",
            # metrics:getBatch is authorized at subscription scope; namespace-scoped Monitoring Reader
            # is enough for the per-resource ARM metrics API, which is all a single namespace needs.
            "use_batch_api": _flag(env, "AZURE_MONITOR_USE_BATCH_API", False),
            "auth": {"authenticator": "azure_auth"},
            "metrics": {"microsoft.eventhub/namespaces": PREMIUM_METRICS},
            # Split by EntityName/OperationResult, Azure returns no time series while nothing is
            # throttled. Without a split it returns an explicit 0, which separates "no throttling"
            # from "no data".
            "dimensions": {
                "enabled": True,
                "overrides": {"Microsoft.EventHub/namespaces": {"ThrottledRequests": []}},
            },
        }
        sources["azure_monitor_api"] = ["azure_monitor/premium"]

        if dedicated_id:
            subscription, resource_group = _dedicated_parts(dedicated_id)
            receivers["azure_monitor/dedicated"] = {
                "subscription_ids": [subscription],
                "resource_groups": [resource_group],
                "services": ["Microsoft.EventHub/clusters"],
                "collection_interval": "60s",
                "initial_delay": "5s",
                "auth": {"authenticator": "azure_auth"},
                "metrics": {"microsoft.eventhub/clusters": DEDICATED_METRICS},
            }
            # A separate source keeps Dedicated Incoming/Outgoing series out of the Premium per-PU panels.
            sources["azure_monitor_dedicated"] = ["azure_monitor/dedicated"]

    receivers["azure_event_hub/diagnostic"] = {
        "event_hub": {
            "name": env["TELEMETRY_EVENTHUB_NAME"],
            "namespace": env["TELEMETRY_NAMESPACE"],
        },
        "auth": "azure_auth",
        "group": env.get("TELEMETRY_CONSUMER_GROUP", "otel-collector"),
        "format": "azure",
        "blob_checkpoint_store": {
            "storage_account_url": env["CHECKPOINT_ACCOUNT_URL"].rstrip("/"),
            "container_name": env.get("COLLECTOR_CHECKPOINT_CONTAINER", "collector-checkpoints"),
        },
    }
    sources["diagnostic_eventhub"] = ["azure_event_hub/diagnostic"]

    receivers["prometheus/lag"] = {
        "config": {
            "scrape_configs": [
                {
                    "job_name": "eventhubs-lag-exporter",
                    "scrape_interval": "15s",
                    "static_configs": [{"targets": [env.get("LAG_EXPORTER_TARGET", "lag-exporter:9464")]}],
                }
            ]
        }
    }
    sources["lag_exporter"] = ["prometheus/lag"]

    receivers["prometheus/self"] = {
        "config": {
            "scrape_configs": [
                {
                    "job_name": "otel-collector",
                    "scrape_interval": "30s",
                    "static_configs": [{"targets": ["127.0.0.1:8888"]}],
                }
            ]
        }
    }
    sources["collector_self"] = ["prometheus/self"]

    if fallback_enabled:
        receivers["prometheus/fallback"] = {
            "config": {
                "scrape_configs": [
                    {
                        "job_name": "azure-metrics-exporter",
                        "scrape_interval": "60s",
                        "scrape_timeout": "50s",
                        "metrics_path": "/probe/metrics/list",
                        "params": {
                            "subscription": [env["AZURE_SUBSCRIPTION_ID"]],
                            "filter": [
                                "resourceType eq 'Microsoft.EventHub/namespaces' "
                                f"and resourceGroup eq '{env['AZURE_RESOURCE_GROUP']}'"
                            ],
                            "metric": [",".join(PREMIUM_METRICS)],
                            "interval": ["PT1M"],
                            "timespan": ["PT5M"],
                            "aggregation": ["average,maximum,total"],
                        },
                        "static_configs": [{"targets": ["azure-metrics-exporter:8080"]}],
                        # The ARM filter cannot combine a tag condition, so keep only the Premium namespace here.
                        "metric_relabel_configs": [
                            {
                                "source_labels": ["resourceID"],
                                "regex": f"(?i).*/namespaces/{env.get('PREMIUM_NAMESPACE_NAME', '.+')}",
                                "action": "keep",
                            }
                        ],
                    }
                ]
            }
        }
        sources["fallback_exporter"] = ["prometheus/fallback"]

    processors: dict[str, dict] = {
        "memory_limiter": {"check_interval": "5s", "limit_percentage": 75, "spike_limit_percentage": 20},
        "batch": {"timeout": "5s"},
    }
    # The lag exporter also exposes Python runtime metrics; keep only the lab's lag signals.
    processors["filter/lag"] = {
        "error_mode": "ignore",
        "metric_conditions": ['not IsMatch(metric.name, "^(eventhubs_.*|up)$")'],
    }
    # Keep only component throughput and failure counters from the Collector's own telemetry.
    processors["filter/self"] = {
        "error_mode": "ignore",
        "metric_conditions": ['not IsMatch(metric.name, "^otelcol_(receiver|exporter)_.*")'],
    }
    if "azure_monitor_dedicated" in sources:
        # The receiver scopes by resource group and type only; drop every other cluster in that group.
        processors["filter/dedicated"] = {
            "error_mode": "ignore",
            "metric_conditions": [
                'ConvertCase(datapoint.attributes["azuremonitor.resource_id"], "lower") != '
                f'"{dedicated_id.lower()}"'
            ],
        }
    for source in sources:
        processors[f"resource/source_{source}"] = _resource_processor("source_path", source)
    for delivery in DELIVERY_EXPORTERS:
        processors[f"resource/delivery_{delivery}"] = _resource_processor("delivery_path", delivery)

    exporters = {
        "prometheus": {
            "endpoint": "0.0.0.0:8889",
            "metric_expiration": "10m",
            "resource_constant_labels": {"included": LABELS},
        },
        "prometheusremotewrite": {
            "endpoint": f"{vmsingle_url}/api/v1/write",
            "tls": {"insecure": True},
            "resource_constant_labels": {"included": LABELS},
            "remote_write_queue": {"enabled": True, "queue_size": 10000, "num_consumers": 2},
        },
    }

    pipelines = {}
    for source, receiver_ids in sources.items():
        for delivery, exporter in DELIVERY_EXPORTERS.items():
            pipelines[f"metrics/{source}-{delivery}"] = {
                "receivers": receiver_ids,
                "processors": [
                    "memory_limiter",
                    *(["filter/lag"] if source == "lag_exporter" else []),
                    *(["filter/self"] if source == "collector_self" else []),
                    *(["filter/dedicated"] if source == "azure_monitor_dedicated" else []),
                    f"resource/source_{source}",
                    f"resource/delivery_{delivery}",
                    "batch",
                ],
                "exporters": [exporter],
            }

    return {
        "extensions": extensions,
        "receivers": receivers,
        "processors": processors,
        "exporters": exporters,
        "service": {
            "extensions": ["health_check", "azure_auth"],
            "telemetry": {
                "logs": {"level": env.get("COLLECTOR_LOG_LEVEL", "info")},
                "metrics": {
                    "level": "detailed",
                    "readers": [
                        {"pull": {"exporter": {"prometheus": {"host": "0.0.0.0", "port": 8888}}}}
                    ],
                },
            },
            "pipelines": pipelines,
        },
    }


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = render_config(read_env_file(args.env_file))
    args.output.write_text(yaml.safe_dump(config, sort_keys=False))


if __name__ == "__main__":
    main()
