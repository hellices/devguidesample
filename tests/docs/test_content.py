from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from scripts.docs.content import (
    DocumentFormatError,
    iter_public_documents,
    load_document,
    load_taxonomy,
    validate_document,
)


FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parents[2]


@pytest.fixture
def taxonomy() -> dict:
    return {
        "collections": {
            "case": {
                "path": "cases",
                "statuses": ["unresolved", "resolved", "historical"],
                "required_fields": ["occurred_at"],
            },
            "guide": {
                "path": "guides",
                "statuses": ["current", "needs-review", "deprecated"],
                "required_fields": [
                    "last_verified",
                    "review_cycle_days",
                    "applies_to",
                ],
            },
            "lab": {
                "path": "labs",
                "statuses": ["verified", "needs-review", "broken", "archived"],
                "required_fields": [
                    "last_verified",
                    "review_cycle_days",
                    "estimated_time",
                    "cost",
                    "cleanup_required",
                ],
            },
            "research": {
                "path": "research",
                "statuses": ["current", "superseded", "archived"],
                "required_fields": ["published_at"],
            },
        },
        "services": {"aks": "Azure Kubernetes Service"},
        "technologies": {"kubernetes": "Kubernetes"},
        "tags": {
            "networking": "Networking",
            "troubleshooting": "Troubleshooting",
        },
        "verification_statuses": ["verified", "needs-review"],
        "official_source_hosts": [
            "learn.microsoft.com",
            "kubernetes.io",
            "www.cncf.io",
        ],
        "required_source_host": "learn.microsoft.com",
    }


def copy_fixture(tmp_path: Path, name: str, relative: str) -> Path:
    target = tmp_path / "docs" / relative
    target.parent.mkdir(parents=True)
    target.write_text((FIXTURES / name).read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_load_document_parses_front_matter_and_body(tmp_path: Path) -> None:
    path = copy_fixture(tmp_path, "valid-guide.md", "guides/aks/network-diagnosis/index.md")

    document = load_document(path, docs_dir=tmp_path / "docs")

    assert document.relative_path.as_posix() == "guides/aks/network-diagnosis/index.md"
    assert document.metadata["document_type"] == "guide"
    assert document.metadata["sources_checked_at"] == date(2026, 9, 12)
    assert document.body.startswith("# AKS 네트워크 진단")


def test_load_document_rejects_missing_front_matter(tmp_path: Path) -> None:
    path = copy_fixture(tmp_path, "invalid-guide.md", "guides/aks/no-front-matter/index.md")

    with pytest.raises(DocumentFormatError, match="YAML front matter"):
        load_document(path, docs_dir=tmp_path / "docs")


def test_valid_guide_has_no_validation_errors(tmp_path: Path, taxonomy: dict) -> None:
    path = copy_fixture(tmp_path, "valid-guide.md", "guides/aks/network-diagnosis/index.md")
    document = load_document(path, docs_dir=tmp_path / "docs")

    errors = validate_document(document, taxonomy, today=date(2026, 9, 12))

    assert errors == []


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda meta: meta.pop("description"), "missing required field: description"),
        (lambda meta: meta.update(document_type="case"), "folder 'guides' does not match"),
        (lambda meta: meta.update(services=["unknown"]), "unknown service: unknown"),
        (lambda meta: meta.update(technologies=["unknown"]), "unknown technology: unknown"),
        (lambda meta: meta.update(tags=["not_registered"]), "tag must be kebab-case"),
        (lambda meta: meta.update(status="draft"), "invalid guide status: draft"),
        (
            lambda meta: meta.update(verification_status="guessed"),
            "invalid verification_status: guessed",
        ),
        (
            lambda meta: meta.update(sources_checked_at=date(2026, 9, 13)),
            "sources_checked_at cannot be in the future",
        ),
        (
            lambda meta: meta.update(sources_checked_at=None),
            "sources_checked_at must be a date",
        ),
        (
            lambda meta: meta.update(
                official_sources=[
                    {"title": "Kubernetes", "url": "https://kubernetes.io/docs/"}
                ]
            ),
            "at least one official source must use learn.microsoft.com",
        ),
        (
            lambda meta: meta.update(
                official_sources=[
                    {
                        "title": "Azure Kubernetes Service documentation",
                        "url": "http://learn.microsoft.com/azure/aks/",
                    }
                ]
            ),
            "official source URL must use HTTPS",
        ),
    ],
)
def test_invalid_metadata_reports_actionable_errors(
    tmp_path: Path,
    taxonomy: dict,
    mutation,
    expected: str,
) -> None:
    path = copy_fixture(tmp_path, "valid-guide.md", "guides/aks/network-diagnosis/index.md")
    loaded = load_document(path, docs_dir=tmp_path / "docs")
    metadata = deepcopy(loaded.metadata)
    mutation(metadata)
    document = loaded.with_metadata(metadata)

    errors = validate_document(document, taxonomy, today=date(2026, 9, 12))

    assert any(expected in error for error in errors), errors


def test_path_must_be_a_kebab_case_page_bundle(tmp_path: Path, taxonomy: dict) -> None:
    path = copy_fixture(tmp_path, "valid-guide.md", "guides/aks/Network_Diagnosis.md")
    document = load_document(path, docs_dir=tmp_path / "docs")

    errors = validate_document(document, taxonomy, today=date(2026, 9, 12))

    assert "public documents must use <collection>/<service>/<topic>/index.md" in errors


def test_needs_review_allows_null_last_verified(tmp_path: Path, taxonomy: dict) -> None:
    path = copy_fixture(tmp_path, "valid-guide.md", "guides/aks/network-diagnosis/index.md")
    loaded = load_document(path, docs_dir=tmp_path / "docs")
    metadata = deepcopy(loaded.metadata)
    metadata.update(
        status="needs-review",
        verification_status="needs-review",
        last_verified=None,
    )

    errors = validate_document(
        loaded.with_metadata(metadata), taxonomy, today=date(2026, 9, 12)
    )

    assert errors == []


@pytest.mark.parametrize(
    ("document_type", "collection", "status", "date_field"),
    [
        ("case", "cases", "resolved", "occurred_at"),
        ("research", "research", "current", "published_at"),
    ],
)
def test_required_collection_dates_reject_null(
    tmp_path: Path,
    taxonomy: dict,
    document_type: str,
    collection: str,
    status: str,
    date_field: str,
) -> None:
    path = copy_fixture(
        tmp_path,
        "valid-guide.md",
        f"{collection}/aks/null-date/index.md",
    )
    loaded = load_document(path, docs_dir=tmp_path / "docs")
    metadata = deepcopy(loaded.metadata)
    metadata.update(document_type=document_type, status=status)
    metadata[date_field] = None

    errors = validate_document(
        loaded.with_metadata(metadata), taxonomy, today=date(2026, 9, 12)
    )

    assert f"{date_field} must be a date" in errors


def test_verified_guide_requires_last_verified_date(tmp_path: Path, taxonomy: dict) -> None:
    path = copy_fixture(tmp_path, "valid-guide.md", "guides/aks/network-diagnosis/index.md")
    loaded = load_document(path, docs_dir=tmp_path / "docs")
    metadata = deepcopy(loaded.metadata)
    metadata["last_verified"] = None

    errors = validate_document(
        loaded.with_metadata(metadata), taxonomy, today=date(2026, 9, 12)
    )

    assert "last_verified must be a date when verification_status is verified" in errors


def test_iter_public_documents_ignores_indexes_and_non_collection_files(
    tmp_path: Path,
) -> None:
    copy_fixture(tmp_path, "valid-guide.md", "guides/aks/network-diagnosis/index.md")
    (tmp_path / "docs" / "index.md").write_text("# Home\n", encoding="utf-8")
    (tmp_path / "docs" / "guides" / "index.md").write_text(
        "# Guides\n", encoding="utf-8"
    )

    documents = list(
        iter_public_documents(
            tmp_path / "docs", {"collections": {"guide": {"path": "guides"}}}
        )
    )

    assert [doc.relative_path.as_posix() for doc in documents] == [
        "guides/aks/network-diagnosis/index.md"
    ]


def test_repository_service_slugs_match_provider_policy() -> None:
    taxonomy = load_taxonomy(ROOT / "docs-taxonomy.yml")

    for slug, label in taxonomy["services"].items():
        if label.startswith("Azure "):
            assert slug.startswith("azure-"), f"{label} must use an azure-* slug"
        if label.startswith("Microsoft "):
            assert slug.startswith("microsoft-"), f"{label} must use a microsoft-* slug"


def test_repository_documents_use_declared_service_folders() -> None:
    taxonomy = load_taxonomy(ROOT / "docs-taxonomy.yml")

    for document in iter_public_documents(ROOT / "docs", taxonomy):
        service = document.relative_path.parts[1]
        assert service in taxonomy["services"]
        assert service in document.metadata["services"]


def test_needs_review_pages_do_not_claim_official_verification_is_complete() -> None:
    taxonomy = load_taxonomy(ROOT / "docs-taxonomy.yml")
    forbidden = (
        "공식 Microsoft Learn 문서 기반 검증 완료",
        "공식 문서 검증 완료",
    )

    for document in iter_public_documents(ROOT / "docs", taxonomy):
        if document.metadata.get("verification_status") != "needs-review":
            continue
        for phrase in forbidden:
            assert phrase not in document.body, (
                f"{document.relative_path}: needs-review page contains {phrase!r}"
            )
