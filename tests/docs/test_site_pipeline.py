from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from urllib.parse import urljoin

from markdown import Markdown
from mkdocs.structure.files import Files, InclusionLevel
from material.plugins.search.plugin import SearchIndex
from mkdocs.commands.build import build
from mkdocs.config import load_config
from mkdocs.exceptions import Abort
import pytest
import yaml

from scripts.docs import validate_search_index
from scripts.docs.content import DocumentFormatError, iter_public_documents, load_document
from scripts.docs.generate_indexes import build_index_pages, write_generated_pages
from scripts.docs.hooks import on_files, on_page_markdown, on_post_page
from scripts.docs.topics import build_topic_catalog


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


def write_topic_document(
    docs_dir: Path,
    relative_path: str,
    title: str,
    *,
    tags: list[str],
    topic_order: int | None = None,
    featured: bool = False,
    redirect_from: list[str] | None = None,
) -> None:
    metadata: dict[str, object] = {
        "title": title,
        "description": f"{title} 설명",
        "document_type": "guide",
        "services": ["aks"],
        "technologies": ["kubernetes"],
        "tags": tags,
        "status": "current",
        "verification_status": "verified",
        "sources_checked_at": "2026-09-12",
        "official_sources": [
            {
                "title": "Azure Kubernetes Service documentation",
                "url": "https://learn.microsoft.com/azure/aks/",
            }
        ],
        "last_verified": "2026-09-12",
        "review_cycle_days": 180,
        "applies_to": ["AKS 1.34+"],
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
        + f"# {title}\n\n{title} 본문입니다.\n",
        encoding="utf-8",
    )


class TopicReaderPage(HTMLParser):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.navigation_depth = 0
        self.navigation_parents: list[str | None] = []
        self.last_navigation_target: str | None = None
        self.navigation_entries: list[tuple[str, str, tuple[str, ...]]] = []
        self.expanded_groups = 0
        self.topic_nav_depth = 0
        self.topic_nav_links: list[tuple[str, str]] = []
        self.current_link: tuple[str, str] | None = None
        self.link_text: list[str] = []
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "nav" and (self.navigation_depth or "md-nav--primary" in classes):
            self.navigation_depth += 1
            self.navigation_parents.append(self.last_navigation_target)
        if tag == "nav" and "dg-topic-nav" in classes:
            self.topic_nav_depth += 1
        if self.navigation_depth and tag == "input" and "md-nav__toggle" in classes:
            self.expanded_groups += "checked" in attributes
        target = attributes.get("href")
        if tag != "a" or not isinstance(target, str):
            return
        self.current_link = (
            target,
            "navigation" if self.navigation_depth else "topic" if self.topic_nav_depth else "other",
        )
        self.link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_link is not None:
            target, kind = self.current_link
            title = " ".join("".join(self.link_text).split())
            if kind == "navigation":
                parents = tuple(parent for parent in self.navigation_parents if parent is not None)
                self.navigation_entries.append((target, title, parents))
                self.last_navigation_target = target
            elif kind == "topic":
                self.topic_nav_links.append((target, title))
            self.current_link = None
        if tag == "nav" and self.topic_nav_depth:
            self.topic_nav_depth -= 1
        if tag == "nav" and self.navigation_depth:
            self.navigation_depth -= 1
            self.navigation_parents.pop()

    def handle_data(self, data: str) -> None:
        if self.current_link is not None:
            self.link_text.append(data)


def make_topic_repository(tmp_path: Path) -> Path:
    root = tmp_path
    docs = root / "docs"
    docs.mkdir()
    (docs / "index.md").write_text(
        "# Home\n\n<!-- home:stats -->\n\n<!-- home:featured -->\n\n<!-- home:browse -->\n",
        encoding="utf-8",
    )
    (docs / ".nav.yml").write_text(
        "nav:\n  - Home: index.md\n  - Services: services\n  - Tags: tags\n"
        "  - Articles: articles\n  - glob: '*'\n    ignore_no_matches: true\n",
        encoding="utf-8",
    )
    taxonomy = {
        "collections": {"guide": {"path": "guides", "title": "구현 가이드"}},
        "services": {"aks": "Azure Kubernetes Service"},
        "technologies": {"kubernetes": "Kubernetes"},
        "tags": {"networking": "Networking", "monitoring": "Monitoring"},
        "verification_statuses": ["verified", "needs-review"],
        "official_source_hosts": ["learn.microsoft.com"],
        "required_source_host": "learn.microsoft.com",
    }
    (root / "docs-taxonomy.yml").write_text(
        yaml.safe_dump(taxonomy, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    site_config = yaml.safe_load(
        (Path(__file__).parents[2] / "mkdocs.yml").read_text(encoding="utf-8")
    )
    config_path = root / "mkdocs.yml"
    site_config.update(
        {
            "site_name": "Topic test",
            "site_url": "https://example.test/devguidesample/",
            "repo_url": "https://github.com/example/devguidesample",
            "docs_dir": str(docs),
            "site_dir": str(root / "site"),
        }
    )
    generator = root / "generate.py"
    generator.write_text(
        "from pathlib import Path\n"
        "from scripts.docs.generate_indexes import write_generated_pages\n"
        f"write_generated_pages(Path({str(root)!r}))\n",
        encoding="utf-8",
    )
    site_config["hooks"] = [str(Path(__file__).parents[2] / "scripts" / "docs" / "hooks.py")]
    site_config["plugins"] = [
        {"search": {"lang": ["ko", "en"]}},
        {"tags": {"tags": False, "listings": False}},
        {"gen-files": {"scripts": [str(generator)]}},
        "awesome-nav",
    ]
    config_path.write_text(yaml.safe_dump(site_config), encoding="utf-8")

    write_topic_document(
        docs,
        "services/aks/network-diagnosis/index.md",
        "Topic title",
        tags=["networking"],
        redirect_from=["guides/aks/old-topic/index.md"],
    )
    write_topic_document(
        docs,
        "services/aks/network-diagnosis/setup/index.md",
        "Setup child",
        tags=["networking"],
        topic_order=1,
        featured=True,
    )
    write_topic_document(
        docs,
        "services/aks/network-diagnosis/results/index.md",
        "Results child",
        tags=["monitoring"],
        topic_order=2,
    )
    write_topic_document(
        docs,
        "services/aks/standalone-topic/index.md",
        "Standalone topic",
        tags=["networking"],
        featured=True,
    )
    sample_dir = docs / "services" / "aks" / "network-diagnosis" / "samples" / "event-lab"
    sample_dir.mkdir(parents=True, exist_ok=True)
    (sample_dir / "sample.yml").write_text(
        yaml.safe_dump(
            {
                "title": "Event lab",
                "description": "Reproduces the monitored incident.",
                "kind": "runnable",
                "used_by": ["setup"],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (sample_dir / "README.md").write_text("# Event lab\n", encoding="utf-8")
    return root


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
        PurePosixPath("services/aks/index.md"),
        PurePosixPath("services/azure-monitor/index.md"),
        PurePosixPath("articles/index.md"),
        PurePosixPath("tags/index.md"),
        PurePosixPath("tags/networking.md"),
        PurePosixPath("tags/troubleshooting.md"),
    }
    guide_front_matter = pages[PurePosixPath("guides/index.md")].split("---", 2)[1]
    assert yaml.safe_load(guide_front_matter) == {
        "title": "일반 가이드",
        "description": "# 안내: 지속 갱신형 절차",
        "hide": ["toc"],
    }
    assert pages[PurePosixPath("guides/index.md")].count("AKS: 파일 I/O") == 1
    assert "../../guides/aks/network-diagnosis/index.md" in pages[
        PurePosixPath("services/aks/index.md")
    ]


def test_mkdocs_keeps_navigation_and_search_metadata_driven() -> None:
    root = Path(__file__).parents[2]
    config = yaml.safe_load((root / "mkdocs.yml").read_text(encoding="utf-8"))

    assert "nav" not in config
    plugins = config["plugins"]
    assert "awesome-nav" in plugins
    assert any(plugin == "tags" or isinstance(plugin, dict) and "tags" in plugin for plugin in plugins)
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
    assert config["exclude_docs"].strip() == "services/**/samples/**"


def test_topic_and_sample_styles_are_responsive_and_accessible() -> None:
    css = (
        Path(__file__).parents[2] / "docs/assets/stylesheets/extra.css"
    ).read_text(encoding="utf-8")

    for selector in (
        ".dg-topic-card",
        ".dg-topic-overview",
        ".dg-topic-list",
        ".dg-topic-context",
        ".dg-topic-nav",
        ".dg-sample-grid",
        ".dg-sample-card",
    ):
        assert selector in css

    mobile = css.split("@media (max-width: 760px)", 1)[1].split(
        "@media (max-width: 480px)", 1
    )[0]
    assert ".dg-topic-nav" in mobile
    assert ".dg-sample-grid" in mobile
    assert "grid-template-columns: minmax(0, 1fr)" in mobile
    assert "a:focus-visible" in css

    reduced_motion = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    assert ".dg-sample-card" in reduced_motion
    assert "transition: none" in reduced_motion


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


def test_on_files_excludes_all_markdown_under_samples() -> None:
    readme = SimpleNamespace(
        src_uri="services/aks/network-diagnosis/samples/event-lab/README.md",
        inclusion=InclusionLevel.UNDEFINED,
    )
    notes = SimpleNamespace(
        src_uri="services/aks/network-diagnosis/samples/event-lab/notes.md",
        inclusion=InclusionLevel.UNDEFINED,
    )
    regular = SimpleNamespace(
        src_uri="services/aks/network-diagnosis/index.md",
        inclusion=InclusionLevel.UNDEFINED,
    )
    manifest = SimpleNamespace(
        src_uri="services/aks/network-diagnosis/samples/event-lab/sample.yml",
        inclusion=InclusionLevel.UNDEFINED,
    )

    on_files([readme, notes, manifest, regular], {})

    assert readme.inclusion is InclusionLevel.EXCLUDED
    assert notes.inclusion is InclusionLevel.EXCLUDED
    assert manifest.inclusion is InclusionLevel.EXCLUDED
    assert regular.inclusion is InclusionLevel.UNDEFINED


def test_topic_catalog_integration_preserves_public_path_filter(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    taxonomy = {
        "collections": {"guide": {"path": "guides", "title": "구현 가이드"}},
        "services": {"aks": "Azure Kubernetes Service"},
        "technologies": {"kubernetes": "Kubernetes"},
        "tags": {"networking": "Networking", "troubleshooting": "Troubleshooting"},
        "verification_statuses": ["verified", "needs-review"],
        "official_source_hosts": ["learn.microsoft.com"],
        "required_source_host": "learn.microsoft.com",
    }
    (tmp_path / "docs-taxonomy.yml").write_text(
        yaml.safe_dump(taxonomy, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    invalid = docs / "services" / "AKS" / "MixedTopic"
    invalid.mkdir(parents=True)
    (invalid / "index.md").write_text(SEARCH_DOCUMENT, encoding="utf-8")

    public_documents = list(iter_public_documents(docs, taxonomy))
    catalog = build_topic_catalog(docs, taxonomy, documents=public_documents)
    pages = build_index_pages(catalog.documents, taxonomy, catalog=catalog)

    assert public_documents == []
    assert catalog.documents == ()
    assert "AKS 네트워크 진단" not in pages[PurePosixPath("articles/index.md")]


def test_on_post_page_injects_head_redirect_tags_when_theme_canonical_is_missing(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    taxonomy = {
        "collections": {"guide": {"path": "guides", "title": "구현 가이드"}},
        "services": {"aks": "Azure Kubernetes Service"},
        "technologies": {"kubernetes": "Kubernetes"},
        "tags": {"networking": "Networking"},
        "verification_statuses": ["verified", "needs-review"],
        "official_source_hosts": ["learn.microsoft.com"],
        "required_source_host": "learn.microsoft.com",
    }
    (tmp_path / "docs-taxonomy.yml").write_text(
        yaml.safe_dump(taxonomy, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    canonical = docs / "services" / "aks" / "network-diagnosis"
    canonical.mkdir(parents=True)
    (canonical / "index.md").write_text(
        SEARCH_DOCUMENT.replace(
            "last_verified: 2026-09-12",
            "redirect_from: [guides/aks/old-topic/index.md]\nlast_verified: 2026-09-12",
        ),
        encoding="utf-8",
    )
    page = SimpleNamespace(file=SimpleNamespace(src_uri="guides/aks/old-topic/index.md"))

    rendered = on_post_page("<html><head></head><body></body></html>", page, {"docs_dir": str(docs)})

    assert '<link rel="canonical" href="../../../services/aks/network-diagnosis/">' in rendered
    assert '<meta http-equiv="refresh" content="0; url=../../../services/aks/network-diagnosis/">' in rendered


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
    page = tmp_path / "docs" / "services" / "aks" / "network-diagnosis"
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
        "# Home\n\n<!-- home:stats -->\n\n<!-- home:featured -->\n\n<!-- home:browse -->\n",
        encoding="utf-8",
    )
    nav_path = docs / ".nav.yml"
    nav_path.write_text(
        "nav:\n  - Home: index.md\n  - Services: services\n  - Tags: tags\n"
        "  - Articles: articles\n  - glob: '*'\n    ignore_no_matches: true\n",
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
                {"tags": {"tags": False, "listings": False}},
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

    assert single_document_navigation.links["services/aks/network-diagnosis/"] == "AKS 네트워크 진단"
    assert single_document_navigation.links["services/aks/"] == "Azure Kubernetes Service"

    page = docs / "services" / "aks" / "new-topic" / "index.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        SEARCH_DOCUMENT.replace("AKS 네트워크 진단", "자동 게시 확인")
        + "\n추가된 문서의 검색 본문입니다.\n",
        encoding="utf-8",
    )
    third_page = docs / "services" / "aks" / "z-last-topic" / "index.md"
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
    assert navigation.links["services/aks/network-diagnosis/"] == "AKS 네트워크 진단"
    assert navigation.links["services/aks/new-topic/"] == "자동 게시 확인"
    assert navigation.links["services/aks/z-last-topic/"] == "세 번째 문서"
    assert navigation.links["services/aks/"] == "Azure Kubernetes Service"
    assert "guides/" not in navigation.links
    assert navigation.links["articles/"] == "Articles"
    assert "자동 게시 확인" in (root / "site" / "guides" / "index.html").read_text(encoding="utf-8")
    assert any(
        entry["location"] == "services/aks/new-topic/"
        and "추가된 문서" in entry["text"]
        for entry in search["docs"]
    )
    article_navigation = PrimaryNavigation()
    article_navigation.feed(
        (root / "site" / "services" / "aks" / "network-diagnosis" / "index.html").read_text(
            encoding="utf-8"
        )
    )
    article_url = "https://example.test/services/aks/network-diagnosis/"
    resolved_links = {
        urljoin(article_url, target): title
        for target, title in article_navigation.links.items()
    }
    assert resolved_links[article_url] == "AKS 네트워크 진단"
    assert resolved_links["https://example.test/services/aks/"] == "Azure Kubernetes Service"
    assert resolved_links["https://example.test/services/aks/new-topic/"] == "자동 게시 확인"
    assert resolved_links["https://example.test/services/aks/z-last-topic/"] == "세 번째 문서"


def make_published_repository(tmp_path: Path) -> tuple[Path, Path, dict[str, bytes]]:
    root = make_topic_repository(tmp_path)
    sample = root / "docs/services/aks/network-diagnosis/samples/event-lab"
    payloads = {
        "diagram.svg": b'<svg xmlns="http://www.w3.org/2000/svg"><text>asset-only-marker</text></svg>\r\n',
        "payload.bin": bytes(range(256)),
        "report.txt": b"\xef\xbb\xbfasset-only-marker\r\nplain text\r\n",
        "notes.md": b"# asset-only-marker\r\n\r\nThis is an asset, not a page.\r\n",
    }
    manifest_path = sample / "sample.yml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["publish"] = []
    for name, payload in payloads.items():
        (sample / name).write_bytes(payload)
        manifest["publish"].append({"source": name, "target": f"setup/images/{name}"})
    # One canonical source can serve a second page without making a physical copy.
    manifest["publish"].append({"source": "diagram.svg", "target": "images/diagram.svg"})
    manifest_path.write_text(yaml.safe_dump(manifest))
    (sample / "unpublished.txt").write_text("unpublished-marker")
    return root, sample, payloads


def test_published_assets_build_byte_exact_without_sample_or_search_pages(tmp_path: Path) -> None:
    root, sample, payloads = make_published_repository(tmp_path)
    page = sample.parent.parent / "setup/index.md"
    page.write_text(
        page.read_text()
        + "\n![Published diagram](images/diagram.svg)\n"
        + "\n".join(f"[Download {name}](images/{name})" for name in payloads)
        + "\n",
        encoding="utf-8",
    )

    build(load_config(str(root / "mkdocs.yml"), strict=True))

    site_topic = root / "site/services/aks/network-diagnosis"
    for name, payload in payloads.items():
        assert (site_topic / "setup/images" / name).read_bytes() == payload
        assert (sample / name).read_bytes() == payload
        assert not (sample.parent.parent / "setup/images" / name).exists()
    assert (site_topic / "images/diagram.svg").read_bytes() == payloads["diagram.svg"]
    assert not (site_topic / "samples").exists()
    rendered = (site_topic / "setup/index.html").read_text()
    assert 'src="images/diagram.svg"' in rendered
    assert 'href="images/notes.md"' in rendered
    assert "unpublished-marker" not in rendered
    search = json.loads((root / "site/search/search_index.json").read_text())
    assert all(
        "/samples/" not in entry["location"] and "/images/" not in entry["location"]
        and "asset-only-marker" not in entry["text"] and "unpublished-marker" not in entry["text"]
        for entry in search["docs"]
    )
    assert any(
        entry["location"].startswith("services/aks/network-diagnosis/setup/")
        and "Download diagram.svg" in entry["text"]
        for entry in search["docs"]
    )
    assert validate_search_index.validate_repository(root).errors == []


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("report.txt", "downloads/.env.example"),
        ("notes.md", ".notes.md"),
        ("payload.bin", ".artifacts/payload.bin"),
        ("notes.md", "downloads/.private/notes.md"),
    ],
)
def test_hidden_published_assets_build_byte_exact_without_exposing_sample_sources(
    tmp_path: Path, source: str, target: str
) -> None:
    root, sample, payloads = make_published_repository(tmp_path)
    manifest_path = sample / "sample.yml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["publish"].append({"source": source, "target": target})
    manifest_path.write_text(yaml.safe_dump(manifest))
    (sample / ".unpublished.txt").write_bytes(b"unpublished sample")
    (sample.parent.parent / ".unpublished.txt").write_bytes(b"unpublished page asset")

    build(load_config(str(root / "mkdocs.yml"), strict=True))

    site_topic = root / "site/services/aks/network-diagnosis"
    published = site_topic / target
    assert published.is_file(), f"declared hidden target was excluded: {target}"
    assert published.read_bytes() == payloads[source]
    assert (sample / source).read_bytes() == payloads[source]
    assert not (site_topic / "samples").exists()
    assert not (site_topic / ".unpublished.txt").exists()
    search = json.loads((root / "site/search/search_index.json").read_text())
    assert all(
        target not in entry["location"] and "/samples/" not in entry["location"]
        and "asset-only-marker" not in entry["text"]
        for entry in search["docs"]
    )


@pytest.mark.parametrize("operation", ["read", "open", "write"])
def test_published_asset_io_failures_report_source_and_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from mkdocs_gen_files.editor import FilesEditor

    root, sample, _ = make_published_repository(tmp_path)
    source = sample / "diagram.svg"
    target = "services/aks/network-diagnosis/setup/images/diagram.svg"
    original_read = Path.read_bytes
    original_open = FilesEditor.open

    def read_bytes(path: Path) -> bytes:
        if path == source:
            raise OSError("injected read failure")
        return original_read(path)

    class BrokenWriter:
        def write(self, content: bytes) -> None:
            raise OSError("injected write failure")

    @contextmanager
    def open_generated(editor, path: str, mode: str = "r", **kwargs):
        if str(path) == target and mode == "wb":
            if operation == "open":
                raise OSError("injected open failure")
            yield BrokenWriter()
        else:
            with original_open(editor, path, mode, **kwargs) as stream:
                yield stream

    if operation == "read":
        monkeypatch.setattr(Path, "read_bytes", read_bytes)
    else:
        monkeypatch.setattr(FilesEditor, "open", open_generated)
    config = load_config(str(root / "mkdocs.yml"))
    with FilesEditor(Files([]), config, str(root / "generated")):
        with pytest.raises(DocumentFormatError, match="cannot publish asset") as error:
            write_generated_pages(root)
    assert source.relative_to(root / "docs").as_posix() in str(error.value)
    assert target in str(error.value)
    assert f"injected {operation} failure" in str(error.value)


def test_topic_packages_drive_sidebar_navigation_redirects_and_bounded_topic_links(
    tmp_path: Path,
) -> None:
    root = make_topic_repository(tmp_path)
    build(load_config(str(root / "mkdocs.yml"), strict=True))

    home = TopicReaderPage(root / "site" / "index.html")
    sidebar_documents = [
        entry
        for entry in home.navigation_entries
        if entry[0].startswith("services/aks/")
    ]
    assert ("services/aks/network-diagnosis/", "Topic title", ("services/", "services/aks/")) in sidebar_documents
    assert (
        "services/aks/network-diagnosis/setup/",
        "1. Setup child",
        ("services/", "services/aks/", "services/aks/network-diagnosis/"),
    ) in sidebar_documents
    assert (
        "services/aks/network-diagnosis/results/",
        "2. Results child",
        ("services/", "services/aks/", "services/aks/network-diagnosis/"),
    ) in sidebar_documents
    assert ("services/aks/standalone-topic/", "Standalone topic", ("services/", "services/aks/")) in sidebar_documents
    assert all("old-topic" not in target for target, _, _ in sidebar_documents)

    entry_page = TopicReaderPage(root / "site" / "services" / "aks" / "network-diagnosis" / "index.html")
    assert entry_page.topic_nav_links == [("setup/", "다음 문서")]

    middle_page = TopicReaderPage(
        root / "site" / "services" / "aks" / "network-diagnosis" / "setup" / "index.html"
    )
    assert middle_page.expanded_groups == 3
    assert middle_page.topic_nav_links == [("../", "이전 문서"), ("../results/", "다음 문서")]

    final_page = TopicReaderPage(
        root / "site" / "services" / "aks" / "network-diagnosis" / "results" / "index.html"
    )
    assert final_page.topic_nav_links == [("../setup/", "이전 문서")]

    redirect_page_path = root / "site" / "guides" / "aks" / "old-topic" / "index.html"
    redirect_page = redirect_page_path.read_text(encoding="utf-8")
    assert "services/aks/network-diagnosis/" in redirect_page
    assert '<link rel="canonical" href="../../../services/aks/network-diagnosis/">' in redirect_page
    assert '<meta http-equiv="refresh" content="0; url=../../../services/aks/network-diagnosis/">' in redirect_page
    search = json.loads((root / "site" / "search" / "search_index.json").read_text(encoding="utf-8"))
    locations = {entry["location"] for entry in search["docs"]}
    assert "guides/aks/old-topic/" not in locations
    assert not any("/samples/" in location for location in locations)
    assert not any("Event lab" in entry.get("text", "") for entry in search["docs"])
    assert not (root / "site" / "services" / "aks" / "network-diagnosis" / "samples").exists()


def write_search_index(root: Path, documents: list[dict[str, str]]) -> None:
    (root / "site" / "search" / "search_index.json").write_text(
        json.dumps({"config": {}, "docs": documents}, ensure_ascii=False),
        encoding="utf-8",
    )


def page_search_entry(text: str) -> dict[str, str]:
    return {
        "location": "services/aks/network-diagnosis/",
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
                "location": "tags/networking/",
                "title": "networking",
                "text": "AKS 네트워크 진단",
            },
            {
                "location": "tags/troubleshooting/",
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


def test_search_gate_requires_tag_destinations_not_just_overview_anchors(tmp_path: Path) -> None:
    root = make_search_repository(tmp_path)
    write_search_index(
        root,
        [
            page_search_entry(
                "<p>네트워크 연결 문제를 확인합니다. "
                "Azure Kubernetes Service diagnostic workflow를 설명합니다.</p>"
            ),
        ]
        + [
            {"location": f"tags/#tag:{tag}", "title": tag, "text": "AKS 네트워크 진단"}
            for tag in ("networking", "troubleshooting")
        ],
    )

    result = validate_search_index.validate_repository(root)

    assert any("tag is missing: networking" in error for error in result.errors)
    assert any("tag is missing: troubleshooting" in error for error in result.errors)


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
    path = root / "docs" / "services" / "aks" / "network-diagnosis" / "index.md"
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
        url="services/aks/network-diagnosis/",
    )
    index = SearchIndex()
    index.add_entry_from_context(page)
    write_search_index(
        root,
        index.entries
        + [
            {
                "location": f"tags/{tag}/",
                "title": tag,
                "text": page.title,
            }
            for tag in document.metadata["tags"]
        ],
    )

    result = validate_search_index.validate_repository(root)

    assert result.errors == []
