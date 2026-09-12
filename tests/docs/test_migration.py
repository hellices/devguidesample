from __future__ import annotations

from pathlib import Path

import yaml

from scripts.docs.content import load_document
from scripts.docs.migrate_content import migrate_repository


ROOT = Path(__file__).parents[2]
CANONICAL_SERVICE_MAPPINGS = {
    "aks": "azure-kubernetes-service",
    "application-gateway": "azure-application-gateway",
    "azure-ai-foundry": "microsoft-foundry",
    "azure-mysql": "azure-database-for-mysql",
    "cosmos-db": "azure-cosmos-db",
    "development": "application-development",
    "hdinsight": "azure-hdinsight",
}


def metadata(document_type: str, service: str, **extra) -> dict:
    base = {
        "title": f"{document_type} title",
        "description": f"{document_type} description",
        "document_type": document_type,
        "services": [service],
        "technologies": ["kubernetes"],
        "tags": ["troubleshooting"],
        "status": {
            "guide": "needs-review",
            "case": "resolved",
            "lab": "needs-review",
            "research": "current",
        }[document_type],
        "verification_status": "needs-review",
        "sources_checked_at": "2026-09-12",
        "official_sources": [
            {
                "title": "Azure Kubernetes Service documentation",
                "url": "https://learn.microsoft.com/azure/aks/",
            }
        ],
    }
    base.update(extra)
    return base


def make_fixture(tmp_path: Path) -> Path:
    legacy = tmp_path / "legacy"
    (legacy / "images").mkdir(parents=True)
    (legacy / "sample" / "evidence").mkdir(parents=True)
    (legacy / "images" / "diagram.png").write_bytes(b"png")
    (legacy / "sample" / "app.py").write_text("print('sample')\n", encoding="utf-8")
    (legacy / "sample" / "evidence" / "timeline.md").write_text(
        "# Raw timeline\n", encoding="utf-8"
    )
    (legacy / "guide.md").write_text(
        "# Guide\n\n![Architecture](images/diagram.png)\n\n"
        "[Related case](case.md)\n\n[Sample](sample/app.py)\n",
        encoding="utf-8",
    )
    (legacy / "case.md").write_text("# Case\n", encoding="utf-8")
    (legacy / "lab.md").write_text("# Lab\n", encoding="utf-8")
    (legacy / "research.md").write_text("# Research\n", encoding="utf-8")

    documents = [
        {
            "source": "legacy/guide.md",
            "destination": "guides/aks/guide/index.md",
            "metadata": metadata(
                "guide",
                "aks",
                last_verified=None,
                review_cycle_days=180,
                applies_to=["AKS"],
            ),
        },
        {
            "source": "legacy/case.md",
            "destination": "cases/aks/case/index.md",
            "metadata": metadata("case", "aks", occurred_at="2026-09-01"),
        },
        {
            "source": "legacy/lab.md",
            "destination": "labs/aks/lab/index.md",
            "metadata": metadata(
                "lab",
                "aks",
                last_verified=None,
                review_cycle_days=90,
                estimated_time="30m",
                cost="paid",
                cleanup_required=True,
            ),
        },
        {
            "source": "legacy/research.md",
            "destination": "research/aks/research/index.md",
            "metadata": metadata("research", "aks", published_at="2026-09-01"),
        },
    ]
    manifest = {
        "repository_url": "https://github.com/hellices/devguidesample",
        "branch": "main",
        "documents": documents,
        "sample_roots": [{"source": "legacy", "destination": "samples/aks/legacy"}],
    }
    manifest_path = tmp_path / "manifest.yml"
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return manifest_path


def test_migration_creates_page_bundles_and_rewrites_links(tmp_path: Path) -> None:
    manifest = make_fixture(tmp_path)

    result = migrate_repository(tmp_path, manifest, apply=True)

    assert result.changed_count > 0
    guide_path = tmp_path / "docs" / "guides" / "aks" / "guide" / "index.md"
    guide = load_document(guide_path, docs_dir=tmp_path / "docs")
    assert guide.metadata["document_type"] == "guide"
    assert guide.metadata["last_verified"] is None
    assert "![Architecture](images/diagram.png)" in guide.body
    assert (guide_path.parent / "images" / "diagram.png").read_bytes() == b"png"
    assert "[Related case](../../../cases/aks/case/index.md)" in guide.body
    assert (
        "[Sample](https://github.com/hellices/devguidesample/blob/main/"
        "samples/aks/legacy/sample/app.py)" in guide.body
    )


def test_migration_moves_unpublished_evidence_under_samples(tmp_path: Path) -> None:
    manifest = make_fixture(tmp_path)

    migrate_repository(tmp_path, manifest, apply=True)

    assert not (tmp_path / "legacy").exists()
    assert (tmp_path / "samples" / "aks" / "legacy" / "sample" / "app.py").exists()
    assert (
        tmp_path / "samples" / "aks" / "legacy" / "sample" / "evidence" / "timeline.md"
    ).exists()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    manifest = make_fixture(tmp_path)
    migrate_repository(tmp_path, manifest, apply=True)

    second = migrate_repository(tmp_path, manifest, apply=True)

    assert second.changed_count == 0


def test_dry_run_does_not_change_files(tmp_path: Path) -> None:
    manifest = make_fixture(tmp_path)

    result = migrate_repository(tmp_path, manifest, apply=False)

    assert result.changed_count > 0
    assert (tmp_path / "legacy" / "guide.md").exists()
    assert not (tmp_path / "docs").exists()


def test_repository_manifest_uses_canonical_service_destinations() -> None:
    manifest = yaml.safe_load(
        (ROOT / "scripts" / "docs" / "migration_manifest.yml").read_text(
            encoding="utf-8"
        )
    )
    document_destinations = [entry["destination"] for entry in manifest["documents"]]
    sample_destinations = [entry["destination"] for entry in manifest["sample_roots"]]

    for legacy, canonical in CANONICAL_SERVICE_MAPPINGS.items():
        assert not any(
            destination.split("/")[1] == legacy
            for destination in document_destinations
        )
        assert any(
            destination.split("/")[1] == canonical
            for destination in document_destinations
        )

    assert "samples/azure-app-service/oryx-test" in sample_destinations
    assert "samples/app-service/oryx-test" not in sample_destinations
