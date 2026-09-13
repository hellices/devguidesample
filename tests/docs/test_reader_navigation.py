from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from urllib.parse import urljoin

from markdown import Markdown
from mkdocs.commands.build import build
from mkdocs.config import load_config
import pytest
import yaml

from scripts.docs.content import Document
from scripts.docs.generate_indexes import build_home_page, build_index_pages
from scripts.docs.hooks import on_page_markdown
from scripts.docs.topics import build_topic_catalog


@pytest.fixture
def taxonomy() -> dict:
    return {
        "collections": {
            "guide": {"path": "guides", "title": "구현 가이드"},
            "research": {"path": "research", "title": "비교·분석"},
        },
        "services": {"azure-monitor": "Azure Monitor", "azure-storage": "Azure Storage"},
        "tags": {"networking": "Networking", "monitoring": "Monitoring", "latency": "Latency"},
    }


def document(collection: str, topic: str, title: str, tags: list[str]) -> Document:
    relative_path = PurePosixPath(collection) / "azure-monitor" / topic / "index.md"
    return Document(
        path=Path(relative_path),
        relative_path=relative_path,
        metadata={
            "title": title,
            "description": f"{title} 설명",
            "document_type": "guide" if collection == "guides" else "research",
            "services": ["azure-monitor", "azure-storage"],
            "tags": tags,
        },
        body="networking이라는 단어를 본문에서 사용합니다.",
    )


def write_topic_document(
    docs_dir: Path,
    relative_path: str,
    title: str,
    *,
    tags: list[str],
    topic_order: int | None = None,
) -> None:
    metadata: dict[str, object] = {
        "title": title,
        "description": f"{title} 설명",
        "document_type": "guide",
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

    path = docs_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n\n"
        + f"# {title}\n\n본문입니다.\n",
        encoding="utf-8",
    )


def build_topic_fixture(tmp_path: Path, taxonomy: dict) -> tuple[Path, object]:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (tmp_path / "docs-taxonomy.yml").write_text(
        yaml.safe_dump(taxonomy, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    write_topic_document(
        docs_dir,
        "services/azure-monitor/new-topic/index.md",
        "Topic title",
        tags=["networking"],
    )
    write_topic_document(
        docs_dir,
        "services/azure-monitor/new-topic/setup/index.md",
        "Setup child",
        tags=["networking"],
        topic_order=1,
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
    )

    sample_dir = docs_dir / "services" / "azure-monitor" / "new-topic" / "samples" / "event-lab"
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

    return docs_dir, build_topic_catalog(docs_dir, taxonomy, include_legacy=False)


def page_namespace(document: Document, *, previous: Document | None = None, next_: Document | None = None):
    def nav_item(item: Document | None):
        if item is None:
            return None
        return SimpleNamespace(
            title=item.metadata["title"],
            url=item.relative_path.as_posix().removesuffix("index.md"),
        )

    return SimpleNamespace(
        title=document.metadata["title"],
        meta=document.metadata,
        file=SimpleNamespace(src_uri=str(document.relative_path)),
        url=document.relative_path.as_posix().removesuffix("index.md"),
        previous_page=nav_item(previous),
        next_page=nav_item(next_),
    )


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.targets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        target = dict(attrs).get("href")
        if tag == "a" and isinstance(target, str):
            self.targets.append(target)


def targets(markdown: str) -> list[str]:
    renderer = Markdown(extensions=["md_in_html", "attr_list"])
    body = markdown.split("---", 2)[2] if markdown.startswith("---") else markdown
    parser = Links()
    parser.feed(renderer.convert(body))
    return parser.targets


@pytest.mark.parametrize("path", ["articles/index.md", "services/azure-monitor/index.md", "tags/networking.md"])
def test_reader_lists_mix_lifecycles_without_type_badges(taxonomy: dict, path: str) -> None:
    documents = [
        document("guides", "setup", "B 구성 절차", ["networking"]),
        document("research", "choices", "A 선택 근거", ["networking"]),
    ]

    page = build_index_pages(documents, taxonomy)[PurePosixPath(path)]

    assert page.count('class="dg-doc-card') == 2
    assert page.index("A 선택 근거") < page.index("B 구성 절차")
    assert "구현 가이드" not in page
    assert "비교·분석" not in page
    assert "Azure Monitor" in page
    assert "Azure Storage" in page


def test_tag_overview_counts_unique_documents_and_only_used_tags(taxonomy: dict) -> None:
    documents = [
        document("guides", "setup", "구성 절차", ["networking", "networking"]),
        document("research", "choices", "선택 근거", ["networking", "monitoring"]),
    ]
    pages = build_index_pages(documents, taxonomy)
    overview = pages[PurePosixPath("tags/index.md")]

    assert "networking.md" in targets(overview)
    assert "monitoring.md" in targets(overview)
    assert "latency.md" not in targets(overview)
    assert PurePosixPath("tags/latency.md") not in pages
    assert "2개 문서" in overview
    assert "1개 문서" in overview
    assert "구성 절차" not in overview
    assert "tag:networking" in overview
    assert "?q=" not in overview
    assert pages[PurePosixPath("tags/networking.md")].count('class="dg-doc-card') == 2


def test_tag_results_require_exact_membership_not_body_or_slug_prefix(taxonomy: dict) -> None:
    taxonomy["tags"]["networking-advanced"] = "Advanced networking"
    matching = document("guides", "setup", "태그 일치 문서", ["networking"])
    mentioning = document("research", "mentions", "본문에만 등장", ["monitoring"])
    prefix = document("research", "prefix", "접두사만 일치", ["networking-advanced"])

    page = build_index_pages([matching, mentioning, prefix], taxonomy)[
        PurePosixPath("tags/networking.md")
    ]

    assert "태그 일치 문서" in page
    assert "본문에만 등장" not in page
    assert "접두사만 일치" not in page
    assert "../guides/azure-monitor/setup/index.md" in targets(page)
    assert "index.md" in targets(page)


def test_service_lists_deduplicate_repeated_service_values(taxonomy: dict) -> None:
    matching = document("guides", "setup", "구성 절차", ["networking"])
    matching.metadata["services"] = ["azure-monitor", "azure-monitor", "azure-storage"]

    pages = build_index_pages([matching], taxonomy)

    assert pages[PurePosixPath("services/azure-monitor/index.md")].count('class="dg-doc-card') == 1
    assert pages[PurePosixPath("services/azure-storage/index.md")].count('class="dg-doc-card') == 1


def test_card_tags_link_to_detail_pages_at_each_directory_depth(taxonomy: dict) -> None:
    matching = document("guides", "setup", "구성 절차", ["networking"])
    pages = build_index_pages([matching], taxonomy)

    assert "../tags/networking.md" in targets(pages[PurePosixPath("articles/index.md")])
    assert "../../tags/networking.md" in targets(pages[PurePosixPath("services/azure-monitor/index.md")])
    assert "networking.md" in targets(pages[PurePosixPath("tags/networking.md")])
    assert "../../tags/networking.md" in targets(pages[PurePosixPath("guides/azure-monitor/index.md")])


def test_tag_labels_are_escaped_without_changing_slug_destinations(taxonomy: dict) -> None:
    taxonomy["tags"]["networking"] = 'Network [links] <script>alert("x")</script>'
    matching = document("guides", "setup", "구성 절차", ["networking"])
    pages = build_index_pages([matching], taxonomy)

    for path in ("tags/index.md", "tags/networking.md", "articles/index.md"):
        body = pages[PurePosixPath(path)].split("---", 2)[2]
        rendered = Markdown(extensions=["md_in_html", "attr_list"]).convert(body)
        assert "<script>" not in rendered
        assert "networking.md" in " ".join(targets(pages[PurePosixPath(path)]))


def test_empty_reader_indexes_do_not_invent_tags_or_documents(taxonomy: dict) -> None:
    pages = build_index_pages([], taxonomy)

    for path in ("articles/index.md", "tags/index.md"):
        page = pages[PurePosixPath(path)]
        assert "dg-empty-state" in page
        assert 'class="dg-doc-card' not in page
    assert not any(path.parent == PurePosixPath("tags") and path.name != "index.md" for path in pages)


def test_reader_cards_keep_real_scope_without_review_placeholders(taxonomy: dict) -> None:
    matching = document("guides", "setup", "구성 절차", ["networking"])
    matching.metadata["applies_to"] = ["공식 원문 재검토 필요", "검증용 테스트 환경"]

    page = build_index_pages([matching], taxonomy)[PurePosixPath("articles/index.md")]

    assert "공식 원문 재검토 필요" not in page
    assert "검증용 테스트 환경" in page
    assert matching.metadata["applies_to"] == ["공식 원문 재검토 필요", "검증용 테스트 환경"]


def test_home_offers_browse_destinations_instead_of_lifecycles(taxonomy: dict) -> None:
    template = "# Home\n\n<!-- home:stats -->\n\n<!-- home:featured -->\n\n<!-- home:browse -->\n"
    matching = document("guides", "setup", "구성 절차", ["networking"])

    page = build_home_page(template, [matching], taxonomy)

    assert {"services/index.md", "tags/index.md", "articles/index.md"} <= set(targets(page))
    assert "guides/index.md" not in targets(page)
    assert "research/index.md" not in targets(page)
    assert "문서 유형" not in page
    assert "구현 가이드" not in page
    assert "비교·분석" not in page


def test_article_tags_use_the_same_detail_pages(tmp_path: Path, taxonomy: dict) -> None:
    (tmp_path / "docs-taxonomy.yml").write_text(yaml.safe_dump(taxonomy), encoding="utf-8")
    matching = document("guides", "setup", "구성 절차", ["networking"])
    page = SimpleNamespace(meta=matching.metadata, file=SimpleNamespace(src_uri=str(matching.relative_path)))

    rendered = on_page_markdown(
        "# 구성 절차\n\n본문입니다.\n",
        page,
        {"docs_dir": str(tmp_path / "docs")},
        None,
    )

    assert "../../../tags/networking.md" in targets(rendered)
    assert "?q=" not in rendered
    assert "본문입니다." in rendered


def test_topic_pages_render_context_outline_and_related_samples(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir, catalog = build_topic_fixture(tmp_path, taxonomy)
    entry = next(
        document
        for document in catalog.documents
        if document.relative_path == PurePosixPath("services/azure-monitor/new-topic/index.md")
    )
    setup = next(
        document
        for document in catalog.documents
        if document.relative_path == PurePosixPath("services/azure-monitor/new-topic/setup/index.md")
    )
    results = next(
        document
        for document in catalog.documents
        if document.relative_path == PurePosixPath("services/azure-monitor/new-topic/results/index.md")
    )
    standalone = next(
        document
        for document in catalog.documents
        if document.relative_path
        == PurePosixPath("services/azure-monitor/standalone-topic/index.md")
    )
    config = {
        "docs_dir": str(docs_dir),
        "repo_url": "https://github.com/example/devguidesample",
    }

    entry_rendered = on_page_markdown(
        "# Topic title\n\n본문입니다.\n",
        page_namespace(entry, next_=setup),
        config,
        None,
    )
    setup_rendered = on_page_markdown(
        "# Setup child\n\n본문입니다.\n",
        page_namespace(setup, previous=entry, next_=results),
        config,
        None,
    )
    results_rendered = on_page_markdown(
        "# Results child\n\n본문입니다.\n",
        page_namespace(results, previous=setup),
        config,
        None,
    )
    standalone_rendered = on_page_markdown(
        "# Standalone topic\n\n본문입니다.\n",
        page_namespace(standalone),
        config,
        None,
    )

    assert 'class="dg-topic-overview"' in entry_rendered
    assert "TOPIC · 3 DOCUMENTS" in entry_rendered
    assert "Topic title · 1 / 3" in entry_rendered
    assert entry_rendered.count("Setup child") == 1
    assert entry_rendered.count("Results child") == 1
    assert entry_rendered.index("Setup child") < entry_rendered.index("Results child")

    assert 'class="dg-topic-context"' in setup_rendered
    assert "Topic title · 2 / 3" in setup_rendered
    assert ">전체 목차<" in setup_rendered
    assert 'class="dg-topic-nav"' in setup_rendered
    assert setup_rendered.index("본문입니다.") < setup_rendered.index('class="dg-topic-nav"')
    assert 'class="dg-sample-card"' in setup_rendered
    assert "Event lab" in setup_rendered
    assert (
        "https://github.com/example/devguidesample/tree/main/"
        "docs/services/azure-monitor/new-topic/samples/event-lab"
    ) in setup_rendered
    assert setup_rendered.index('class="dg-sample-card"') < setup_rendered.index(
        'class="doc-sources"'
    )

    assert "Topic title · 3 / 3" in results_rendered
    assert 'class="dg-topic-nav"' in results_rendered
    assert 'class="dg-sample-card"' not in results_rendered
    assert 'class="dg-sample-card"' not in standalone_rendered


def test_legacy_same_slug_pages_do_not_get_canonical_topic_ui(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (tmp_path / "docs-taxonomy.yml").write_text(
        yaml.safe_dump(taxonomy, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    write_topic_document(
        docs_dir,
        "guides/azure-monitor/shared/index.md",
        "Guide title",
        tags=["networking"],
    )
    write_topic_document(
        docs_dir,
        "research/azure-monitor/shared/index.md",
        "Research title",
        tags=["networking"],
    )
    research_path = docs_dir / "research" / "azure-monitor" / "shared" / "index.md"
    research_path.write_text(
        research_path.read_text(encoding="utf-8").replace("document_type: guide", "document_type: research"),
        encoding="utf-8",
    )
    guide = document("guides", "shared", "Guide title", ["networking"])
    catalog = build_topic_catalog(docs_dir, taxonomy)

    rendered = on_page_markdown(
        "# Guide title\n\n본문입니다.\n",
        page_namespace(guide),
        {"docs_dir": str(docs_dir)},
        None,
    )

    assert catalog.by_document[guide.relative_path].entry.relative_path == guide.relative_path
    assert 'class="dg-topic-overview"' not in rendered
    assert 'class="dg-topic-context"' not in rendered
    assert 'class="dg-topic-nav"' not in rendered


class ReaderPage(HTMLParser):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.navigation_depth = 0
        self.card_depth = 0
        self.navigation_links: dict[str, str] = {}
        self.navigation_entries: list[tuple[str, str, tuple[str, ...]]] = []
        self.navigation_parents: list[str | None] = []
        self.last_navigation_target: str | None = None
        self.root_links: dict[str, str] = {}
        self.card_entries: list[tuple[str, str]] = []
        self.tag_links: set[str] = set()
        self.expanded_groups = 0
        self.active_links: list[str] = []
        self.current_link: tuple[str, bool, bool, bool] | None = None
        self.link_text: list[str] = []
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "nav" and (self.navigation_depth or "md-nav--primary" in classes):
            self.navigation_depth += 1
            self.navigation_parents.append(self.last_navigation_target)
        if tag == "article" and (self.card_depth or "dg-doc-card" in classes):
            self.card_depth += 1
        if self.navigation_depth and tag == "input" and "md-nav__toggle" in classes:
            self.expanded_groups += "checked" in attributes
        target = attributes.get("href")
        if tag != "a" or not isinstance(target, str):
            return
        if "dg-tag" in classes:
            self.tag_links.add(target)
        if self.navigation_depth and "md-nav__link--active" in classes:
            self.active_links.append(target)
        self.current_link = (
            target,
            bool(self.navigation_depth),
            self.navigation_depth == 1 and "md-nav__link" in classes,
            bool(self.card_depth) and not {"dg-tag", "headerlink"}.intersection(classes),
        )
        self.link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_link is not None:
            target, navigation, root, card = self.current_link
            title = " ".join("".join(self.link_text).split())
            if navigation:
                self.navigation_links[target] = title
                parents = tuple(parent for parent in self.navigation_parents if parent is not None)
                self.navigation_entries.append((target, title, parents))
                self.last_navigation_target = target
            if root:
                self.root_links[target] = title
            if card:
                self.card_entries.append((target, title))
            self.current_link = None
        if tag == "nav" and self.navigation_depth:
            self.navigation_depth -= 1
            self.navigation_parents.pop()
        if tag == "article" and self.card_depth:
            self.card_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.current_link is not None:
            self.link_text.append(data)


def test_each_new_bundle_updates_all_reader_destinations(
    tmp_path: Path, taxonomy: dict
) -> None:
    root = Path(__file__).parents[2]
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text(
        (root / "docs/index.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (docs / "contributing").mkdir()
    (docs / "contributing/index.md").write_text("# 기여하기\n", encoding="utf-8")
    navigation_path = docs / ".nav.yml"
    navigation_path.write_text(
        (root / "docs/.nav.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    taxonomy_path = tmp_path / "docs-taxonomy.yml"
    taxonomy_path.write_text(yaml.safe_dump(taxonomy), encoding="utf-8")
    generator = tmp_path / "generate.py"
    generator.write_text(
        "from pathlib import Path\n"
        "from scripts.docs.generate_indexes import write_generated_pages\n"
        f"write_generated_pages(Path({str(tmp_path)!r}))\n",
        encoding="utf-8",
    )
    settings = yaml.safe_load((root / "mkdocs.yml").read_text(encoding="utf-8"))
    settings.update(
        {
            "site_name": "Azure Engineering Notes",
            "hooks": [str(root / "scripts/docs/hooks.py")],
            "plugins": [
                {"search": {"lang": ["ko", "en"]}},
                {"tags": {"tags": False, "listings": False}},
                {"gen-files": {"scripts": [str(generator)]}},
                "awesome-nav",
            ],
            "extra_css": [],
        }
    )
    settings_path = tmp_path / "mkdocs.yml"
    settings_path.write_text(yaml.safe_dump(settings), encoding="utf-8")

    def add_bundle(item: Document) -> Path:
        path = docs / item.relative_path
        path.parent.mkdir(parents=True)
        path.write_text(
            "---\n" + yaml.safe_dump(item.metadata, allow_unicode=True)
            + f"---\n\n# {item.metadata['title']}\n\n{item.body}\n",
            encoding="utf-8",
        )
        return path

    original = add_bundle(document("guides", "setup", "B 구성 절차", ["networking"]))
    unchanged = [settings_path, navigation_path, taxonomy_path, docs / "index.md", original]
    original_bytes = [path.read_bytes() for path in unchanged]
    build(load_config(str(settings_path), strict=True))
    home = ReaderPage(tmp_path / "site/index.html")

    assert list(home.root_links.values()) == ["홈", "서비스별 보기", "태그별 보기", "전체 글", "기여하기"]
    assert home.navigation_links["services/azure-monitor/"] == "Azure Monitor"
    assert home.navigation_links["guides/azure-monitor/setup/"] == "B 구성 절차"
    assert home.expanded_groups == 0
    assert not (tmp_path / "site/tags/latency/index.html").exists()

    add_bundle(document("research", "choices", "A 선택 근거", ["networking", "latency"]))
    build(load_config(str(settings_path), strict=True))

    assert [path.read_bytes() for path in unchanged] == original_bytes
    for destination in ("articles", "services/azure-monitor", "services/azure-storage", "tags/networking"):
        page = ReaderPage(tmp_path / "site" / destination / "index.html")
        assert [title for target, title in page.card_entries] == ["A 선택 근거", "B 구성 절차"]
    new_tag = ReaderPage(tmp_path / "site/tags/latency/index.html")
    assert [title for target, title in new_tag.card_entries] == ["A 선택 근거"]
    updated_home = ReaderPage(tmp_path / "site/index.html")
    assert updated_home.navigation_links["research/azure-monitor/choices/"] == "A 선택 근거"
    sidebar_documents = [
        entry for entry in updated_home.navigation_entries
        if entry[0].startswith(("guides/", "research/"))
    ]
    primary_service = ("services/", "services/azure-monitor/")
    assert sidebar_documents == [
        ("research/azure-monitor/choices/", "A 선택 근거", primary_service),
        ("guides/azure-monitor/setup/", "B 구성 절차", primary_service),
    ]

    add_bundle(document("guides", "mentions", "C 본문만 일치", ["monitoring"]))
    build(load_config(str(settings_path), strict=True))

    assert [path.read_bytes() for path in unchanged] == original_bytes
    expected_titles = {"A 선택 근거", "B 구성 절차", "C 본문만 일치"}
    for destination in ("articles", "services/azure-monitor", "services/azure-storage"):
        page = ReaderPage(tmp_path / "site" / destination / "index.html")
        assert [title for target, title in page.card_entries] == sorted(expected_titles)

    final_home = ReaderPage(tmp_path / "site/index.html")
    assert [
        entry for entry in final_home.navigation_entries
        if entry[0].startswith(("guides/", "research/"))
    ] == [
        ("research/azure-monitor/choices/", "A 선택 근거", primary_service),
        ("guides/azure-monitor/setup/", "B 구성 절차", primary_service),
        ("guides/azure-monitor/mentions/", "C 본문만 일치", primary_service),
    ]

    tag = ReaderPage(tmp_path / "site/tags/networking/index.html")
    assert [title for target, title in tag.card_entries] == ["A 선택 근거", "B 구성 절차"]
    assert tag.expanded_groups == 1
    assert (tmp_path / "site/tags/latency/index.html").is_file()
    assert (tmp_path / "site/guides/azure-monitor/index.html").is_file()
    assert (tmp_path / "site/research/index.html").is_file()

    article = ReaderPage(tmp_path / "site/guides/azure-monitor/setup/index.html")
    article_url = "https://example.test/devguidesample/guides/azure-monitor/setup/"
    assert {urljoin(article_url, target) for target in article.tag_links} == {
        "https://example.test/devguidesample/tags/networking/"
    }
    assert {urljoin(article_url, target) for target in article.active_links} == {article_url}
    assert article.expanded_groups == 2
    assert set(article.navigation_links.values()) >= expected_titles
    assert "구현 가이드" not in article.navigation_links.values()
    assert "비교·분석" not in article.navigation_links.values()
    assert all("?q=" not in target for target in article.tag_links)

    search = json.loads((tmp_path / "site/search/search_index.json").read_text(encoding="utf-8"))
    locations = {entry["location"] for entry in search["docs"]}
    assert {"tags/networking/", "tags/latency/", "articles/", "research/azure-monitor/choices/"} <= locations
