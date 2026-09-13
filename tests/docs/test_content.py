from __future__ import annotations

from datetime import date
from pathlib import Path, PurePosixPath

import pytest

from scripts.docs.content import (
    Document,
    DocumentFormatError,
    build_series_catalog,
    iter_public_documents,
    load_document,
    load_taxonomy,
    series_validation_errors,
    validate_document,
)


FIXTURES = Path(__file__).parent / "fixtures"
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
        "services": {"aks": "Azure Kubernetes Service"},
        "technologies": {"kubernetes": "Kubernetes"},
        "tags": {
            "networking": "Networking",
            "troubleshooting": "Troubleshooting",
        },
        "verification_statuses": ["verified", "needs-review"],
        "official_source_hosts": ["learn.microsoft.com", "kubernetes.io"],
        "required_source_host": "learn.microsoft.com",
    }


def copy_fixture(tmp_path: Path, name: str, relative: str) -> Path:
    target = tmp_path / "docs" / relative
    target.parent.mkdir(parents=True)
    target.write_text((FIXTURES / name).read_text(encoding="utf-8"), encoding="utf-8")
    return target


def series_document(path: str, order: int, role: str) -> Document:
    return Document(
        path=Path(path),
        relative_path=PurePosixPath(path),
        metadata={
            "title": path,
            "description": f"{path} description",
            "series": "agent-memory",
            "series_order": order,
            "series_role": role,
        },
        body="",
    )


def test_valid_page_bundle_satisfies_the_content_contract(
    tmp_path: Path, taxonomy: dict
) -> None:
    path = copy_fixture(
        tmp_path,
        "valid-guide.md",
        "guides/aks/network-diagnosis/index.md",
    )

    document = load_document(path, docs_dir=tmp_path / "docs")

    assert document.relative_path.as_posix() == (
        "guides/aks/network-diagnosis/index.md"
    )
    assert document.metadata["sources_checked_at"] == date(2026, 9, 12)
    assert validate_document(document, taxonomy, today=date(2026, 9, 12)) == []


def test_page_bundle_requires_yaml_front_matter(tmp_path: Path) -> None:
    path = copy_fixture(
        tmp_path,
        "invalid-guide.md",
        "guides/aks/no-front-matter/index.md",
    )

    with pytest.raises(DocumentFormatError, match="YAML front matter"):
        load_document(path, docs_dir=tmp_path / "docs")


def test_content_contract_rejects_invalid_path_taxonomy_and_source(
    tmp_path: Path, taxonomy: dict
) -> None:
    path = copy_fixture(
        tmp_path,
        "valid-guide.md",
        "guides/aks/Network_Diagnosis.md",
    )
    loaded = load_document(path, docs_dir=tmp_path / "docs")
    metadata = {
        **loaded.metadata,
        "services": ["unknown"],
        "status": "draft",
        "sources_checked_at": date(2026, 9, 13),
        "official_sources": [
            {"title": "Kubernetes", "url": "http://kubernetes.io/docs/"}
        ],
    }

    errors = validate_document(
        loaded.with_metadata(metadata),
        taxonomy,
        today=date(2026, 9, 12),
    )

    expected = (
        "public documents must use <collection>/<service>/<topic>/index.md",
        "unknown service: unknown",
        "invalid guide status: draft",
        "sources_checked_at cannot be in the future",
        "official source URL must use HTTPS",
        "at least one official source must use learn.microsoft.com",
    )
    for message in expected:
        assert any(message in error for error in errors), errors


def test_unverified_guide_can_leave_last_verified_empty(
    tmp_path: Path, taxonomy: dict
) -> None:
    path = copy_fixture(
        tmp_path,
        "valid-guide.md",
        "guides/aks/network-diagnosis/index.md",
    )
    loaded = load_document(path, docs_dir=tmp_path / "docs")
    metadata = {
        **loaded.metadata,
        "status": "needs-review",
        "verification_status": "needs-review",
        "last_verified": None,
    }

    errors = validate_document(
        loaded.with_metadata(metadata),
        taxonomy,
        today=date(2026, 9, 12),
    )

    assert errors == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("document_type", ["guide"]),
        ("document_type", {"name": "guide"}),
        ("review_cycle_days", True),
        ("review_cycle_days", None),
        ("applies_to", None),
        ("applies_to", []),
        ("featured", "true"),
        ("featured", 1),
        ("series", ["agent-memory"]),
        ("series_order", True),
        ("series_order", -1),
        ("series_role", "appendix"),
    ],
)
def test_invalid_metadata_values_return_validation_errors(
    tmp_path: Path, taxonomy: dict, field: str, value: object
) -> None:
    path = copy_fixture(
        tmp_path, "valid-guide.md", "guides/aks/network-diagnosis/index.md"
    )
    loaded = load_document(path, docs_dir=tmp_path / "docs")

    errors = validate_document(
        loaded.with_metadata({**loaded.metadata, field: value}),
        taxonomy,
        today=date(2026, 9, 12),
    )

    assert any(field in error for error in errors), errors


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({"series": "unknown-series", "series_order": 0, "series_role": "overview"}, "unknown series: unknown-series"),
        ({"series_order": 0}, "series_order requires series"),
        ({"series_role": "overview"}, "series_role requires series"),
    ],
)
def test_series_metadata_requires_known_series_context(
    tmp_path: Path, taxonomy: dict, metadata: dict[str, object], message: str
) -> None:
    path = copy_fixture(
        tmp_path, "valid-guide.md", "guides/aks/network-diagnosis/index.md"
    )
    loaded = load_document(path, docs_dir=tmp_path / "docs")

    errors = validate_document(
        loaded.with_metadata({**loaded.metadata, **metadata}),
        taxonomy,
        today=date(2026, 9, 12),
    )

    assert any(message in error for error in errors), errors


def test_build_series_catalog_orders_members_and_indexes_paths(
    taxonomy: dict,
) -> None:
    taxonomy["series"] = {
        "agent-memory": {
            "title": "Agent Memory",
            "description": "Ordered memory research",
        }
    }
    chapter = series_document(
        "research/microsoft-foundry/chapter/index.md", 1, "chapter"
    )
    overview = series_document(
        "research/microsoft-foundry/overview/index.md", 0, "overview"
    )

    catalog = build_series_catalog([chapter, overview], taxonomy)

    series = catalog.by_slug["agent-memory"]
    assert [member.relative_path for member in series.members] == [
        overview.relative_path,
        chapter.relative_path,
    ]
    assert series.overview == overview
    assert catalog.by_document[chapter.relative_path] == series
    assert catalog.positions[chapter.relative_path] == 1


@pytest.mark.parametrize(
    ("documents", "message"),
    [
        (
            [series_document("research/x/overview/index.md", 0, "chapter")],
            "exactly one overview",
        ),
        (
            [
                series_document("research/x/overview/index.md", 0, "overview"),
                series_document("research/x/chapter/index.md", 0, "chapter"),
            ],
            "duplicate series_order 0",
        ),
        (
            [
                series_document("research/x/overview/index.md", 0, "overview"),
                series_document("research/x/chapter/index.md", 2, "chapter"),
            ],
            "contiguous from 0",
        ),
    ],
)
def test_series_validation_rejects_invalid_groups(
    taxonomy: dict, documents: list[Document], message: str
) -> None:
    taxonomy["series"] = {
        "agent-memory": {"title": "Agent Memory", "description": "Description"}
    }
    errors = series_validation_errors(documents, taxonomy)
    assert any(message in error for error in errors), errors
    with pytest.raises(DocumentFormatError, match=message):
        build_series_catalog(documents, taxonomy)


@pytest.mark.parametrize("featured", [True, False])
def test_featured_is_optional_boolean(
    tmp_path: Path, taxonomy: dict, featured: bool
) -> None:
    path = copy_fixture(
        tmp_path, "valid-guide.md", "guides/aks/network-diagnosis/index.md"
    )
    loaded = load_document(path, docs_dir=tmp_path / "docs")

    assert validate_document(
        loaded.with_metadata({**loaded.metadata, "featured": featured}),
        taxonomy,
        today=date(2026, 9, 12),
    ) == []


def test_malformed_source_url_returns_a_validation_error(
    tmp_path: Path, taxonomy: dict
) -> None:
    path = copy_fixture(
        tmp_path, "valid-guide.md", "guides/aks/network-diagnosis/index.md"
    )
    loaded = load_document(path, docs_dir=tmp_path / "docs")

    errors = validate_document(
        loaded.with_metadata(
            {
                **loaded.metadata,
                "official_sources": [{"title": "Source", "url": "https://[invalid"}],
            }
        ),
        taxonomy,
        today=date(2026, 9, 12),
    )

    assert any("official_sources[0].url" in error for error in errors), errors


def test_repository_uses_provider_consistent_service_slugs() -> None:
    taxonomy = load_taxonomy(ROOT / "docs-taxonomy.yml")

    for slug, label in taxonomy["services"].items():
        if label.startswith("Azure "):
            assert slug.startswith("azure-"), f"{label} must use an azure-* slug"
        if label.startswith("Microsoft "):
            assert slug.startswith(
                "microsoft-"
            ), f"{label} must use a microsoft-* slug"

    for document in iter_public_documents(ROOT / "docs", taxonomy):
        service = document.relative_path.parts[1]
        assert service in taxonomy["services"]
        assert service in document.metadata["services"]
