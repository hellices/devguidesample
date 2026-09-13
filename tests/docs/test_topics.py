from __future__ import annotations

from pathlib import Path, PurePosixPath
import re

import pytest
import yaml

from scripts.docs.content import (
    DocumentFormatError,
    load_taxonomy,
    validate_document,
)
from scripts.docs.topics import build_topic_catalog


ROOT = Path(__file__).parents[2]


@pytest.fixture
def taxonomy() -> dict:
    return {
        "collections": {
            "guide": {
                "path": "guides",
                "statuses": ["current", "needs-review", "deprecated"],
                "required_fields": [
                    "last_verified",
                    "review_cycle_days",
                    "applies_to",
                ],
            }
        },
        "services": {"azure-monitor": "Azure Monitor"},
        "technologies": {"kubernetes": "Kubernetes"},
        "tags": {"networking": "Networking"},
        "verification_statuses": ["verified", "needs-review"],
        "official_source_hosts": ["learn.microsoft.com"],
        "required_source_host": "learn.microsoft.com",
    }


def write_document(
    root: Path,
    relative: str,
    title: str,
    *,
    topic_order: int | None = None,
    redirect_from: list[str] | None = None,
    services: list[str] | None = None,
) -> Path:
    metadata: dict[str, object] = {
        "title": title,
        "description": f"{title} description",
        "document_type": "guide",
        "services": services or ["azure-monitor"],
        "technologies": ["kubernetes"],
        "tags": ["networking"],
        "status": "current",
        "verification_status": "verified",
        "sources_checked_at": "2026-09-12",
        "official_sources": [
            {
                "title": "Azure Monitor documentation",
                "url": "https://learn.microsoft.com/azure/azure-monitor/",
            }
        ],
        "last_verified": "2026-09-12",
        "review_cycle_days": 180,
        "applies_to": ["Azure Monitor"],
    }
    if topic_order is not None:
        metadata["topic_order"] = topic_order
    if redirect_from is not None:
        metadata["redirect_from"] = redirect_from

    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n\n"
        + f"# {title}\n",
        encoding="utf-8",
    )
    return path


def write_sample(
    root: Path,
    relative: str,
    manifest: dict[str, object] | None = None,
    *,
    readme: bool = True,
) -> Path:
    sample_dir = root / relative
    sample_dir.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (sample_dir / "sample.yml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    if readme:
        (sample_dir / "README.md").write_text(
            "# Sample\n",
            encoding="utf-8",
        )
    return sample_dir


def test_build_topic_catalog_discovers_canonical_topic_documents_and_samples(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir = tmp_path / "docs"
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/index.md",
        "Agent topic",
    )
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/setup/index.md",
        "Setup",
        topic_order=1,
    )
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/results/index.md",
        "Results",
        topic_order=2,
    )
    write_sample(
        docs_dir,
        "services/azure-monitor/agent-topic/samples/event-lab",
        {
            "title": "Event lab",
            "description": "Reproduces the monitored incident.",
            "kind": "runnable",
            "used_by": ["setup", "results"],
        },
    )

    catalog = build_topic_catalog(docs_dir, taxonomy)
    topic = catalog.topics[("azure-monitor", "agent-topic")]

    assert topic.entry.relative_path == PurePosixPath(
        "services/azure-monitor/agent-topic/index.md"
    )
    assert [member.relative_path for member in topic.members] == [
        PurePosixPath("services/azure-monitor/agent-topic/index.md"),
        PurePosixPath("services/azure-monitor/agent-topic/setup/index.md"),
        PurePosixPath("services/azure-monitor/agent-topic/results/index.md"),
    ]
    assert catalog.position_by_document[topic.members[2].relative_path] == 2
    assert [
        sample.slug
        for sample in catalog.samples_by_document[topic.members[1].relative_path]
    ] == ["event-lab"]


def test_build_topic_catalog_does_not_leak_canonical_sample_ownership_to_legacy_aliases(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir = tmp_path / "docs"
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/index.md",
        "Agent topic",
    )
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/setup/index.md",
        "Setup",
        topic_order=1,
    )
    write_document(
        docs_dir,
        "guides/azure-monitor/agent-topic/index.md",
        "Legacy topic",
    )
    write_sample(
        docs_dir,
        "services/azure-monitor/agent-topic/samples/entry-lab",
        {
            "title": "Entry lab",
            "description": "Owned by the canonical entry only.",
            "kind": "runnable",
            "used_by": ["index"],
        },
    )

    catalog = build_topic_catalog(docs_dir, taxonomy)

    assert [sample.slug for sample in catalog.samples_by_document[PurePosixPath("services/azure-monitor/agent-topic/index.md")]] == [
        "entry-lab"
    ]
    assert catalog.samples_by_document[PurePosixPath("guides/azure-monitor/agent-topic/index.md")] == ()


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("missing root index", "topic entry document is missing"),
        ("child without topic_order", "topic_order must be a positive integer"),
        ("duplicate child order", "duplicate topic_order 1"),
        ("non-contiguous order", "topic_order values must be contiguous from 1"),
        ("nested grandchild", "child documents must be directly below the topic"),
        ("sample missing manifest", "sample.yml is required"),
        ("sample missing readme", "README.md is required"),
        ("invalid sample kind", "kind must be runnable or artifact"),
        ("empty used_by", "used_by must be a non-empty list"),
        ("unknown used_by", "unknown document slug"),
        ("duplicate redirect", "redirect_from path is already used"),
        (
            "canonical redirect collision",
            "redirect_from collides with a canonical document",
        ),
    ],
)
def test_build_topic_catalog_rejects_invalid_topic_and_sample_layouts(
    tmp_path: Path, taxonomy: dict, case: str, expected: str
) -> None:
    docs_dir = tmp_path / "docs"
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/index.md",
        "Agent topic",
    )
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/setup/index.md",
        "Setup",
        topic_order=1,
    )

    if case == "missing root index":
        (docs_dir / "services/azure-monitor/agent-topic/index.md").unlink()
    elif case == "child without topic_order":
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/results/index.md",
            "Results",
        )
    elif case == "duplicate child order":
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/results/index.md",
            "Results",
            topic_order=1,
        )
    elif case == "non-contiguous order":
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/results/index.md",
            "Results",
            topic_order=3,
        )
    elif case == "nested grandchild":
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/setup/deeper/index.md",
            "Deeper",
            topic_order=2,
        )
    elif case == "sample missing manifest":
        write_sample(
            docs_dir,
            "services/azure-monitor/agent-topic/samples/event-lab",
            None,
        )
    elif case == "sample missing readme":
        write_sample(
            docs_dir,
            "services/azure-monitor/agent-topic/samples/event-lab",
            {
                "title": "Event lab",
                "description": "Reproduces the monitored incident.",
                "kind": "runnable",
                "used_by": ["setup"],
            },
            readme=False,
        )
    elif case == "invalid sample kind":
        write_sample(
            docs_dir,
            "services/azure-monitor/agent-topic/samples/event-lab",
            {
                "title": "Event lab",
                "description": "Reproduces the monitored incident.",
                "kind": "broken",
                "used_by": ["setup"],
            },
        )
    elif case == "empty used_by":
        write_sample(
            docs_dir,
            "services/azure-monitor/agent-topic/samples/event-lab",
            {
                "title": "Event lab",
                "description": "Reproduces the monitored incident.",
                "kind": "runnable",
                "used_by": [],
            },
        )
    elif case == "unknown used_by":
        write_sample(
            docs_dir,
            "services/azure-monitor/agent-topic/samples/event-lab",
            {
                "title": "Event lab",
                "description": "Reproduces the monitored incident.",
                "kind": "runnable",
                "used_by": ["unknown"],
            },
        )
    elif case == "duplicate redirect":
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/results/index.md",
            "Results",
            topic_order=2,
            redirect_from=["guides/azure-monitor/shared/index.md"],
        )
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/verify/index.md",
            "Verify",
            topic_order=3,
            redirect_from=["guides/azure-monitor/shared/index.md"],
        )
    elif case == "canonical redirect collision":
        write_document(
            docs_dir,
            "guides/azure-monitor/shared/index.md",
            "Shared",
        )
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/results/index.md",
            "Results",
            topic_order=2,
            redirect_from=["guides/azure-monitor/shared/index.md"],
        )

    with pytest.raises(DocumentFormatError, match=re.escape(expected)):
        build_topic_catalog(docs_dir, taxonomy)


def test_validate_document_rejects_canonical_service_paths_absent_from_taxonomy(
    tmp_path: Path, taxonomy: dict
) -> None:
    path = write_document(
        tmp_path / "docs",
        "services/unknown-service/agent-topic/index.md",
        "Agent topic",
        services=["unknown-service"],
    )
    from scripts.docs.content import load_document

    document = load_document(path, docs_dir=tmp_path / "docs")

    errors = validate_document(document, taxonomy)

    assert "unknown service: unknown-service" in errors


def test_build_topic_catalog_preserves_all_legacy_paths_sharing_one_topic_key(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir = tmp_path / "docs"
    taxonomy["collections"]["lab"] = {
        "path": "labs",
        "statuses": ["verified"],
        "required_fields": [
            "last_verified",
            "review_cycle_days",
            "estimated_time",
            "cost",
            "cleanup_required",
        ],
    }
    guide = write_document(
        docs_dir,
        "guides/azure-monitor/agent-topic/index.md",
        "Guide legacy topic",
    )
    lab = write_document(
        docs_dir,
        "labs/azure-monitor/agent-topic/index.md",
        "Lab legacy topic",
    )
    lab.write_text(
        guide.read_text(encoding="utf-8").replace("document_type: guide", "document_type: lab"),
        encoding="utf-8",
    )

    catalog = build_topic_catalog(docs_dir, taxonomy)

    guide_path = PurePosixPath("guides/azure-monitor/agent-topic/index.md")
    lab_path = PurePosixPath("labs/azure-monitor/agent-topic/index.md")
    topic = catalog.topics[("azure-monitor", "agent-topic")]

    assert guide.relative_to(docs_dir).as_posix() in {
        document.relative_path.as_posix() for document in catalog.documents
    }
    assert lab.relative_to(docs_dir).as_posix() in {
        document.relative_path.as_posix() for document in catalog.documents
    }
    assert catalog.by_document[guide_path] == topic
    assert catalog.by_document[lab_path] == topic


def test_repository_connected_topics_have_canonical_layout() -> None:
    expected = {
        ("microsoft-foundry", "agent-memory"): {
            "slugs": [
                "index",
                "taxonomy",
                "architecture-patterns",
                "pipeline-retrieval",
                "frameworks",
                "production-evaluation",
                "commerce",
            ],
            "redirects": [
                "research/microsoft-foundry/agent-memory-overview/index.md",
                "research/microsoft-foundry/agent-memory-taxonomy/index.md",
                "research/microsoft-foundry/agent-memory-architecture-patterns/index.md",
                "research/microsoft-foundry/agent-memory-pipeline-retrieval/index.md",
                "research/microsoft-foundry/agent-memory-frameworks/index.md",
                "research/microsoft-foundry/agent-memory-production-evaluation/index.md",
                "research/microsoft-foundry/agent-memory-commerce/index.md",
            ],
        },
        ("azure-monitor", "azure-sre-agent"): {
            "slugs": [
                "index",
                "event-lab",
                "setup",
                "scenario-http-500",
                "scenario-latency",
                "scenario-blob-permission",
                "results",
                "validation-results",
                "incident-runbook",
                "dynamic-thresholds",
            ],
            "redirects": [
                "guides/azure-monitor/azure-sre-agent-overview/index.md",
                "labs/azure-monitor/sre-agent-event-lab/index.md",
                "labs/azure-monitor/sre-agent-event-lab-setup/index.md",
                "labs/azure-monitor/sre-agent-scenario-http-500/index.md",
                "labs/azure-monitor/sre-agent-scenario-latency/index.md",
                "labs/azure-monitor/sre-agent-scenario-blob-permission/index.md",
                "labs/azure-monitor/sre-agent-results/index.md",
                "research/azure-monitor/sre-agent-validation-results/index.md",
                "guides/azure-monitor/sre-agent-incident-runbook/index.md",
                "guides/azure-monitor/sre-agent-dynamic-thresholds/index.md",
            ],
        },
        ("azure-ai-search", "custom-vectorization"): {
            "slugs": [
                "index",
                "rag-chunking",
                "custom-web-api",
                "gpu-vllm",
                "bge-m3-vs-qwen3",
                "a10-vs-t4",
            ],
            "redirects": [
                "guides/azure-ai-search/custom-embedding-ingestion/index.md",
                "research/azure-ai-search/rag-chunking-strategies/index.md",
                "guides/azure-ai-search/custom-web-api-vectorization/index.md",
                "guides/azure-ai-search/gpu-vllm-rag/index.md",
                "research/azure-ai-search/bge-m3-vs-qwen3-embedding/index.md",
                "research/azure-ai-search/a10-vs-t4-embedding-benchmark/index.md",
            ],
        },
        ("azure-monitor", "hdinsight-kafka-monitoring"): {
            "slugs": ["index", "prometheus-grafana", "catch-up-benchmark"],
            "redirects": [
                "research/azure-monitor/hdinsight-kafka-monitoring-options/index.md",
                "guides/azure-monitor/hdinsight-kafka-prometheus-grafana/index.md",
                "research/azure-hdinsight/kafka-catchup-sku-fetch-benchmark/index.md",
            ],
        },
    }
    catalog = build_topic_catalog(
        ROOT / "docs", load_taxonomy(ROOT / "docs-taxonomy.yml")
    )

    for topic_key, topic_expected in expected.items():
        topic = catalog.topics[topic_key]
        slugs = [
            "index" if member == topic.entry else member.relative_path.parts[-2]
            for member in topic.members
        ]

        assert slugs == topic_expected["slugs"]
        assert "topic_order" not in topic.entry.metadata
        assert [
            member.metadata.get("redirect_from") for member in topic.members
        ] == [[redirect] for redirect in topic_expected["redirects"]]


def test_repository_uses_only_canonical_topic_packages() -> None:
    moved_documents = {
        ("application-development", "nodejs-file-io-cpu"):
            "guides/application-development/nodejs-file-io-cpu/index.md",
        ("azure-ai-search", "eventual-consistency-reindex"):
            "cases/azure-ai-search/eventual-consistency-reindex/index.md",
        ("azure-ai-search", "korean-analyzer-comparison"):
            "guides/azure-ai-search/korean-analyzer-comparison/index.md",
        ("azure-application-gateway", "sse-response-buffering"):
            "guides/azure-application-gateway/sse-response-buffering/index.md",
        ("azure-application-gateway", "waf-path-ip-allowlist"):
            "guides/azure-application-gateway/waf-path-ip-allowlist/index.md",
        ("azure-architecture", "response-time-optimization"):
            "guides/azure-architecture/response-time-optimization/index.md",
        ("azure-automation", "portal-cli-limitations"):
            "guides/azure-automation/portal-cli-limitations/index.md",
        ("azure-cosmos-db", "nodejs-client-optimization"):
            "guides/azure-cosmos-db/nodejs-client-optimization/index.md",
        ("azure-cosmos-db", "nodejs-dns-lookup-bottleneck"):
            "guides/azure-cosmos-db/nodejs-dns-lookup-bottleneck/index.md",
        ("azure-cosmos-db", "point-read-optimization"):
            "guides/azure-cosmos-db/point-read-optimization/index.md",
        ("azure-database-for-mysql", "blue-green-upgrade"):
            "guides/azure-database-for-mysql/blue-green-upgrade/index.md",
        ("azure-database-for-mysql", "nodejs-read-write-routing"):
            "guides/azure-database-for-mysql/nodejs-read-write-routing/index.md",
        ("azure-kubernetes-service", "file-io-throttling"):
            "cases/azure-kubernetes-service/file-io-throttling/index.md",
        ("azure-kubernetes-service", "netapp-files-cpu-io-wait"):
            "cases/azure-kubernetes-service/netapp-files-cpu-io-wait/index.md",
        ("azure-kubernetes-service", "pod-database-query-latency"):
            "cases/azure-kubernetes-service/pod-database-query-latency/index.md",
        ("azure-kubernetes-service", "argocd-image-updater-acr"):
            "guides/azure-kubernetes-service/argocd-image-updater-acr/index.md",
        ("azure-kubernetes-service", "authorization-troubleshooting"):
            "guides/azure-kubernetes-service/authorization-troubleshooting/index.md",
        ("azure-kubernetes-service", "cni-overlay-nsg"):
            "guides/azure-kubernetes-service/cni-overlay-nsg/index.md",
        ("azure-kubernetes-service", "kaito-open-source-model"):
            "guides/azure-kubernetes-service/kaito-open-source-model/index.md",
        ("azure-kubernetes-service", "pod-affinity-distribution"):
            "guides/azure-kubernetes-service/pod-affinity-distribution/index.md",
        ("azure-kubernetes-service", "pod-scheduling-agent-pools"):
            "guides/azure-kubernetes-service/pod-scheduling-agent-pools/index.md",
        ("azure-kubernetes-service", "pyroscope-anf-s3"):
            "guides/azure-kubernetes-service/pyroscope-anf-s3/index.md",
        ("azure-kubernetes-service", "python-memory-leak-memray"):
            "guides/azure-kubernetes-service/python-memory-leak-memray/index.md",
        ("azure-kubernetes-service", "remote-cluster-local-development"):
            "guides/azure-kubernetes-service/remote-cluster-local-development/index.md",
        ("azure-kubernetes-service", "spot-h100-kaito"):
            "guides/azure-kubernetes-service/spot-h100-kaito/index.md",
        ("azure-kubernetes-service", "workload-identity-databricks"):
            "guides/azure-kubernetes-service/workload-identity-databricks/index.md",
        ("azure-load-testing", "locust-appgw-aks-private"):
            "guides/azure-load-testing/locust-appgw-aks-private/index.md",
        ("azure-managed-redis", "cluster-failover-recovery"):
            "cases/azure-managed-redis/cluster-failover-recovery/index.md",
        ("azure-monitor", "aks-private-opentelemetry"):
            "guides/azure-monitor/aks-private-opentelemetry/index.md",
        ("azure-monitor", "dynamic-thresholds-brief"):
            "research/azure-monitor/dynamic-thresholds-brief/index.md",
        ("azure-openai", "adaptive-ptu-load-balancing"):
            "guides/azure-openai/adaptive-ptu-load-balancing/index.md",
        ("azure-storage", "mobile-resumable-upload-tus"):
            "guides/azure-storage/mobile-resumable-upload-tus/index.md",
        ("microsoft-foundry", "agent-framework-2026"):
            "research/microsoft-foundry/agent-framework-2026/index.md",
        ("microsoft-foundry", "codex-closed-network"):
            "guides/microsoft-foundry/codex-closed-network/index.md",
        ("microsoft-foundry", "foundry-local-air-gapped"):
            "guides/microsoft-foundry/foundry-local-air-gapped/index.md",
        ("microsoft-foundry", "gpt-memory-layer"):
            "guides/microsoft-foundry/gpt-memory-layer/index.md",
    }
    catalog = build_topic_catalog(
        ROOT / "docs", load_taxonomy(ROOT / "docs-taxonomy.yml")
    )

    assert len(catalog.documents) == 62
    assert len(catalog.topics) == 40
    assert not any(
        (ROOT / "docs" / name).exists()
        for name in ("cases", "guides", "labs", "research")
    )
    assert not (ROOT / "samples").exists()
    assert all(
        document.relative_path.parts[0] == "services"
        for document in catalog.documents
    )
    assert {
        redirect
        for topic_key, redirect in moved_documents.items()
        if catalog.topics[topic_key].entry.metadata.get("redirect_from") == [redirect]
    } == set(moved_documents.values())


def test_mobile_upload_commands_use_the_canonical_sample_path() -> None:
    guide = (
        ROOT
        / "docs"
        / "services"
        / "azure-storage"
        / "mobile-resumable-upload-tus"
        / "index.md"
    ).read_text(encoding="utf-8")
    sample_path = (
        "docs/services/azure-storage/mobile-resumable-upload-tus/"
        "samples/spring-application"
    )

    assert f"cd {sample_path}\n" in guide
    assert f"cd {sample_path}/scripts\n" in guide
    assert "cd azureblob/spring-resumable-upload" not in guide
    assert "cd spring-resumable-upload/scripts" not in guide
