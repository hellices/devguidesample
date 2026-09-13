"""Tests for the metadata-driven landing/index generator.

These tests inspect meaningful rendered links, metadata, and coverage rather
than exact prose or full-page snapshots, per the public documentation
contract for generated collection/service/home pages.
"""

from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path, PurePosixPath

from markdown import Markdown
from mkdocs.config import load_config
import pytest
import yaml

from scripts.docs.content import Document, load_taxonomy
from scripts.docs.generate_indexes import (
    build_home_page,
    build_index_pages,
    build_redirect_pages,
)
from scripts.docs.topics import build_topic_catalog


ROOT = Path(__file__).parents[2]


def doc(relative_path: str, **metadata: object) -> Document:
    return Document(
        path=Path(relative_path),
        relative_path=PurePosixPath(relative_path),
        metadata=metadata,
        body="",
    )


def write_topic_document(
    docs_dir: Path,
    relative_path: str,
    title: str,
    *,
    tags: list[str],
    topic_order: int | None = None,
    featured: bool = False,
    redirect_from: list[str] | None = None,
    document_type: str = "guide",
) -> None:
    metadata: dict[str, object] = {
        "title": title,
        "description": f"{title} description",
        "document_type": document_type,
        "services": ["azure-monitor"],
        "technologies": ["kubernetes"],
        "tags": tags,
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
    if featured:
        metadata["featured"] = True
    if redirect_from is not None:
        metadata["redirect_from"] = redirect_from

    path = docs_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n\n"
        + f"# {title}\n",
        encoding="utf-8",
    )


def build_topic_fixture(
    tmp_path: Path,
    taxonomy: dict,
    *,
    include_redirect: bool = False,
) -> tuple[list[Document], object]:
    docs_dir = tmp_path / "docs"
    write_topic_document(
        docs_dir,
        "services/azure-monitor/new-topic/index.md",
        "Topic title",
        tags=["networking"],
        redirect_from=["guides/azure-monitor/old-topic/index.md"] if include_redirect else None,
    )
    write_topic_document(
        docs_dir,
        "services/azure-monitor/new-topic/setup/index.md",
        "Setup child",
        tags=["networking"],
        topic_order=1,
        featured=True,
    )
    write_topic_document(
        docs_dir,
        "services/azure-monitor/new-topic/results/index.md",
        "Results child",
        tags=["monitoring"],
        topic_order=2,
    )
    write_topic_document(
        docs_dir,
        "services/azure-monitor/standalone-topic/index.md",
        "Standalone topic",
        tags=["networking"],
        featured=True,
    )

    catalog = build_topic_catalog(docs_dir, taxonomy)
    return list(catalog.documents), catalog


@pytest.fixture
def taxonomy() -> dict:
    return {
        "collections": {
            "case": {
                "path": "cases",
                "title": "트러블슈팅",
                "description": "사례 모음입니다.",
            },
            "guide": {
                "path": "guides",
                "title": "구현 가이드",
                "description": "가이드 모음입니다.",
            },
            "lab": {
                "path": "labs",
                "title": "실습",
                "description": "실습 모음입니다.",
            },
            "research": {
                "path": "research",
                "title": "비교·분석",
                "description": "리서치 모음입니다.",
            },
        },
        "services": {
            "azure-kubernetes-service": "Azure Kubernetes Service",
            "azure-monitor": "Azure Monitor",
        },
        "technologies": {"kubernetes": "Kubernetes", "python": "Python"},
        "tags": {
            "latency": "Latency",
            "networking": "Networking",
            "monitoring": "Monitoring",
        },
    }


@pytest.fixture
def markdown_renderer() -> Markdown:
    config = load_config(config_file=str(ROOT / "mkdocs.yml"))
    return Markdown(extensions=config.markdown_extensions, extension_configs=config.mdx_configs)


def render_body(markdown_renderer: Markdown, page: str) -> str:
    """Render a generated virtual page's Markdown body (after front matter) to HTML."""
    body = page.split("---", 2)[2]
    return markdown_renderer.reset().convert(body)


# ---------------------------------------------------------------------------
# build_index_pages: collection pages
# ---------------------------------------------------------------------------


def test_collection_page_groups_by_primary_service_without_duplicates(taxonomy: dict) -> None:
    multi_service_doc = doc(
        "guides/azure-monitor/diag/index.md",
        title="AKS 진단 가이드",
        description="진단 절차",
        document_type="guide",
        services=["azure-monitor", "azure-kubernetes-service"],
        status="current",
        last_verified=date(2026, 1, 1),
        applies_to=["AKS 1.34+"],
        verification_status="verified",
        tags=["networking"],
    )
    other_doc = doc(
        "guides/azure-kubernetes-service/other/index.md",
        title="다른 가이드",
        description="다른 절차",
        document_type="guide",
        services=["azure-kubernetes-service"],
        status="current",
        last_verified=date(2026, 1, 2),
        applies_to=["AKS 1.34+"],
        verification_status="verified",
        tags=[],
    )

    pages = build_index_pages([multi_service_doc, other_doc], taxonomy)
    guide_index = pages[PurePosixPath("guides/index.md")]

    # The multi-service document is grouped by its path's primary service
    # (azure-monitor) and therefore appears exactly once, even though its
    # metadata also lists azure-kubernetes-service.
    assert guide_index.count("AKS 진단 가이드") == 1
    assert "azure-monitor/diag/index.md" in guide_index
    assert "azure-kubernetes-service/other/index.md" in guide_index

    # Jump links target explicit, existing H2 anchors for each present group.
    assert "#service-azure-monitor" in guide_index
    assert "#service-azure-kubernetes-service" in guide_index
    assert '## Azure Monitor { #service-azure-monitor }' in guide_index
    assert '## Azure Kubernetes Service { #service-azure-kubernetes-service }' in guide_index


def test_collection_service_landing_contains_only_its_own_documents(taxonomy: dict) -> None:
    documents = [
        doc(
            "cases/azure-kubernetes-service/first/index.md",
            title="First case",
            description="Case details",
            document_type="case",
            services=["azure-kubernetes-service", "azure-monitor"],
        ),
        doc(
            "cases/azure-kubernetes-service/second/index.md",
            title="Second case",
            description="Case details",
            document_type="case",
            services=["azure-kubernetes-service"],
        ),
        doc(
            "guides/azure-kubernetes-service/guide/index.md",
            title="A guide",
            description="Guide details",
            document_type="guide",
            services=["azure-kubernetes-service"],
        ),
        doc(
            "cases/azure-monitor/other/index.md",
            title="Other service case",
            description="Case details",
            document_type="case",
            services=["azure-monitor"],
        ),
    ]

    pages = build_index_pages(documents, taxonomy)
    service_landing = pages[PurePosixPath("cases/azure-kubernetes-service/index.md")]

    assert yaml.safe_load(service_landing.split("---", 2)[1])["title"] == "Azure Kubernetes Service"
    assert service_landing.count('class="dg-doc-card ') == 2
    assert "[First case](first/index.md)" in service_landing
    assert "[Second case](second/index.md)" in service_landing
    assert "Other service case" not in service_landing
    assert "A guide" not in service_landing
    assert "First case" not in pages[PurePosixPath("cases/azure-monitor/index.md")]
    assert "First case" in pages[PurePosixPath("services/azure-monitor/index.md")]


def test_legacy_service_indexes_include_redirected_documents_deterministically(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir = tmp_path / "docs"
    write_topic_document(
        docs_dir,
        "services/azure-monitor/current-topic/index.md",
        "Current topic",
        tags=[],
    )
    write_topic_document(
        docs_dir,
        "services/azure-monitor/moved-topic/index.md",
        "Moved topic",
        tags=[],
        redirect_from=[
            "research/azure-hdinsight/old-topic/index.md",
            "research/azure-hdinsight/another-old-topic/index.md",
        ],
    )
    write_topic_document(
        docs_dir,
        "services/azure-monitor/moved-topic/benchmark/index.md",
        "Benchmark",
        tags=[],
        topic_order=1,
        document_type="research",
        redirect_from=[
            "guides/azure-monitor/old-benchmark/index.md",
            "research/azure-hdinsight/old-benchmark/index.md",
        ],
    )
    catalog = build_topic_catalog(docs_dir, taxonomy)

    pages = build_index_pages(catalog.documents, taxonomy, catalog=catalog)

    legacy = pages[PurePosixPath("research/azure-hdinsight/index.md")]
    assert legacy.count("[Moved topic](../../services/azure-monitor/moved-topic/index.md)") == 1
    assert legacy.count("[Benchmark](../../services/azure-monitor/moved-topic/benchmark/index.md)") == 1
    assert "SERVICES / 2 DOCUMENTS" in legacy
    assert "Current topic" not in legacy
    current = pages[PurePosixPath("guides/azure-monitor/index.md")]
    assert current.count("[Current topic](../../services/azure-monitor/current-topic/index.md)") == 1
    assert current.count("[Benchmark](../../services/azure-monitor/moved-topic/benchmark/index.md)") == 1
    assert "SERVICES / 3 DOCUMENTS" in current
    assert current.count('class="dg-doc-card dg-topic-card') == 1
    assert legacy.count('class="dg-doc-card dg-topic-card') == 1
    assert "old-benchmark" not in current
    assert pages == build_index_pages(reversed(catalog.documents), taxonomy, catalog=catalog)
    assert pages[PurePosixPath("guides/index.md")].count('class="dg-doc-card dg-topic-card') == 1
    assert pages[PurePosixPath("services/azure-monitor/index.md")].count('class="dg-doc-card dg-topic-card') == 1


def test_repository_legacy_hdinsight_index_links_to_canonical_benchmark() -> None:
    taxonomy = load_taxonomy(ROOT / "docs-taxonomy.yml")
    catalog = build_topic_catalog(ROOT / "docs", taxonomy)

    pages = build_index_pages(catalog.documents, taxonomy, catalog=catalog)

    assert PurePosixPath("research/azure-hdinsight/index.md") in pages
    legacy = pages[PurePosixPath("research/azure-hdinsight/index.md")]
    assert "../../services/azure-monitor/hdinsight-kafka-monitoring/catch-up-benchmark/index.md" in legacy
    assert "kafka-catchup-sku-fetch-benchmark/index.md" not in legacy
    for redirect, canonical in catalog.redirects.items():
        service_index = redirect.parent.parent / "index.md"
        assert service_index in pages
        assert f"../../{canonical.as_posix()}" in pages[service_index]


def test_collection_page_reflects_real_counts_and_wrapper_classes(taxonomy: dict) -> None:
    documents = [
        doc(
            f"cases/azure-kubernetes-service/case-{i}/index.md",
            title=f"사례 {i}",
            description="설명",
            document_type="case",
            services=["azure-kubernetes-service"],
            status="resolved",
            occurred_at=date(2026, 6, i + 1),
            verification_status="verified",
            tags=[],
        )
        for i in range(2)
    ]

    pages = build_index_pages(documents, taxonomy)
    case_index = pages[PurePosixPath("cases/index.md")]

    assert 'class="dg-landing dg-collection dg-collection--case"' in case_index
    assert "CASE FILES / 2 DOCUMENTS" in case_index
    assert 'class="dg-doc-card dg-doc-card--case"' in case_index
    assert case_index.count('class="dg-doc-card') == 2


def test_collection_page_empty_state_is_explicit_and_has_no_fake_data(taxonomy: dict) -> None:
    pages = build_index_pages([], taxonomy)
    lab_index = pages[PurePosixPath("labs/index.md")]

    assert "LABS / 0 DOCUMENTS" in lab_index
    assert "dg-doc-card" not in lab_index
    assert "dg-jump-links" not in lab_index
    assert "다" in lab_index or "없" in lab_index  # explicit, human-readable empty message


def test_status_labels_are_mapped_to_korean_copy_not_raw_strings(taxonomy: dict) -> None:
    resolved = doc(
        "cases/azure-monitor/resolved/index.md",
        title="해결된 사례",
        description="설명",
        document_type="case",
        services=["azure-monitor"],
        status="resolved",
        occurred_at=date(2026, 1, 1),
        verification_status="verified",
        tags=[],
    )
    unresolved = doc(
        "cases/azure-monitor/unresolved/index.md",
        title="조사 중 사례",
        description="설명",
        document_type="case",
        services=["azure-monitor"],
        status="unresolved",
        occurred_at=date(2026, 1, 2),
        verification_status="needs-review",
        tags=[],
    )
    historical = doc(
        "cases/azure-monitor/historical/index.md",
        title="과거 사례",
        description="설명",
        document_type="case",
        services=["azure-monitor"],
        status="historical",
        occurred_at=date(2026, 1, 3),
        verification_status="verified",
        tags=[],
    )

    pages = build_index_pages([resolved, unresolved, historical], taxonomy)
    case_index = pages[PurePosixPath("cases/index.md")]

    assert "<span>해결 기록</span>" in case_index
    assert "<span>조사 중</span>" in case_index
    assert "<span>과거 사례</span>" in case_index
    # Raw taxonomy status strings must never leak as user-facing copy.
    assert ">resolved<" not in case_index
    assert ">unresolved<" not in case_index
    assert ">historical<" not in case_index


def test_review_metadata_is_preserved_without_reader_badges(taxonomy: dict) -> None:
    needs_review = doc(
        "guides/azure-monitor/needs-review/index.md",
        title="검토 필요 가이드",
        description="설명",
        document_type="guide",
        services=["azure-monitor"],
        status="needs-review",
        last_verified=None,
        applies_to=["AKS 1.34+"],
        verification_status="needs-review",
        tags=[],
    )
    verified = doc(
        "guides/azure-monitor/verified/index.md",
        title="검증된 가이드",
        description="설명",
        document_type="guide",
        services=["azure-monitor"],
        status="current",
        last_verified=date(2026, 3, 1),
        applies_to=["AKS 1.34+"],
        verification_status="verified",
        tags=[],
    )

    pages = build_index_pages([needs_review, verified], taxonomy)
    guide_index = pages[PurePosixPath("guides/index.md")]

    assert "dg-review-state" not in guide_index
    assert "근거 재검토 필요" not in guide_index
    assert needs_review.metadata["verification_status"] == "needs-review"
    # No fabricated last_verified date for the needs-review document.
    needs_review_card = guide_index.split("검토 필요 가이드")[0]
    assert "최종 확인일" not in needs_review_card.rsplit("<article", 1)[-1]
    assert "최종 확인일: 2026-03-01" in guide_index


def test_lab_details_omit_missing_fields_without_fabricating_them(taxonomy: dict) -> None:
    complete_lab = doc(
        "labs/azure-monitor/complete/index.md",
        title="완전한 실습",
        description="설명",
        document_type="lab",
        services=["azure-monitor"],
        status="verified",
        last_verified=date(2026, 2, 1),
        estimated_time="30m",
        cost="free",
        cleanup_required=True,
        verification_status="verified",
        tags=[],
    )
    sparse_lab = doc(
        "labs/azure-monitor/sparse/index.md",
        title="부족한 실습",
        description="설명",
        document_type="lab",
        services=["azure-monitor"],
        status="needs-review",
        last_verified=None,
        verification_status="needs-review",
        tags=[],
    )

    pages = build_index_pages([complete_lab, sparse_lab], taxonomy)
    lab_index = pages[PurePosixPath("labs/index.md")]

    assert "소요 시간: 30m" in lab_index
    assert "예상 비용: free" in lab_index
    assert "정리 절차: 필요" in lab_index

    sparse_card = lab_index.split("부족한 실습", 1)[1]
    # No dg-doc-details block is fabricated when a lab is missing optional
    # fields, and no fabricated last_verified date is shown either.
    next_article_boundary = sparse_card.find("</article>")
    sparse_card_body = sparse_card[:next_article_boundary]
    assert "dg-doc-details" not in sparse_card_body
    assert "소요 시간" not in sparse_card_body
    assert "최종 확인일" not in sparse_card_body


def test_research_card_uses_published_date_and_technologies(taxonomy: dict) -> None:
    research = doc(
        "research/azure-monitor/bench/index.md",
        title="벤치마크",
        description="설명",
        document_type="research",
        services=["azure-monitor"],
        status="current",
        published_at=date(2026, 7, 22),
        verification_status="needs-review",
        technologies=["python", "kubernetes"],
        tags=[],
    )

    pages = build_index_pages([research], taxonomy)
    research_index = pages[PurePosixPath("research/index.md")]

    assert "게시일: 2026-07-22" in research_index
    assert "다룬 기술: Python, Kubernetes" in research_index


def test_service_label_falls_back_to_slug_when_taxonomy_omits_it(taxonomy: dict) -> None:
    document = doc(
        "guides/unlisted-service/topic/index.md",
        title="목록에 없는 서비스",
        description="설명",
        document_type="guide",
        services=["unlisted-service"],
        status="current",
        last_verified=date(2026, 1, 1),
        applies_to=["AKS 1.34+"],
        verification_status="verified",
        tags=[],
    )

    pages = build_index_pages([document], taxonomy)
    guide_index = pages[PurePosixPath("guides/index.md")]

    assert "## unlisted-service { #service-unlisted-service }" in guide_index
    assert PurePosixPath("services/unlisted-service/index.md") in pages
    assert "[unlisted-service](unlisted-service/index.md)" in pages[PurePosixPath("services/index.md")]


def test_tags_are_capped_at_three_and_labels_fall_back_to_slug(
    taxonomy: dict, markdown_renderer: Markdown
) -> None:
    document = doc(
        "guides/azure-monitor/many-tags/index.md",
        title="태그 많은 가이드",
        description="설명",
        document_type="guide",
        services=["azure-monitor"],
        status="current",
        last_verified=date(2026, 1, 1),
        applies_to=["AKS 1.34+"],
        verification_status="verified",
        tags=["networking", "monitoring", "latency", "unlisted-tag"],
    )

    pages = build_index_pages([document], taxonomy)
    guide_index = pages[PurePosixPath("guides/index.md")]

    rendered = render_body(markdown_renderer, guide_index)
    tags_block = rendered.split('class="dg-doc-tags"')[1].split("</div>")[0]
    assert tags_block.count('class="dg-tag"') == 3
    assert "unlisted-tag" not in tags_block


def test_title_and_description_punctuation_is_escaped_safely(taxonomy: dict) -> None:
    document = doc(
        "guides/azure-monitor/special/index.md",
        title="A & B [의 사례] <위험>",
        description='설명 "인용문" & <script>alert(1)</script>',
        document_type="guide",
        services=["azure-monitor"],
        status="current",
        last_verified=date(2026, 1, 1),
        applies_to=["AKS 1.34+"],
        verification_status="verified",
        tags=[],
    )

    pages = build_index_pages([document], taxonomy)
    guide_index = pages[PurePosixPath("guides/index.md")]

    # Description sits in raw (non-markdown) HTML, so it must be HTML-escaped
    # and not double-escaped.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in guide_index
    assert "&amp;lt;" not in guide_index
    assert "<script>" not in guide_index
    assert "\\[의 사례\\]" in guide_index
    assert "A &amp; B" in guide_index
    assert "&amp;amp;" not in guide_index


def test_rendered_card_title_preserves_literal_markup(
    taxonomy: dict, markdown_renderer: Markdown
) -> None:
    title = "C++ [A & B] <em>literal</em> *literal* `vector_id`"
    document = doc(
        "guides/azure-monitor/special/index.md",
        title=title,
        description="설명",
        document_type="guide",
        services=["azure-monitor"],
    )
    page = build_index_pages([document], taxonomy)[PurePosixPath("guides/index.md")]
    rendered = render_body(markdown_renderer, page)
    expected = (
        '<a href="azure-monitor/special/index.md">'
        f"{escape(title, quote=False)}</a>"
    )

    assert expected in rendered


def test_generated_collection_page_renders_service_groups_and_links(
    taxonomy: dict, markdown_renderer: Markdown
) -> None:
    document = doc(
        "guides/azure-kubernetes-service/topic/index.md",
        title="AKS 토픽",
        description="설명",
        document_type="guide",
        services=["azure-kubernetes-service"],
        status="current",
        last_verified=date(2026, 1, 1),
        applies_to=["AKS 1.34+"],
        verification_status="verified",
        tags=["networking"],
    )

    pages = build_index_pages([document], taxonomy)
    html = render_body(markdown_renderer, pages[PurePosixPath("guides/index.md")])

    assert '<h2 id="service-azure-kubernetes-service">' in html
    assert '<a href="#service-azure-kubernetes-service">Azure Kubernetes Service</a>' in html
    assert '<a href="azure-kubernetes-service/topic/index.md">AKS 토픽</a>' in html


def test_topic_cards_collapse_multi_document_topics_across_generated_indexes(
    tmp_path: Path, taxonomy: dict
) -> None:
    documents, catalog = build_topic_fixture(tmp_path, taxonomy)

    pages = build_index_pages(documents, taxonomy, catalog=catalog)
    home = build_home_page(HOME_TEMPLATE, documents, taxonomy, catalog=catalog)

    for path in (
        PurePosixPath("guides/index.md"),
        PurePosixPath("services/azure-monitor/index.md"),
        PurePosixPath("articles/index.md"),
    ):
        page = pages[path]
        assert page.count('class="dg-doc-card dg-topic-card') == 1
        assert "3개 문서" in page
        assert "Setup child" not in page
        assert "Results child" not in page
        assert "Standalone topic" in page

    tag_page = pages[PurePosixPath("tags/networking.md")]
    assert tag_page.count('class="dg-doc-card dg-topic-card') == 1
    assert "2 / 3개 문서 일치" in tag_page
    assert "Setup child" not in tag_page
    assert "Results child" not in tag_page
    assert "Standalone topic" in tag_page

    assert home.count('class="dg-doc-card dg-topic-card') == 1
    assert "3개 문서" in home
    assert "Setup child" not in home
    assert "Results child" not in home
    assert "Standalone topic" in home
    assert "[Topic title](services/azure-monitor/new-topic/index.md)" in home


def test_redirect_pages_point_to_canonical_topic_entries_and_stay_out_of_indexes(
    tmp_path: Path, taxonomy: dict
) -> None:
    documents, catalog = build_topic_fixture(tmp_path, taxonomy, include_redirect=True)

    redirect_path = PurePosixPath("guides/azure-monitor/old-topic/index.md")
    redirect_pages = build_redirect_pages(catalog)
    redirect_page = redirect_pages[redirect_path]

    assert yaml.safe_load(redirect_page.split("---", 2)[1]) == {
        "title": "문서 이동",
        "search": {"exclude": True},
        "hide": ["navigation", "toc"],
    }
    assert '<link rel="canonical" href="../../../services/azure-monitor/new-topic/">' in redirect_page
    assert 'http-equiv="refresh"' in redirect_page
    assert 'content="0; url=../../../services/azure-monitor/new-topic/"' in redirect_page
    assert 'href="../../../services/azure-monitor/new-topic/"' in redirect_page
    assert "services/azure-monitor/new-topic/index.md" in redirect_page

    pages = build_index_pages(documents, taxonomy, catalog=catalog)
    assert all("old-topic" not in content for content in pages.values())


def test_secondary_service_pages_show_the_matching_service_on_topic_cards(
    tmp_path: Path, taxonomy: dict
) -> None:
    documents, catalog = build_topic_fixture(tmp_path, taxonomy)
    for document in documents:
        if document.relative_path == PurePosixPath("services/azure-monitor/new-topic/setup/index.md"):
            document.metadata["services"] = ["azure-monitor", "azure-kubernetes-service"]
            break

    pages = build_index_pages(documents, taxonomy, catalog=catalog)
    service_page = pages[PurePosixPath("services/azure-kubernetes-service/index.md")]

    assert "Azure Kubernetes Service" in service_page
    assert "Azure Monitor</span><span>1 / 3개 문서 일치" not in service_page


# ---------------------------------------------------------------------------
# build_index_pages: service pages
# ---------------------------------------------------------------------------


def test_service_page_includes_documents_across_document_types(taxonomy: dict) -> None:
    case = doc(
        "cases/azure-kubernetes-service/case-1/index.md",
        title="AKS 사례",
        description="설명",
        document_type="case",
        services=["azure-kubernetes-service"],
        status="resolved",
        occurred_at=date(2026, 1, 1),
        verification_status="verified",
        tags=[],
    )
    guide = doc(
        "guides/azure-monitor/guide-1/index.md",
        title="AKS 가이드",
        description="설명",
        document_type="guide",
        services=["azure-monitor", "azure-kubernetes-service"],
        status="current",
        last_verified=date(2026, 1, 1),
        applies_to=["AKS 1.34+"],
        verification_status="verified",
        tags=[],
    )

    pages = build_index_pages([case, guide], taxonomy)
    service_page = pages[PurePosixPath("services/azure-kubernetes-service/index.md")]

    assert 'class="dg-landing dg-service"' in service_page
    assert "SERVICES / 2 DOCUMENTS" in service_page
    # Included because "azure-kubernetes-service" is in the document's
    # services metadata, even though its primary/path service is azure-monitor.
    assert "AKS 가이드" in service_page
    assert "AKS 사례" in service_page
    assert "## 트러블슈팅" not in service_page
    assert "## 구현 가이드" not in service_page


def test_service_page_preserves_path_with_explicit_zero_marker_when_empty(taxonomy: dict) -> None:
    pages = build_index_pages([], taxonomy)

    assert set(pages) >= {
        PurePosixPath("services/azure-kubernetes-service/index.md"),
        PurePosixPath("services/azure-monitor/index.md"),
    }
    empty_page = pages[PurePosixPath("services/azure-kubernetes-service/index.md")]
    assert "SERVICES / 0 DOCUMENTS" in empty_page
    assert "dg-doc-card" not in empty_page


def test_services_overview_lists_every_service_with_real_counts(taxonomy: dict) -> None:
    document = doc(
        "cases/azure-kubernetes-service/case-1/index.md",
        title="AKS 사례",
        description="설명",
        document_type="case",
        services=["azure-kubernetes-service"],
        status="resolved",
        occurred_at=date(2026, 1, 1),
        verification_status="verified",
        tags=[],
    )

    pages = build_index_pages([document], taxonomy)
    overview = pages[PurePosixPath("services/index.md")]

    assert 'class="dg-landing dg-services"' in overview
    assert "SERVICES / 1 DOCUMENTS" in overview
    assert "[Azure Kubernetes Service](azure-kubernetes-service/index.md)" in overview
    assert "[Azure Monitor](azure-monitor/index.md)" in overview
    # Real counts: one document for AKS, zero (explicit) for Azure Monitor.
    assert "1개 문서" in overview
    assert "0개 문서" in overview


def test_services_overview_orders_nonempty_services_before_empty_ones(taxonomy: dict) -> None:
    # Taxonomy insertion order lists azure-kubernetes-service before
    # azure-monitor, but only azure-monitor has documents here, so the sort
    # (not insertion order) must promote it to the front.
    document = doc(
        "guides/azure-monitor/g1/index.md",
        title="AKS 진단",
        description="설명",
        document_type="guide",
        services=["azure-monitor"],
        status="current",
        last_verified=date(2026, 1, 1),
        applies_to=["AKS 1.34+"],
        verification_status="verified",
        tags=[],
    )

    pages = build_index_pages([document], taxonomy)
    overview = pages[PurePosixPath("services/index.md")]

    aks_index = overview.find("[Azure Kubernetes Service]")
    monitor_index = overview.find("[Azure Monitor]")
    assert monitor_index != -1 and aks_index != -1
    assert monitor_index < aks_index


def test_services_overview_orders_by_descending_count_then_label(taxonomy: dict) -> None:
    many_docs_service = "azure-kubernetes-service"
    few_docs_service = "azure-monitor"
    documents = [
        doc(
            f"guides/{many_docs_service}/g{i}/index.md",
            title=f"가이드{i}",
            description="설명",
            document_type="guide",
            services=[many_docs_service],
            status="current",
            last_verified=date(2026, 1, 1),
            applies_to=["AKS 1.34+"],
            verification_status="verified",
            tags=[],
        )
        for i in range(2)
    ] + [
        doc(
            f"guides/{few_docs_service}/g/index.md",
            title="가이드3",
            description="설명",
            document_type="guide",
            services=[few_docs_service],
            status="current",
            last_verified=date(2026, 1, 1),
            applies_to=["AKS 1.34+"],
            verification_status="verified",
            tags=[],
        )
    ]

    pages = build_index_pages(documents, taxonomy)
    overview = pages[PurePosixPath("services/index.md")]

    aks_index = overview.find("[Azure Kubernetes Service]")
    monitor_index = overview.find("[Azure Monitor]")
    # AKS has 2 documents and Azure Monitor has 1: higher count sorts first.
    assert aks_index < monitor_index


# ---------------------------------------------------------------------------
# build_home_page
# ---------------------------------------------------------------------------


HOME_TEMPLATE = """---
title: Azure Engineering Notes
description: 홈
---

# 홈

<!-- home:stats -->

<!-- home:featured -->

<!-- home:browse -->
"""


def test_home_page_requires_all_three_slots_exactly_once() -> None:
    with pytest.raises(ValueError):
        build_home_page("no slots", [], {"collections": {}})

    with pytest.raises(ValueError):
        build_home_page(
            "<!-- home:stats --><!-- home:stats -->"
            "<!-- home:featured --><!-- home:browse -->",
            [],
            {"collections": {}},
        )

    with pytest.raises(ValueError):
        build_home_page(
            "<!-- home:stats --><!-- home:featured -->",
            [],
            {"collections": {}},
        )


def test_home_page_selects_featured_documents_sorted_case_first(taxonomy: dict) -> None:
    featured_guide = doc(
        "guides/azure-monitor/g/index.md",
        title="B 가이드",
        description="설명",
        document_type="guide",
        services=["azure-monitor"],
        status="current",
        last_verified=date(2026, 1, 1),
        applies_to=["AKS 1.34+"],
        verification_status="verified",
        tags=[],
        featured=True,
    )
    featured_case = doc(
        "cases/azure-monitor/c/index.md",
        title="A 사례",
        description="설명",
        document_type="case",
        services=["azure-monitor"],
        status="resolved",
        occurred_at=date(2026, 1, 1),
        verification_status="verified",
        tags=[],
        featured=True,
    )
    unfeatured = doc(
        "research/azure-monitor/r/index.md",
        title="리서치",
        description="설명",
        document_type="research",
        services=["azure-monitor"],
        status="current",
        published_at=date(2026, 1, 1),
        verification_status="verified",
        tags=[],
    )

    rendered = build_home_page(HOME_TEMPLATE, [featured_guide, featured_case, unfeatured], taxonomy)

    featured_block = rendered.split('class="dg-feature-grid"', 1)[1]
    case_index = featured_block.find("A 사례")
    guide_index = featured_block.find("B 가이드")
    assert case_index != -1 and guide_index != -1
    # Case-first taxonomy order: the case collection precedes guide, so the
    # featured case must appear before the featured guide despite its title
    # sorting after "B" alphabetically... the collection order wins.
    assert case_index < guide_index


def test_home_page_falls_back_to_one_per_collection_when_nothing_featured(
    taxonomy: dict,
) -> None:
    documents = [
        doc(
            "cases/azure-monitor/c1/index.md",
            title="사례1",
            description="설명",
            document_type="case",
            services=["azure-monitor"],
            status="resolved",
            occurred_at=date(2026, 1, 1),
            verification_status="verified",
            tags=[],
        ),
        doc(
            "guides/azure-monitor/g1/index.md",
            title="가이드1",
            description="설명",
            document_type="guide",
            services=["azure-monitor"],
            status="current",
            last_verified=date(2026, 1, 1),
            applies_to=["AKS 1.34+"],
            verification_status="verified",
            tags=[],
        ),
    ]

    rendered = build_home_page(HOME_TEMPLATE, documents, taxonomy)
    featured_block = rendered.split('class="dg-feature-grid"', 1)[1].split(
        'class="dg-browse-grid"', 1
    )[0]

    assert "사례1" in featured_block
    assert "가이드1" in featured_block
    assert featured_block.count('class="dg-doc-card') == 2


def test_home_page_featured_empty_state_is_honest_when_no_documents(taxonomy: dict) -> None:
    rendered = build_home_page(HOME_TEMPLATE, [], taxonomy)
    assert "dg-doc-card" not in rendered
    assert "dg-feature-grid" not in rendered


def test_home_page_counts_are_derived_not_hardcoded(taxonomy: dict) -> None:
    documents = [
        doc(
            "cases/azure-monitor/c1/index.md",
            title="사례1",
            description="설명",
            document_type="case",
            services=["azure-monitor"],
            status="resolved",
            occurred_at=date(2026, 1, 1),
            verification_status="verified",
            tags=[],
        ),
        doc(
            "cases/azure-kubernetes-service/c2/index.md",
            title="사례2",
            description="설명",
            document_type="case",
            services=["azure-kubernetes-service"],
            status="resolved",
            occurred_at=date(2026, 1, 1),
            verification_status="verified",
            tags=[],
        ),
    ]

    rendered = build_home_page(HOME_TEMPLATE, documents, taxonomy)
    stats_block = rendered.split('class="dg-stats"', 1)[1].split("</div>\n\n</div>")[0]

    assert "<strong>2</strong>" in stats_block  # total documents
    assert "<strong>0</strong>" in stats_block
    assert "다루는 태그" in stats_block


def test_home_page_browse_block_lists_destinations_with_real_counts(
    taxonomy: dict,
) -> None:
    document = doc(
        "guides/azure-monitor/g1/index.md",
        title="가이드1",
        description="설명",
        document_type="guide",
        services=["azure-monitor"],
        status="current",
        last_verified=date(2026, 1, 1),
        applies_to=["AKS 1.34+"],
        verification_status="verified",
        tags=[],
    )

    rendered = build_home_page(HOME_TEMPLATE, [document], taxonomy)
    browse_block = rendered.split('class="dg-browse-grid"', 1)[1]

    assert browse_block.count('class="dg-browse-card') == 3
    assert "[서비스별 보기](services/index.md)" in browse_block
    assert "[태그별 보기](tags/index.md)" in browse_block
    assert "[전체 글](articles/index.md)" in browse_block
    assert "1개 문서" in browse_block
    assert "1개 서비스" in browse_block
    assert "0개 태그" in browse_block


def test_home_page_malformed_template_fails_explicitly() -> None:
    malformed_templates = [
        "",
        "<!-- home:featured --><!-- home:browse -->",
        "<!-- home:stats --><!-- home:browse -->",
        "<!-- home:stats --><!-- home:featured -->",
    ]
    for template in malformed_templates:
        with pytest.raises(ValueError):
            build_home_page(template, [], {"collections": {}})


def test_real_docs_index_template_has_exactly_one_of_each_slot() -> None:
    template = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    for slot in ("<!-- home:stats -->", "<!-- home:featured -->", "<!-- home:browse -->"):
        assert template.count(slot) == 1
