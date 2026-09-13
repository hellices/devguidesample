from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from urllib.parse import urljoin

from markdown import Markdown
from material.plugins.search.plugin import SearchIndex
from mkdocs.commands.build import build
from mkdocs.config import load_config
from mkdocs.exceptions import Abort
import pytest
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
        PurePosixPath("guides/aks/index.md"),
        PurePosixPath("services/index.md"),
        PurePosixPath("services/aks.md"),
        PurePosixPath("services/azure-monitor.md"),
    }
    guide_front_matter = pages[PurePosixPath("guides/index.md")].split("---", 2)[1]
    assert yaml.safe_load(guide_front_matter) == {
        "title": "일반 가이드",
        "description": "# 안내: 지속 갱신형 절차",
        "hide": ["toc"],
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


def test_strict_build_rejects_missing_anchors(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text("# Page\n\n[Missing](#missing)\n", encoding="utf-8")
    config = load_config(
        config_file=str(Path(__file__).parents[2] / "mkdocs.yml"),
        docs_dir=str(docs),
        site_dir=str(tmp_path / "site"),
        plugins=[],
        hooks=[],
        extra_css=[],
        strict=True,
    )

    with pytest.raises(Abort):
        build(config)

    assert "no such anchor" in caplog.text


def test_navigation_renders_collapsible_groups(tmp_path: Path) -> None:
    class NavigationParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.toggles: set[str] = set()
            self.labels: set[str] = set()
            self.fixed_sections = 0
            self.expanded_groups = 0

        def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
            attrs = dict(attributes)
            classes = (attrs.get("class") or "").split()
            identifier = attrs.get("id")
            label_for = attrs.get("for")
            if (
                tag == "input"
                and "md-nav__toggle" in classes
                and isinstance(identifier, str)
                and identifier.startswith("__nav_")
            ):
                self.toggles.add(identifier)
                self.expanded_groups += "checked" in attrs
            if tag == "label" and isinstance(label_for, str):
                self.labels.add(label_for)
            self.fixed_sections += "md-nav__item--section" in classes

    docs = tmp_path / "docs"
    docs.mkdir()
    for name in ("index", "guide", "lab"):
        (docs / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
    config = load_config(
        config_file=str(Path(__file__).parents[2] / "mkdocs.yml"),
        docs_dir=str(docs),
        site_dir=str(tmp_path / "site"),
        nav=[
            {"Home": "index.md"},
            {"Guides": [{"Guide": "guide.md"}]},
            {"Labs": [{"Lab": "lab.md"}]},
        ],
        plugins=[],
        hooks=[],
        extra_css=[],
        strict=True,
    )
    build(config)
    parser = NavigationParser()
    parser.feed((tmp_path / "site" / "index.html").read_text(encoding="utf-8"))

    assert len(parser.toggles) >= 2
    assert parser.toggles <= parser.labels
    assert parser.fixed_sections == 0
    assert parser.expanded_groups == 0


class Page:
    def __init__(self, metadata: dict) -> None:
        self.meta = metadata


def test_page_hook_keeps_sources_without_workflow_notices() -> None:
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

    assert "재검토" not in rendered
    assert "마이그레이션" not in rendered
    assert "needs-review" not in rendered
    assert "2026-09-12" not in rendered
    assert '<details class="doc-sources">' in rendered
    assert 'href="https://learn.microsoft.com/azure/aks/"' in rendered
    assert "Azure Kubernetes Service documentation" in rendered
    assert missing == "# Page\n"


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
    site_config = yaml.safe_load(
        (Path(__file__).parents[2] / "mkdocs.yml").read_text(encoding="utf-8")
    )
    (tmp_path / "mkdocs.yml").write_text(
        yaml.safe_dump(
            {
                "site_name": "Search test",
                "markdown_extensions": site_config["markdown_extensions"],
            }
        ),
        encoding="utf-8",
    )
    page = tmp_path / "docs" / "guides" / "aks" / "network-diagnosis"
    page.mkdir(parents=True)
    (page / "index.md").write_text(SEARCH_DOCUMENT, encoding="utf-8")
    (tmp_path / "site" / "search").mkdir(parents=True)
    return tmp_path


def test_new_bundle_updates_navigation_and_search_without_config_edits(
    tmp_path: Path,
) -> None:
    class PrimaryNavigation(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.depth = 0
            self.links: dict[str, str] = {}
            self.target: str | None = None
            self.link_text: list[str] = []

        def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
            attrs = dict(attributes)
            if tag == "nav" and (
                self.depth or "md-nav--primary" in (attrs.get("class") or "").split()
            ):
                self.depth += 1
            target = attrs.get("href")
            if tag == "a" and self.depth and isinstance(target, str):
                self.target = target
                self.link_text = []

        def handle_endtag(self, tag: str) -> None:
            if tag == "a" and self.target is not None:
                self.links[self.target] = " ".join("".join(self.link_text).split())
                self.target = None
            if tag == "nav" and self.depth:
                self.depth -= 1

        def handle_data(self, text: str) -> None:
            if self.depth and self.target is not None:
                self.link_text.append(text)

    root = make_search_repository(tmp_path)
    docs = root / "docs"
    (docs / "index.md").write_text(
        "# Home\n\n<!-- home:stats -->\n\n<!-- home:featured -->\n\n<!-- home:collections -->\n",
        encoding="utf-8",
    )
    (docs / "tags.md").write_text("# Tags\n\n<!-- material/tags -->\n", encoding="utf-8")
    nav_path = docs / ".nav.yml"
    nav_path.write_text(
        "nav:\n  - Home: index.md\n  - Guides: guides\n  - Services: services\n  - Tags: tags.md\n",
        encoding="utf-8",
    )
    generator = root / "generate.py"
    generator.write_text(
        "from pathlib import Path\n"
        "from scripts.docs.generate_indexes import write_generated_pages\n"
        f"write_generated_pages(Path({str(root)!r}))\n",
        encoding="utf-8",
    )
    config_path = root / "mkdocs.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config.update(
        {
            "theme": {"name": "material", "features": ["navigation.indexes"]},
            "hooks": [str(Path(__file__).parents[2] / "scripts" / "docs" / "hooks.py")],
            "plugins": [
                {"search": {"lang": ["ko", "en"]}},
                "tags",
                {"gen-files": {"scripts": [str(generator)]}},
                "awesome-nav",
            ],
            "validation": {"links": {"anchors": "warn"}},
        }
    )
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    unchanged_paths = (config_path, nav_path, root / "docs-taxonomy.yml")
    original_settings = [path.read_bytes() for path in unchanged_paths]
    build(load_config(str(config_path), strict=True))
    single_document_navigation = PrimaryNavigation()
    single_document_navigation.feed(
        (root / "site" / "index.html").read_text(encoding="utf-8")
    )

    assert single_document_navigation.links["guides/aks/network-diagnosis/"] == "AKS 네트워크 진단"
    assert single_document_navigation.links["guides/aks/"] == "Azure Kubernetes Service"

    page = docs / "guides" / "aks" / "new-topic" / "index.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        SEARCH_DOCUMENT.replace("AKS 네트워크 진단", "자동 게시 확인")
        + "\n추가된 문서의 검색 본문입니다.\n",
        encoding="utf-8",
    )
    third_page = docs / "guides" / "aks" / "z-last-topic" / "index.md"
    third_page.parent.mkdir(parents=True)
    third_page.write_text(
        SEARCH_DOCUMENT.replace("AKS 네트워크 진단", "세 번째 문서"),
        encoding="utf-8",
    )
    build(load_config(str(config_path), strict=True))
    navigation = PrimaryNavigation()
    navigation.feed((root / "site" / "index.html").read_text(encoding="utf-8"))
    search = json.loads(
        (root / "site" / "search" / "search_index.json").read_text(encoding="utf-8")
    )

    assert [path.read_bytes() for path in unchanged_paths] == original_settings
    assert navigation.links["guides/aks/network-diagnosis/"] == "AKS 네트워크 진단"
    assert navigation.links["guides/aks/new-topic/"] == "자동 게시 확인"
    assert navigation.links["guides/aks/z-last-topic/"] == "세 번째 문서"
    assert navigation.links["guides/aks/"] == "Azure Kubernetes Service"
    assert navigation.links["guides/"] == "Guides"
    assert "자동 게시 확인" in (root / "site" / "guides" / "index.html").read_text(encoding="utf-8")
    assert any(
        entry["location"] == "guides/aks/new-topic/"
        and "추가된 문서" in entry["text"]
        for entry in search["docs"]
    )
    article_navigation = PrimaryNavigation()
    article_navigation.feed(
        (root / "site" / "guides" / "aks" / "network-diagnosis" / "index.html").read_text(
            encoding="utf-8"
        )
    )
    article_url = "https://example.test/guides/aks/network-diagnosis/"
    resolved_links = {
        urljoin(article_url, target): title
        for target, title in article_navigation.links.items()
    }
    assert resolved_links[article_url] == "AKS 네트워크 진단"
    assert resolved_links["https://example.test/guides/aks/"] == "Azure Kubernetes Service"
    assert resolved_links["https://example.test/guides/aks/new-topic/"] == "자동 게시 확인"
    assert resolved_links["https://example.test/guides/aks/z-last-topic/"] == "세 번째 문서"


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


@pytest.mark.parametrize(
    "body",
    [
        "# Guide\n\nUse **Azure Kubernetes** Service. 본문입니다.",
        "# Guide\n\nAzure **Kubernetes Service** 설명입니다.",
        "# Guide\n\n![네트워크구성도](images/network.png)\n\n"
        "본문입니다. Azure Kubernetes Service.",
        "# Guide\n\n<!-- 숨겨진메모 Unsearchable Product -->\n\n"
        "본문입니다. Azure Kubernetes Service.",
        '# Guide\n\n![diagram](images/network.png){ title="Azure Portal Screenshot" }\n\n'
        "본문입니다. Azure Kubernetes Service.",
    ],
)
def test_search_gate_accepts_visible_rendered_markdown(
    tmp_path: Path, body: str
) -> None:
    root = make_search_repository(tmp_path)
    path = root / "docs" / "guides" / "aks" / "network-diagnosis" / "index.md"
    front_matter = SEARCH_DOCUMENT.split("\n# ", 1)[0]
    path.write_text(front_matter + "\n\n" + body, encoding="utf-8")
    document = load_document(path, docs_dir=root / "docs")
    config = load_config(config_file=str(root / "mkdocs.yml"))
    renderer = Markdown(
        extensions=config.markdown_extensions, extension_configs=config.mdx_configs
    )
    page = SimpleNamespace(
        meta=document.metadata,
        title=document.metadata["title"],
        content=renderer.convert(document.body),
        toc=[],
        url="guides/aks/network-diagnosis/",
    )
    index = SearchIndex()
    index.add_entry_from_context(page)
    write_search_index(
        root,
        index.entries
        + [
            {
                "location": f"tags/#tag:{tag}",
                "title": tag,
                "text": page.title,
            }
            for tag in document.metadata["tags"]
        ],
    )

    result = validate_search_index.validate_repository(root)

    assert result.errors == []
