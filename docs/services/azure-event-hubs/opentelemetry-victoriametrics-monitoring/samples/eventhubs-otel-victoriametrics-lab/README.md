# Event Hubs OpenTelemetry VictoriaMetrics lab

This runnable sample implements the Event Hubs observability design described by
the parent topic. It will provision Event Hubs Premium, an AKS-hosted
VictoriaMetrics deployment, and a Gateway VM hosting OpenTelemetry Collector
Contrib and Grafana OSS.

The implementation is intentionally marked `needs-review` until the complete
Azure deployment, metric queries, dashboard capture, and resource cleanup have
all been executed and recorded. It never provisions an Event Hubs Dedicated
cluster; the Dedicated configuration accepts only an existing cluster resource
ID.

See the [parent guide](../../index.md) for the current scope and official
references.
