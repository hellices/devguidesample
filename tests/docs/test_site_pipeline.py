from __future__ import annotations

from datetime import date
import json
from pathlib import Path, PurePosixPath

import yaml

from scripts.docs import validate_search_index
from scripts.docs.content import load_document
from scripts.docs.generate_indexes import build_index_pages
from scripts.docs.hooks import on_page_markdown


FIXTURE = Path(__file__).parent / "fixtures" / "valid-guide.md"

SEARCH_DOCUMENT = """\
---
title: AKS 네트워크 진단
description: AKS 네트워크 문제를 진단하는 절차
document_type: guide
services: [aks]
technologies: [kubernetes]
tags: [networking, troubleshooting]
status: current
verification_status: verified
sources_checked_at: 2026-09-12
official_sources:
  - title: Azure Kubernetes Service documentation
    url: https://learn.microsoft.com/azure/aks/
last_verified: 2026-09-12
review_cycle_days: 180
applies_to: [AKS 1.34+]
---

# AKS 네트워크 진단

네트워크 연결 문제를 확인합니다. Azure Kubernetes Service diagnostic workflow를 설명합니다.
"""


def test_indexes_are_generated_from_metadata_with_safe_yaml() -> None:
    loaded = load_document(FIXTURE, docs_dir=FIXTURE.parent)
    document = loaded.__class__(
        path=loaded.path,
        relative_path=PurePosixPath("guides/aks/network-diagnosis/index.md"),
        metadata={
            **loaded.metadata,
            "title": "AKS: 파일 I/O",
            "services": ["aks", "azure-monitor"],
        },
        body=loaded.body,
    )
    taxonomy = {
        "collections": {
            "guide": {
                "path": "guides",
                "title": "일반 가이드",
                "description": "# 안내: 지속 갱신형 절차",
            },
            "case": {
                "path": "cases",
                "title": "문제 해결 사례",
                "description": "시점 고정 이력",
            },
        },
        "services": {
            "aks": "Azure Kubernetes Service",
            "azure-monitor": "Azure Monitor",
        },
    }

    pages = build_index_pages([document], taxonomy)

    assert set(pages) == {
        PurePosixPath("cases/index.md"),
        PurePosixPath("guides/index.md"),
        PurePosixPath("services/index.md"),
        PurePosixPath("services/aks.md"),
        PurePosixPath("services/azure-monitor.md"),
    }
    guide_front_matter = pages[PurePosixPath("guides/index.md")].split("---", 2)[1]
    assert yaml.safe_load(guide_front_matter) == {
        "title": "일반 가이드",
        "description": "# 안내: 지속 갱신형 절차",
    }
    assert pages[PurePosixPath("guides/index.md")].count("AKS: 파일 I/O") == 1
    assert "../guides/aks/network-diagnosis/index.md" in pages[
        PurePosixPath("services/aks.md")
    ]


def test_mkdocs_keeps_navigation_and_search_metadata_driven() -> None:
    root = Path(__file__).parents[2]
    config = yaml.safe_load((root / "mkdocs.yml").read_text(encoding="utf-8"))

    assert "nav" not in config
    plugins = config["plugins"]
    assert "awesome-nav" in plugins
    assert "tags" in plugins
    assert any(
        isinstance(plugin, dict) and "gen-files" in plugin
        for plugin in plugins
    )
    search = next(
        plugin["search"]
        for plugin in plugins
        if isinstance(plugin, dict) and "search" in plugin
    )
    assert search["lang"] == ["ko", "en"]


class Page:
    def __init__(self, metadata: dict) -> None:
        self.meta = metadata


def test_page_hook_renders_source_status_and_missing_values() -> None:
    rendered = on_page_markdown(
        "# Page\n",
        Page(
            {
                "document_type": "guide",
                "verification_status": "needs-review",
                "sources_checked_at": date(2026, 9, 12),
                "official_sources": [
                    {
                        "title": "Azure Kubernetes Service documentation",
                        "url": "https://learn.microsoft.com/azure/aks/",
                    }
                ],
            }
        ),
        {},
        None,
    )
    missing = on_page_markdown(
        "# Page\n",
        Page(
            {
                "document_type": "guide",
                "verification_status": "needs-review",
                "sources_checked_at": None,
                "official_sources": None,
            }
        ),
        {},
        None,
    )

    assert "공식 문서 재검토 필요" in rendered
    assert "2026-09-12" in rendered
    assert (
        "[Azure Kubernetes Service documentation]"
        "(https://learn.microsoft.com/azure/aks/)"
    ) in rendered
    assert "출처 확인일:** unknown" in missing
    assert "공식 근거:** 등록되지 않음" in missing


def make_search_repository(tmp_path: Path) -> Path:
    taxonomy = {
        "collections": {"guide": {"path": "guides"}},
        "services": {"aks": "Azure Kubernetes Service"},
        "technologies": {"kubernetes": "Kubernetes"},
        "tags": {
            "networking": "Networking",
            "troubleshooting": "Troubleshooting",
        },
    }
    (tmp_path / "docs-taxonomy.yml").write_text(
        yaml.safe_dump(taxonomy, allow_unicode=True),
        encoding="utf-8",
    )
    page = tmp_path / "docs" / "guides" / "aks" / "network-diagnosis"
    page.mkdir(parents=True)
    (page / "index.md").write_text(SEARCH_DOCUMENT, encoding="utf-8")
    (tmp_path / "site" / "search").mkdir(parents=True)
    return tmp_path


def write_search_index(root: Path, documents: list[dict[str, str]]) -> None:
    (root / "site" / "search" / "search_index.json").write_text(
        json.dumps({"config": {}, "docs": documents}, ensure_ascii=False),
        encoding="utf-8",
    )


def page_search_entry(text: str) -> dict[str, str]:
    return {
        "location": "guides/aks/network-diagnosis/",
        "title": "AKS 네트워크 진단",
        "text": text,
    }


def test_search_gate_accepts_full_text_and_tag_entries(tmp_path: Path) -> None:
    root = make_search_repository(tmp_path)
    write_search_index(
        root,
        [
            page_search_entry(
                "<p>네트워크 연결 문제를 확인합니다. "
                "Azure Kubernetes Service diagnostic workflow를 설명합니다.</p>"
            ),
            {
                "location": "tags/#tag:networking",
                "title": "networking",
                "text": "AKS 네트워크 진단",
            },
            {
                "location": "tags/#tag:troubleshooting",
                "title": "troubleshooting",
                "text": "AKS 네트워크 진단",
            },
        ],
    )

    result = validate_search_index.validate_repository(root)

    assert result.document_count == 1
    assert result.tag_count == 2
    assert result.errors == []
    assert validate_search_index._page_location(PurePosixPath("index.md")) == ""


def test_search_gate_rejects_missing_tags_and_body_text(tmp_path: Path) -> None:
    root = make_search_repository(tmp_path)
    write_search_index(root, [page_search_entry("<p>unrelated content</p>")])

    result = validate_search_index.validate_repository(root)

    assert any("tag is missing: networking" in error for error in result.errors)
    assert any("Korean body text" in error for error in result.errors)
    assert any("English product phrase" in error for error in result.errors)
