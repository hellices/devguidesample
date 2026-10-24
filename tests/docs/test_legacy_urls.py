from pathlib import Path

from scripts.docs.content import load_taxonomy
from scripts.docs.topics import build_topic_catalog


ROOT = Path(__file__).parents[2]
# redirect_from paths of URLs published by earlier layouts. Remove an entry only to
# retire that public URL on purpose.
LEGACY_PAGES = """
cases/azure-ai-search/eventual-consistency-reindex/index.md
cases/azure-api-management/mcp-entra-validation/index.md
cases/azure-kubernetes-service/file-io-throttling/index.md
cases/azure-kubernetes-service/netapp-files-cpu-io-wait/index.md
cases/azure-kubernetes-service/pod-database-query-latency/index.md
cases/azure-managed-redis/cluster-failover-recovery/index.md
guides/application-development/nodejs-file-io-cpu/index.md
guides/azure-ai-search/custom-embedding-ingestion/index.md
guides/azure-ai-search/custom-web-api-vectorization/index.md
guides/azure-ai-search/gpu-vllm-rag/index.md
guides/azure-ai-search/korean-analyzer-comparison/index.md
guides/azure-api-management/mcp-entra-private-access/index.md
guides/azure-application-gateway/sse-response-buffering/index.md
guides/azure-application-gateway/waf-path-ip-allowlist/index.md
guides/azure-architecture/mcp-configuration/index.md
guides/azure-architecture/response-time-optimization/index.md
guides/azure-automation/portal-cli-limitations/index.md
guides/azure-cosmos-db/nodejs-client-optimization/index.md
guides/azure-cosmos-db/nodejs-dns-lookup-bottleneck/index.md
guides/azure-cosmos-db/point-read-optimization/index.md
guides/azure-database-for-mysql/blue-green-upgrade/index.md
guides/azure-database-for-mysql/nodejs-read-write-routing/index.md
guides/azure-kubernetes-service/argocd-image-updater-acr/index.md
guides/azure-kubernetes-service/authorization-troubleshooting/index.md
guides/azure-kubernetes-service/cni-overlay-nsg/index.md
guides/azure-kubernetes-service/kaito-open-source-model/index.md
guides/azure-kubernetes-service/pod-affinity-distribution/index.md
guides/azure-kubernetes-service/pod-scheduling-agent-pools/index.md
guides/azure-kubernetes-service/pyroscope-anf-s3/index.md
guides/azure-kubernetes-service/python-memory-leak-memray/index.md
guides/azure-kubernetes-service/remote-cluster-local-development/index.md
guides/azure-kubernetes-service/spot-h100-kaito/index.md
guides/azure-kubernetes-service/workload-identity-databricks/index.md
guides/azure-load-testing/locust-appgw-aks-private/index.md
guides/azure-monitor/aks-private-opentelemetry/index.md
guides/azure-monitor/azure-sre-agent-overview/index.md
guides/azure-monitor/hdinsight-kafka-prometheus-grafana/index.md
guides/azure-monitor/sre-agent-dynamic-thresholds/index.md
guides/azure-monitor/sre-agent-incident-runbook/index.md
guides/azure-openai/adaptive-ptu-load-balancing/index.md
guides/azure-storage/mobile-resumable-upload-tus/index.md
guides/microsoft-foundry/codex-closed-network/index.md
guides/microsoft-foundry/foundry-local-air-gapped/index.md
guides/microsoft-foundry/gpt-memory-layer/index.md
labs/azure-api-management/mcp-rest-and-upstream/index.md
labs/azure-architecture/mcp-configuration/index.md
labs/azure-monitor/sre-agent-event-lab-setup/index.md
labs/azure-monitor/sre-agent-event-lab/index.md
labs/azure-monitor/sre-agent-results/index.md
labs/azure-monitor/sre-agent-scenario-blob-permission/index.md
labs/azure-monitor/sre-agent-scenario-http-500/index.md
labs/azure-monitor/sre-agent-scenario-latency/index.md
research/azure-ai-search/a10-vs-t4-embedding-benchmark/index.md
research/azure-ai-search/bge-m3-vs-qwen3-embedding/index.md
research/azure-ai-search/rag-chunking-strategies/index.md
research/azure-api-management/mcp-authentication-options/index.md
research/azure-hdinsight/kafka-catchup-sku-fetch-benchmark/index.md
research/azure-monitor/dynamic-thresholds-brief/index.md
research/azure-monitor/hdinsight-kafka-monitoring-options/index.md
research/azure-monitor/sre-agent-validation-results/index.md
research/microsoft-foundry/agent-framework-2026/index.md
research/microsoft-foundry/agent-memory-architecture-patterns/index.md
research/microsoft-foundry/agent-memory-commerce/index.md
research/microsoft-foundry/agent-memory-frameworks/index.md
research/microsoft-foundry/agent-memory-overview/index.md
research/microsoft-foundry/agent-memory-pipeline-retrieval/index.md
research/microsoft-foundry/agent-memory-production-evaluation/index.md
research/microsoft-foundry/agent-memory-taxonomy/index.md
""".split()


def test_legacy_public_urls_still_redirect_to_current_documents() -> None:
    catalog = build_topic_catalog(ROOT / "docs", load_taxonomy(ROOT / "docs-taxonomy.yml"))
    assert len(LEGACY_PAGES) == len(set(LEGACY_PAGES))
    missing = sorted(set(LEGACY_PAGES) - {path.as_posix() for path in catalog.redirects})
    assert not missing, "legacy URLs are no longer declared in any redirect_from: " + ", ".join(missing)
