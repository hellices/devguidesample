from __future__ import annotations

from pathlib import Path, PurePosixPath
import re

import pytest
import yaml

from scripts.docs.content import DocumentFormatError, validate_document
from scripts.docs.topics import build_topic_catalog


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
