from collections import Counter
from copy import deepcopy
from html.parser import HTMLParser
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from types import SimpleNamespace
from urllib.parse import parse_qs, urljoin, urlsplit

from markdown import Markdown
import pytest
import yaml
import material

from scripts.docs import content
from scripts.docs.generate_indexes import build_home_page, build_index_pages
from scripts.docs.hooks import on_page_markdown, on_post_page
from scripts.docs.topics import build_topic_catalog


ROOT = Path(__file__).parents[2]
GOALS = dict(zip(
    "design build deploy diagnose optimize operate secure evaluate migrate".split(),
    "설계 구현 배포 진단 최적화 운영 보안 비교·검증 마이그레이션".split(),
))
SUBJECTS = {"ai-agents": "AI agents", "networking": "네트워킹", "identity": "ID·권한", "storage": "스토리지"}
LEGACY = {
    "ai-agents": {"tag": ["ai-agents"]}, "architecture": {"tag": ["design"]},
    "authentication": {"tag": ["identity", "secure"]}, "authorization": {"tag": ["identity", "secure"]},
    "benchmarking": {"tag": ["evaluate"]}, "deployment": {"tag": ["deploy"]},
    "development": {"tag": ["build"]}, "diagnostics": {"tag": ["diagnose"]},
    "troubleshooting": {"tag": ["diagnose"]}, "disaster-recovery": {"tag": ["operate"]},
    "high-availability": {"tag": ["operate"]}, "monitoring": {"tag": ["operate"]},
    "observability": {"tag": ["operate"]}, "reliability": {"tag": ["operate"]},
    "kubernetes": {"technology": ["kubernetes"]}, "latency": {"tag": ["optimize"]},
    "performance": {"tag": ["optimize"]}, "migration": {"tag": ["migrate"]},
    "networking": {"tag": ["networking"]}, "security": {"tag": ["secure"]},
    "storage": {"tag": ["storage"]},
}
REFINEMENTS = {
    "microsoft-foundry/agent-memory": {
        "index": "design ai-agents", "taxonomy": "design ai-agents",
        "architecture-patterns": "design ai-agents",
        "pipeline-retrieval": "build optimize ai-agents", "frameworks": "evaluate ai-agents",
        "production-evaluation": "operate evaluate ai-agents", "commerce": "design build ai-agents",
    },
    "azure-monitor/azure-sre-agent": {
        "index": "operate diagnose ai-agents", "event-lab": "diagnose evaluate ai-agents",
        "setup": "deploy operate ai-agents", "scenario-http-500": "diagnose operate ai-agents",
        "scenario-latency": "optimize operate ai-agents",
        "scenario-blob-permission": "secure operate identity ai-agents",
        "results": "evaluate diagnose ai-agents", "validation-results": "evaluate operate ai-agents",
        "incident-runbook": "diagnose operate ai-agents", "dynamic-thresholds": "operate design ai-agents",
    },
    "azure-ai-search/custom-vectorization": {
        "index": "design build optimize", "rag-chunking": "design optimize evaluate",
        "custom-web-api": "build deploy", "gpu-vllm": "build deploy optimize",
        "bge-m3-vs-qwen3": "evaluate optimize", "a10-vs-t4": "evaluate optimize",
    },
    "azure-monitor/hdinsight-kafka-monitoring": {
        "index": "evaluate operate", "prometheus-grafana": "deploy operate",
        "catch-up-benchmark": "evaluate optimize",
    },
}


@pytest.fixture
def taxonomy():
    return content.load_taxonomy(ROOT / "docs-taxonomy.yml")


@pytest.fixture
def catalog(taxonomy):
    return build_topic_catalog(ROOT / "docs", taxonomy)


class Elements(HTMLParser):
    def __init__(self, markdown):
        super().__init__()
        self.elements = []
        body = markdown.split("---", 2)[2] if markdown.startswith("---") else markdown
        self.rendered = Markdown(extensions=["md_in_html", "attr_list"]).convert(body)
        self.feed(self.rendered)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def select(self, attribute):
        return [attrs for _, attrs in self.elements if attribute in attrs]


def test_repository_practical_tags_and_refinements(taxonomy, catalog):
    assert taxonomy["tags"] == GOALS | SUBJECTS
    assert taxonomy.get("tag_groups") == {
        "goal": {"label": "목적", "tags": list(GOALS)},
        "subject": {"label": "주제", "tags": list(SUBJECTS)},
    }
    assert taxonomy.get("legacy_tag_redirects") == LEGACY
    counts = Counter(tag for doc in catalog.documents for tag in doc.metadata["tags"])
    assert set(counts) == set(taxonomy["tags"])
    for doc in catalog.documents:
        tags = doc.metadata["tags"]
        assert 1 <= len(tags) <= 4
        assert len(tags) == len(set(tags))
        assert tags == [t for t in tags if t in GOALS] + [t for t in tags if t in SUBJECTS]
        assert "legacy_tags" not in doc.metadata
        parts = doc.relative_path.parts
        topic = "/".join(parts[1:3])
        child = parts[3] if len(parts) == 5 else "index"
        if topic in REFINEMENTS:
            assert tags == REFINEMENTS[topic][child].split()


@pytest.mark.parametrize("mutation,fragment", [
    (lambda t: t.pop("tag_groups"), "tag_groups"),
    (lambda t: t["tag_groups"]["goal"]["tags"].remove("build"), "missing"),
    (lambda t: t["tag_groups"]["goal"]["tags"].append("unknown"), "unknown"),
    (lambda t: t["tag_groups"]["goal"]["tags"].append("build"), "duplicate"),
    (lambda t: t["tag_groups"]["subject"]["tags"].append("build"), "duplicate"),
    (lambda t: t["tag_groups"]["goal"].update(tags="build"), "list"),
    (lambda t: t["legacy_tag_redirects"].update(bad={"tag": ["old"]}), "unknown"),
])
def test_taxonomy_validator_rejects_invalid_groups(mutation, fragment):
    taxonomy = {
        "tags": GOALS | SUBJECTS, "technologies": {"kubernetes": "Kubernetes"},
        "tag_groups": {"goal": {"label": "목적", "tags": list(GOALS)}, "subject": {"label": "주제", "tags": list(SUBJECTS)}},
        "legacy_tag_redirects": deepcopy(LEGACY),
    }
    mutation(taxonomy)
    assert hasattr(content, "validate_taxonomy"), "taxonomy validation is required"
    assert any(fragment in e for e in content.validate_taxonomy(taxonomy))


@pytest.mark.parametrize("tags", [[], ["design"] * 2, list(GOALS)[:5], ["identity", "secure"]])
def test_document_tag_contract_rejects_invalid_tags(tags, taxonomy, catalog):
    doc = catalog.documents[0]
    errors = content.validate_document(doc.with_metadata({**doc.metadata, "tags": tags}), taxonomy)
    assert any("tags" in error for error in errors), errors


def test_goal_before_subject_does_not_depend_on_yaml_mapping_order(taxonomy, catalog):
    taxonomy["tag_groups"] = dict(reversed(list(taxonomy["tag_groups"].items())))
    doc = catalog.documents[0]
    valid = doc.with_metadata({**doc.metadata, "tags": ["secure", "identity"]})
    assert content.validate_document(valid, taxonomy) == []


def test_two_home_browse_destinations_do_not_leave_a_third_grid_column():
    css = (ROOT / "docs/assets/stylesheets/extra.css").read_text()
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]+)\}", css):
        if ".dg-browse-grid" in [selector.strip() for selector in selectors.split(",")]:
            assert "repeat(3," not in body


def test_explore_has_exact_member_data_and_one_card_per_topic(taxonomy, catalog):
    pages = build_index_pages(catalog.documents, taxonomy, catalog=catalog)
    assert PurePosixPath("explore/index.md") in pages
    page = pages[PurePosixPath("explore/index.md")]
    assert yaml.safe_load(page.split("---", 2)[1])["title"] == "글 찾기"
    assert "40개 주제 · 62개 문서" in page
    parser = Elements(page)
    assert len(parser.select("data-explore-topic")) == len(catalog.topics) == 40
    members = parser.select("data-explore-member")
    assert len(members) == len(catalog.documents) == 62
    by_path = {row["data-explore-member"]: row for row in members}
    for doc in catalog.documents:
        row = by_path[doc.relative_path.as_posix()]
        for field in ("services", "tags", "technologies"):
            assert json.loads(row[f"data-{field}"]) == doc.metadata[field]
        assert row["data-search"] == f'{doc.metadata["title"]}\n{doc.metadata["description"]}'
        assert "hidden" not in row
        href = "../" + doc.relative_path.parent.as_posix() + "/"
        assert any(a.get("href") == href for _, a in parser.elements)
    legends = [tag for tag, _ in parser.elements if tag == "legend"]
    assert len(legends) == 5  # service, tags with two groups, technology
    assert "<noscript>" in parser.rendered
    assert 'role="status"' in page and 'aria-live="polite"' in page
    assert 'role="alert"' in page
    assert 'type="search"' in page and 'type="reset"' in page
    assert 'name="text"' in page and 'name="q"' not in page
    assert "모든 주제" in page


def test_explore_data_and_link_labels_are_escaped(taxonomy, catalog):
    doc = catalog.documents[0]
    original = dict(doc.metadata)
    try:
        doc.metadata.update(title='A "quoted" <script>bad</script> & [title]',
                            description="' onfocus='bad' & <img src=x>")
        pages = build_index_pages(catalog.documents, taxonomy, catalog=catalog)
        assert PurePosixPath("explore/index.md") in pages
        parser = Elements(pages[PurePosixPath("explore/index.md")])
        row = next(r for r in parser.select("data-explore-member") if r["data-explore-member"] == str(doc.relative_path))
        assert row["data-search"] == doc.metadata["title"] + "\n" + doc.metadata["description"]
        assert "<script>" not in parser.rendered and "<img src=x>" not in parser.rendered
        assert all("onfocus" not in attrs for _, attrs in parser.elements)
    finally:
        doc.metadata.clear()
        doc.metadata.update(original)


def test_discovery_redirects_are_taxonomy_owned_and_search_excluded(taxonomy, catalog):
    pages = build_index_pages(catalog.documents, taxonomy, catalog=catalog)
    for slug, expected in LEGACY.items():
        path = PurePosixPath(f"tags/{slug}.md")
        assert path in pages
        page = pages[path]
        assert yaml.safe_load(page.split("---", 2)[1])["search"]["exclude"] is True
        links = Elements(page).select("href")
        target = next(a["href"] for a in links if "explore/" in a["href"])
        resolved = urlsplit(urljoin(f"https://example.test/project/tags/{slug}/", target))
        assert resolved.path == "/project/explore/"
        assert parse_qs(resolved.query) == expected
        rendered = on_post_page(
            '<html><head><link rel="canonical" href="old"></head><body></body></html>',
            SimpleNamespace(file=SimpleNamespace(src_uri=str(path))),
            {"docs_dir": str(ROOT / "docs"), "_topic_catalog": catalog},
        )
        assert f'content="0; url={target.replace("&", "&amp;")}"' in rendered.split("</head>")[0]
    for path in ("tags/index.md", "articles/index.md"):
        page = pages[PurePosixPath(path)]
        assert yaml.safe_load(page.split("---", 2)[1])["search"]["exclude"]
        assert 'href="../explore/"' in page


def test_home_navigation_and_article_chips_use_explore(taxonomy, catalog):
    nav = yaml.safe_load((ROOT / "docs/.nav.yml").read_text())["nav"]
    assert [next(iter(item)) for item in nav if "glob" not in item] == ["홈", "서비스별 보기", "글 찾기", "기여하기"]
    home = build_home_page((ROOT / "docs/index.md").read_text(), catalog.documents, taxonomy, catalog=catalog)
    assert "40개 주제 · 62개 문서" in home
    assert "전체 글" not in home and "태그별 보기" not in home
    assert "(explore/index.md)" in home
    doc = catalog.documents[0]
    page = SimpleNamespace(meta=doc.metadata, file=SimpleNamespace(src_uri=str(doc.relative_path)))
    rendered = on_page_markdown("# Title\n", page, {"docs_dir": str(ROOT / "docs"), "_topic_catalog": catalog}, None)
    links = Elements(rendered).select("href")
    for tag in doc.metadata["tags"]:
        assert any(a["href"].endswith(f"explore/index.md?tag={tag}") for a in links)


def test_explore_assets_are_configured_and_accessible():
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text())
    assert "assets/javascripts/explore.js" in config.get("extra_javascript", [])
    css = (ROOT / "docs/assets/stylesheets/extra.css").read_text()
    for selector in (".dg-explore", ".dg-explore-filters", ".dg-explore-member", ".dg-explore-topic", ".dg-filter-option"):
        assert selector in css
    assert ".dg-explore [hidden]" in css
    assert ":focus-visible" in css and "prefers-reduced-motion" in css


def test_service_discovery_reports_topics_and_documents(taxonomy, catalog):
    pages = build_index_pages(catalog.documents, taxonomy, catalog=catalog)
    assert "40개 주제 · 62개 문서" in pages[PurePosixPath("services/index.md")]
    documents = [doc for doc in catalog.documents if "azure-monitor" in doc.metadata["services"]]
    topics = {catalog.by_document[doc.relative_path].entry.relative_path for doc in documents}
    assert f"{len(topics)}개 주제 · {len(documents)}개 문서" in pages[PurePosixPath("services/azure-monitor/index.md")]
    for path in ("services/azure-monitor/index.md", "guides/index.md"):
        assert "개 주제 · " in pages[PurePosixPath(path)]


def test_javascript_behavior_with_available_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable: parent browser verification is required")
    result = subprocess.run([node, "--test", str(ROOT / "tests/docs/explore.test.cjs")],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_explore_integrates_with_material_search_cleanup(tmp_path, taxonomy, catalog):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable: parent browser verification is required")
    page = build_index_pages(catalog.documents, taxonomy, catalog=catalog)[PurePosixPath("explore/index.md")]
    parser = Elements(page)
    controls = [
        {"name": attrs["name"], "value": attrs["value"], "label": attrs["value"]}
        for tag, attrs in parser.elements if tag == "input" and attrs.get("type") == "checkbox"
    ]
    topics = []
    for _, attrs in parser.elements:
        if "data-explore-topic" in attrs:
            topics.append([])
        if "data-explore-member" in attrs:
            topics[-1].append({field: attrs[f"data-{field}"] for field in ("tags", "services", "technologies", "search")})
    matching = [
        [row for row in topic if "design" in json.loads(row["tags"])
         and all(term in row["search"].casefold() for term in ("agent", "memory"))]
        for topic in topics
    ]
    expected = f"{sum(bool(topic) for topic in matching)}개 주제 · {sum(map(len, matching))}개 문서"
    fixture_path = tmp_path / "explore-catalog.json"
    fixture_path.write_text(json.dumps({"controls": controls, "topics": topics, "expectedCount": expected}))
    source_map = next((Path(material.__file__).parent / "templates/assets/javascripts").glob("bundle*.js.map"))
    result = subprocess.run(
        [node, "--test", str(ROOT / "tests/docs/explore-material.test.cjs")],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "MATERIAL_SOURCE_MAP": str(source_map), "EXPLORE_FIXTURE": str(fixture_path)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
