from __future__ import annotations

from dataclasses import FrozenInstanceError
from html import escape
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import sys

from mkdocs.structure.files import File
import pytest
import yaml

from scripts.docs.pre_pages import (
    BaselineDocument, PrePagesInventory, audit_repository, load_inventory,
)
from scripts.docs.pre_pages_site import inspect_built_site
from scripts.docs.topics import build_topic_catalog


ROOT = Path(__file__).parents[2]
CHROMIUM_VISIBILITY = json.loads((ROOT / "tests/docs/fixtures/pre_pages_chromium_visibility.json").read_text())
CLI = ROOT / "scripts/docs/audit_pre_pages.py"
ENTRY = "services/service/topic/index.md"
CHILD = "services/service/topic/child/index.md"
OLD = "guides/service/old/index.md"
OLD_CHILD = "guides/service/old-child/index.md"
ARTICLE = (
    '<article class="md-content__inner md-typeset">'
    '<h1>Document</h1><p>Preserved prose.</p></article>'
)
FOUNDRY_HTML = "services/microsoft-foundry/foundry-local-air-gapped/index.html"


def write(root: Path, path: str, text: str | bytes) -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode() if isinstance(text, str) else text)
    return target


def html(body: str = "", head: str = "") -> str:
    return f"<!doctype html><html><head>{head}</head><body><main>{ARTICLE}{body}</main></body></html>"


def source(path: str, old: str, order: int | None = None) -> str:
    metadata = {
        "title": "Document", "document_type": "guide", "services": ["service"],
        "redirect_from": [old],
    }
    if order:
        metadata["topic_order"] = order
    return "---\n" + yaml.safe_dump(metadata) + "---\n\n# Document\n\nPreserved prose.\n"


def search_entry(path: str, fragment: str = "") -> dict:
    return {
        "location": str(PurePosixPath(path).parent) + "/" + fragment,
        "title": "Document", "text": "Preserved prose.",
    }


def redirect(target: str) -> str:
    return html(
        f'<p><a href="{target}">Moved document</a></p>',
        f'<link rel="canonical" href="{target}">'
        f'<meta http-equiv="refresh" content="0; url={target}">',
    )


@pytest.fixture
def site_repo(tmp_path: Path):
    write(tmp_path, "docs-taxonomy.yml", "services:\n  service: Service\n")
    write(tmp_path, "mkdocs.yml", "site_url: https://example.test/project/\n")
    for path, old, order in ((ENTRY, OLD, None), (CHILD, OLD_CHILD, 1)):
        write(tmp_path / "docs", path, source(path, old, order))
        write(tmp_path / "site", path.replace(".md", ".html"), html())
    for old, target in ((OLD, ENTRY), (OLD_CHILD, CHILD)):
        write(
            tmp_path / "site", old.replace(".md", ".html"),
            redirect("../../../" + str(PurePosixPath(target).parent) + "/"),
        )
    write(tmp_path, "site/services/service/index.html", html('<a href="topic/">Topic</a>'))
    write(tmp_path, "site/explore/index.html", html(
        '<a href="../services/service/topic/">Entry</a>'
        '<a href="../services/service/topic/child/">Child</a>'
    ))
    write(tmp_path, "site/search/search_index.json", json.dumps({
        "docs": [search_entry(ENTRY), search_entry(CHILD), search_entry(CHILD, "#heading")],
    }))
    sample = "docs/services/service/topic/samples/example/"
    write(tmp_path, sample + "README.md", "# Sample\n")
    write(tmp_path, sample + "asset.bin", b"\x00\xffsample\r\n")
    write(tmp_path, sample + "sample.yml", yaml.safe_dump({
        "title": "Sample", "description": "Sample fixture", "kind": "artifact",
        "used_by": ["index"], "publish": [{"source": "asset.bin", "target": "downloads/asset.bin"}],
    }))
    write(tmp_path, "site/services/service/topic/downloads/asset.bin", b"\x00\xffsample\r\n")
    inventory = PrePagesInventory(
        "a" * 40, "b" * 40, 20,
        tuple(BaselineDocument(PurePosixPath(f"old/{i}.md"), PurePosixPath(old), {})
              for i, old in enumerate((OLD, OLD_CHILD))), {},
    )
    return tmp_path, inventory


def inspect(site_repo):
    root, inventory = site_repo
    catalog = build_topic_catalog(root / "docs", {"services": {"service": "Service"}})
    return inspect_built_site(root, root / "site", inventory, catalog)


def findings(site_repo) -> str:
    return "\n".join(inspect(site_repo).errors)


def test_site_fixture_has_all_visibility_and_publish_guarantees(site_repo):
    result = inspect(site_repo)
    assert result.errors == ()
    assert result.details["canonical_html"] == 2
    assert result.details["redirects"] == 2
    assert result.details["searchable_documents"] == 2
    assert result.details["service_topics"] == 1
    assert result.details["explore_documents"] == 2
    assert result.details["published_assets"] == 1


@pytest.mark.parametrize("path,label", [
    ("docs/" + ENTRY, "source"),
    ("site/" + ENTRY.replace(".md", ".html"), "canonical"),
    ("site/" + OLD.replace(".md", ".html"), "redirect"),
    ("site/services/service/index.html", "service"),
    ("site/explore/index.html", "explore"),
    ("site/search/search_index.json", "search"),
])
def test_missing_required_files_fail_closed(site_repo, path, label):
    root, inventory = site_repo
    catalog = build_topic_catalog(root / "docs", {"services": {"service": "Service"}})
    (root / path).unlink()
    result = inspect_built_site(root, root / "site", inventory, catalog)
    assert path.removeprefix("site/").removeprefix("docs/") in "\n".join(result.errors)
    assert label in "\n".join(result.errors).lower()


@pytest.mark.parametrize("kind", ["canonical", "refresh", "fallback"])
def test_each_redirect_channel_must_target_canonical(site_repo, kind):
    root, _ = site_repo
    target = "../../../services/service/topic/"
    content = redirect(target)
    if kind == "canonical":
        content = content.replace(f'rel="canonical" href="{target}"', 'rel="canonical" href="/wrong/"')
    elif kind == "refresh":
        content = content.replace(f"0; url={target}", "0; url=/wrong/")
    else:
        content = content.replace(f'<a href="{target}">', '<a href="/wrong/">')
    write(root / "site", OLD.replace(".md", ".html"), content)
    assert kind in findings(site_repo)


@pytest.mark.parametrize("head", [
    '<link rel="canonical" href="../../../services/service/topic/">',
    '<meta http-equiv="refresh" content="0; url=../../../services/service/topic/">',
    '<meta http-equiv="refresh" content="not a refresh">',
])
def test_duplicate_or_malformed_redirect_metadata_fails(site_repo, head):
    root, _ = site_repo
    path = root / "site" / OLD.replace(".md", ".html")
    path.write_text(path.read_text().replace("</head>", head + "</head>"))
    assert "redirect" in findings(site_repo)


@pytest.mark.parametrize("suffix", ["?different=1", "#other-section"])
def test_redirect_metadata_must_use_the_canonical_base_url(site_repo, suffix):
    root, _ = site_repo
    write(root / "site", OLD.replace(".md", ".html"),
          redirect("../../../services/service/topic/" + suffix))
    assert "redirect canonical" in findings(site_repo)
    assert "redirect refresh" in findings(site_repo)


@pytest.mark.parametrize("body", [
    '<a href="../../../services/service/topic/"></a>',
    '<a href="../../../services/service/topic/"><span hidden>Hidden</span></a>',
    '<noscript><a href="../../../services/service/topic/">No script only</a></noscript>',
])
def test_invisible_fallback_anchors_do_not_prove_redirect_reachability(site_repo, body):
    root, _ = site_repo
    path = root / "site" / OLD.replace(".md", ".html")
    original = path.read_text()
    path.write_text(original[:original.index("<main>") + 6] + body + "</main></body></html>")
    assert "redirect fallback" in findings(site_repo)


def test_initial_pages_redirect_must_appear_exactly_once(site_repo):
    root, inventory = site_repo
    catalog = build_topic_catalog(root / "docs", {"services": {"service": "Service"}})
    catalog.documents[0].metadata["redirect_from"] = [OLD_CHILD, OLD_CHILD]
    result = inspect_built_site(root, root / "site", inventory, catalog)
    assert "exactly once" in "\n".join(result.errors)


@pytest.mark.parametrize("entries", [
    [search_entry(ENTRY), search_entry(CHILD, "#only-heading")],
    [search_entry(ENTRY), search_entry(CHILD), search_entry(OLD, "#heading")],
    [search_entry(ENTRY), search_entry(CHILD), search_entry(OLD)],
])
def test_search_requires_canonical_base_and_excludes_redirects(site_repo, entries):
    root, _ = site_repo
    write(root, "site/search/search_index.json", json.dumps({"docs": entries}))
    assert "search" in findings(site_repo)


def test_homepage_fragment_search_entries_are_valid(site_repo):
    root, _ = site_repo
    write(root, "site/index.html", html())
    entries = [search_entry(ENTRY), search_entry(CHILD)]
    entries.extend({"location": location, "title": "Home", "text": "Home"} for location in ("", "#home"))
    write(root, "site/search/search_index.json", json.dumps({"docs": entries}))
    assert inspect(site_repo).errors == ()


def test_mysql_details_render_tables_and_placeholders_as_markdown():
    from markdown import Markdown
    from scripts.docs.content import load_document

    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text())
    extensions = []
    extension_configs = {}
    for extension in config["markdown_extensions"]:
        if isinstance(extension, dict):
            extensions.extend(extension)
            extension_configs.update(extension)
        else:
            extensions.append(extension)
    renderer = Markdown(extensions=extensions, extension_configs=extension_configs)
    document = load_document(
        ROOT / "docs/services/azure-database-for-mysql/blue-green-upgrade/index.md",
        docs_dir=ROOT / "docs",
    )
    rendered = renderer.convert(document.body)
    assert "<old-db-fqdn>" not in rendered
    assert "<code>&lt;old-db-fqdn&gt;</code>" in rendered
    assert "### 목적" not in rendered
    assert "| write 발생 여부 | Rollback 방법 |" not in rendered


def test_details_rendering_annotation_does_not_change_preserved_source_prose():
    from scripts.docs.pre_pages_content import extract_markdown_structure

    before = "<details>\n<summary>Historical commands</summary>\n\nPreserved prose.\n\n</details>"
    after = before.replace("<details>", '<details markdown="1">')
    baseline = extract_markdown_structure(before)
    current = extract_markdown_structure(after)
    assert baseline == current
    assert extract_markdown_structure(after.replace("Historical commands", "Other")).prose != baseline.prose
    assert extract_markdown_structure(after.replace("Preserved prose.", "")).prose != baseline.prose
    assert extract_markdown_structure('`<details markdown="1">`').prose == ('<details markdown="1">',)


@pytest.mark.parametrize("data", [
    "", "[]", "{}", '{"docs":null}', '{"docs":[null]}', '{"docs":[{}]}',
    '{"docs":[{"location":1,"title":"x","text":"x"}]}',
    '{"docs":[],"docs":[]}',
    '{"docs":[],"config":NaN}',
    json.dumps({"docs": [dict(search_entry(ENTRY), location="../../outside/")]}),
    json.dumps({"docs": [dict(search_entry(ENTRY), location="https://example.test/outside/")]}),
    json.dumps({"docs": [dict(search_entry(ENTRY), location="services/service/topic/\t")]}),
])
def test_malformed_search_state_fails_closed(site_repo, data):
    root, _ = site_repo
    write(root, "site/search/search_index.json", data)
    assert "malformed or missing search index" in findings(site_repo)


def test_raw_published_html_is_a_download_not_a_searchable_page(site_repo):
    root, _ = site_repo
    sample = root / "docs/services/service/topic/samples/example"
    manifest = yaml.safe_load((sample / "sample.yml").read_text())
    manifest["publish"].append({"source": "asset.bin", "target": "downloads/raw.html"})
    (sample / "sample.yml").write_text(yaml.safe_dump(manifest))
    write(root, "site/services/service/topic/downloads/raw.html", b"\x00\xffsample\r\n")
    assert inspect(site_repo).errors == ()
    path = root / "site/search/search_index.json"
    data = json.loads(path.read_text())
    data["docs"].append({
        "location": "services/service/topic/downloads/raw.html",
        "title": "Leaked source", "text": "Sample payload",
    })
    path.write_text(json.dumps(data))
    assert "published" in findings(site_repo)


@pytest.mark.parametrize("path,target", [
    ("site/services/service/index.html", "topic/"),
    ("site/explore/index.html", "../services/service/topic/child/"),
])
def test_chrome_or_hidden_links_do_not_prove_reachability(site_repo, path, target):
    root, _ = site_repo
    write(root, path, html(
        f'<nav><a href="{target}">Navigation only</a></nav>'
        f'<div hidden><a href="{target}">Hidden</a></div>'
        f'<template><a href="{target}">Inert</a></template>'
    ))
    assert "not linked" in findings(site_repo)


@pytest.mark.parametrize("element,raw", [
    ('<img src="images/missing.png">', "images/missing.png"),
    ('<img srcset="images/a.png 1x, images/missing.png 2x">', "images/missing.png"),
    ('<source srcset="images/a.png 1x, images/missing.png 2x">', "images/missing.png"),
    ('<source src="images/missing.png">', "images/missing.png"),
    ('<a href="downloads/missing.bin" download>Download</a>', "downloads/missing.bin"),
    ('<a href="downloads/missing.md">Source</a>', "downloads/missing.md"),
])
def test_every_rendered_local_target_exists_with_path_diagnostics(site_repo, element, raw):
    root, _ = site_repo
    write(root, "site/services/service/topic/images/a.png", b"image")
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(element))
    error = findings(site_repo)
    assert ENTRY.replace(".md", ".html") in error
    assert raw in error


def test_inspects_assets_on_generated_pages_not_only_canonical_pages(site_repo):
    root, _ = site_repo
    write(root, "site/index.html", html('<img src="missing-home.png">'))
    assert "missing-home.png" in findings(site_repo)


def test_nonlocal_fragment_and_query_urls_are_ignored(site_repo):
    root, _ = site_repo
    urls = [
        "https://external.test/not-built.png", "//external.test/not-built.png",
        "data:image/png;base64,Zm9v", "mailto:reader@example.test", "#image", "?image=1",
        "https://external.test/not built.png", "data:image/svg+xml,%3Csvg width='1'%3E",
        "#image one", "?image=one two",
    ]
    elements = "".join(f'<img src="{url}"><a download href="{url}">X</a>' for url in urls)
    elements += '<source srcset="data:image/png;base64,Zm9v 1x, https://external.test/b.png 2x">'
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(elements))
    assert inspect(site_repo).errors == ()


def test_percent_encoded_targets_and_project_absolute_urls_resolve(site_repo):
    root, _ = site_repo
    write(root, "site/services/service/topic/images/한 글.png", b"image")
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(
        '<img src="images/%ED%95%9C%20%EA%B8%80.png?v=2#figure">'
        '<source srcset="/project/services/service/topic/images/%ED%95%9C%20%EA%B8%80.png 2x">'
        '<a download href="/project/services/service/topic/downloads/asset.bin">Download</a>'
    ))
    assert inspect(site_repo).errors == ()


@pytest.mark.parametrize("raw", [
    "../../../../outside.png", "%2e%2e/%2e%2e/%2e%2e/%2e%2e/outside.png",
    "%2f..%2foutside.png", "images/%00.png", "images/%FF.png", "images/%xx.png",
    r"images\outside.png", "images/%5coutside.png",
])
def test_unsafe_asset_resolution_fails_closed(site_repo, raw):
    root, _ = site_repo
    write(root, "outside.png", b"must not be read")
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(f'<img src="{raw}">'))
    assert "unsafe" in findings(site_repo)


def test_asset_symlink_cannot_escape_site(site_repo):
    root, _ = site_repo
    outside = write(root, "outside.png", b"must not be read")
    (root / "site/services/service/topic/image.png").symlink_to(outside)
    write(root, "site/" + ENTRY.replace(".md", ".html"), html('<img src="image.png">'))
    assert "outside site" in findings(site_repo)


def test_unreferenced_symlink_directory_cannot_escape_the_site(site_repo):
    root, _ = site_repo
    (root / "site/leak").symlink_to(root / "docs", target_is_directory=True)
    assert "outside site" in findings(site_repo)


@pytest.mark.parametrize("content", [
    "", "<html><head></head><body><img src='broken",
    html('<img src="x.png" src="y.png">'),
    html("<picture><source srcset='image.png invalid'></picture>"),
    html("<div><span>unclosed</div>"),
    html("", '<base href="https://external.test/">'),
    html("<div aria-hidden>Invalid boolean aria value</div>"),
    "<html><body><head></head><h1>Wrong structure</h1></body></html>",
    html("<script/><a href='downloads/asset.bin'>Not rendered</a>"),
    html("<![UNKNOWN]>"),
])
def test_malformed_html_state_fails_closed(site_repo, content):
    root, _ = site_repo
    write(root, "site/" + ENTRY.replace(".md", ".html"), content)
    assert "HTML" in findings(site_repo)


def test_invalid_utf8_html_is_not_counted_as_a_valid_canonical_page(site_repo):
    root, _ = site_repo
    write(root, "site/" + ENTRY.replace(".md", ".html"), b"\xff")
    result = inspect(site_repo)
    assert result.errors
    assert result.details["canonical_html"] == 1


def test_html_parser_assertion_becomes_a_path_specific_finding(site_repo, monkeypatch):
    from scripts.docs.pre_pages_site import _Page

    def malformed_declaration(self, text):
        raise AssertionError("unknown status keyword in marked section")

    monkeypatch.setattr(_Page, "feed", malformed_declaration)
    errors = findings(site_repo)
    assert "malformed HTML" in errors
    assert ENTRY.replace(".md", ".html") in errors


@pytest.mark.parametrize("suffix", ["samples/leak.py", "child/samples/leak.md"])
def test_sample_source_must_not_leak_into_site(site_repo, suffix):
    root, _ = site_repo
    write(root, "site/services/service/topic/" + suffix, "secret source")
    assert "sample source" in findings(site_repo)


@pytest.mark.parametrize("mutation", ["missing", "changed", "directory"])
def test_published_assets_must_be_byte_identical(site_repo, mutation):
    root, _ = site_repo
    target = root / "site/services/service/topic/downloads/asset.bin"
    target.unlink()
    if mutation == "changed":
        target.write_bytes(b"changed")
    elif mutation == "directory":
        target.mkdir()
    error = findings(site_repo)
    assert "publish" in error
    assert "downloads/asset.bin" in error


@pytest.mark.parametrize("location", ["source", "target"])
def test_publish_symlinks_cannot_escape_their_ownership_roots(site_repo, location):
    root, inventory = site_repo
    catalog = build_topic_catalog(root / "docs", {"services": {"service": "Service"}})
    path = root / (
        "docs/services/service/topic/samples/example/asset.bin" if location == "source"
        else "site/services/service/topic/downloads/asset.bin"
    )
    outside = write(root, "outside.bin", b"\x00\xffsample\r\n")
    path.unlink()
    path.symlink_to(outside)
    errors = inspect_built_site(root, root / "site", inventory, catalog).errors
    assert any("publish" in error and "outside" in error for error in errors)


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout.decode().strip()


@pytest.fixture(scope="module")
def historical_repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("task4-history")
    git(root, "init", "-q")
    git(root, "config", "user.name", "Audit Test")
    git(root, "config", "user.email", "audit@example.test")
    entries = []
    for i in range(62):
        baseline = f"old/doc-{i}.md"
        old = f"guides/service/topic-{i}/index.md"
        canonical = f"services/service/topic-{i}/index.md"
        marker = f"\n<!-- Historical identity {i}: " + (f"document-{i} " * 12) + "-->\n"
        write(root, baseline, "# Document\n\nPreserved prose.\n" + marker)
        entries.append((baseline, old, canonical, marker))
    for i in range(11):
        write(root, f"notes/{i}.md", "Unchanged ancillary Markdown\n")
    for i in range(286):
        write(root, f"assets/{i}.bin", b"baseline")
    git(root, "add", ".")
    git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "Baseline")
    baseline_commit = git(root, "rev-parse", "HEAD")
    for baseline, old, canonical, marker in entries:
        write(root, "docs/" + old, source(canonical, old) + marker)
        (root / baseline).unlink()
    git(root, "add", ".")
    git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "Pages")
    pages_commit = git(root, "rev-parse", "HEAD")
    for baseline, old, canonical, marker in entries:
        write(root, "docs/" + canonical, source(canonical, old) + marker)
        write(root, "site/" + canonical.replace(".md", ".html"), html())
        write(root, "site/" + old.replace(".md", ".html"),
              redirect("../../../" + str(PurePosixPath(canonical).parent) + "/"))
    write(root, "docs-taxonomy.yml", "services:\n  service: Service\n")
    write(root, "site/services/service/index.html", html("".join(
        f'<a href="topic-{i}/">Topic</a>' for i in range(62)
    )))
    write(root, "site/explore/index.html", html("".join(
        f'<a href="../services/service/topic-{i}/">Topic</a>' for i in range(62)
    )))
    write(root, "site/search/search_index.json", json.dumps({
        "docs": [search_entry(canonical) for _, _, canonical, _ in entries],
    }))
    write(root, "scripts/docs/pre_pages_inventory.yml", yaml.safe_dump({
        "version": 3, "baseline_commit": baseline_commit, "pages_commit": pages_commit,
        "rename_similarity": 20, "dispositions": {},
        "documents": [{"baseline_path": b, "pages_path": p} for b, p, _, _ in entries],
    }))
    git(root, "add", ".")
    git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "Current")
    return root


def test_repository_audit_consumes_real_inventory_history_and_content(historical_repo):
    root = historical_repo
    result = audit_repository(root, root / "site", root / "scripts/docs/pre_pages_inventory.yml")
    assert result.errors == ()
    assert (result.baseline_file_count, result.baseline_markdown_count) == (359, 73)
    assert (result.document_count, result.preserved_documents, result.reviewed_documents) == (62, 62, 0)
    assert getattr(result, "current_document_count", None) == 62
    with pytest.raises(FrozenInstanceError):
        result.document_count = 1


def test_cli_success_writes_atomic_json_and_exact_summary(historical_repo):
    output = historical_repo / "audit.json"
    output.write_text("previous report")
    command = subprocess.run([
        sys.executable, str(CLI), "--repo-root", str(historical_repo),
        "--json-output", str(output),
    ], capture_output=True, text=True)
    assert command.returncode == 0, command.stdout + command.stderr
    assert command.stdout.strip() == (
        "Audited 359 baseline files and 73 Markdown files: 62/62 baseline documents "
        "mapped and preserved; 62 current documents searchable and visible; "
        "declared redirects and local assets verified."
    )
    assert json.loads(output.read_text())["errors"] == []
    assert not list(historical_repo.glob(".*.tmp"))


def test_cli_content_only_does_not_claim_built_site_verification(historical_repo):
    command = subprocess.run([
        sys.executable, str(CLI), "--repo-root", str(historical_repo),
        "--site-dir", str(historical_repo / "not-built"), "--content-only",
    ], capture_output=True, text=True)
    assert command.returncode == 0, command.stdout + command.stderr
    assert "content-only" in command.stdout
    assert "searchable" not in command.stdout


def test_cli_errors_are_structured_and_exit_one(historical_repo, tmp_path):
    output = tmp_path / "error.json"
    command = subprocess.run([
        sys.executable, str(CLI), "--repo-root", str(historical_repo),
        "--inventory", str(tmp_path / "missing.yml"), "--json-output", str(output),
    ], capture_output=True, text=True)
    assert command.returncode == 1
    assert "missing.yml" in command.stdout
    assert json.loads(output.read_text())["errors"]
    assert "Traceback" not in command.stderr


@pytest.mark.parametrize("mutation", ["content", "html", "redirect_from"])
def test_real_repository_cli_rejects_current_state_loss(historical_repo, tmp_path, mutation):
    root = tmp_path / "repo"
    shutil.copytree(historical_repo, root)
    if mutation == "html":
        (root / "site/services/service/topic-0/index.html").unlink()
    else:
        source_path = root / "docs/services/service/topic-0/index.md"
        content = source_path.read_text()
        content = content.replace("Preserved prose.", "") if mutation == "content" else content.replace(
            "- guides/service/topic-0/index.md", "- guides/service/missing/index.md",
        )
        source_path.write_text(content)
    command = subprocess.run([
        sys.executable, str(CLI), "--repo-root", str(root),
        "--site-dir", "site", "--inventory", "scripts/docs/pre_pages_inventory.yml",
    ], capture_output=True, text=True)
    assert command.returncode == 1, command.stdout + command.stderr
    assert "topic-0" in command.stdout
    assert "Traceback" not in command.stderr


def test_json_replace_failure_retains_the_previous_report(historical_repo, tmp_path, monkeypatch):
    from scripts.docs.audit_pre_pages import write_audit_json
    from scripts.docs.pre_pages import PreservationAuditResult

    path = write(tmp_path, "report.json", "previous report")
    result = PreservationAuditResult(359, 73, 62, 62, 62, 0, (), (), {})

    def fail_replace(source, destination):
        assert source.parent == destination.parent
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        write_audit_json(path, result)
    assert path.read_text() == "previous report"
    assert not list(tmp_path.glob(".*.tmp"))


def test_cli_emits_one_path_specific_line_per_finding(monkeypatch, capsys):
    from scripts.docs import audit_pre_pages
    from scripts.docs.pre_pages import PreservationAuditResult

    result = PreservationAuditResult(
        359, 73, 62, 62, 61, 0, ("docs/services/service/topic/index.md: lost code: first\nsecond",), (), {},
    )
    monkeypatch.setattr(audit_pre_pages, "audit_repository", lambda *args, **kwargs: result)
    assert audit_pre_pages.main([]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "docs/services/service/topic/index.md: lost code: first\\nsecond",
    ]


@pytest.mark.parametrize("raw", [
    "/services/service/topic/",
    "https://hellices.github.io/services/service/topic/",
    "/devguidesample/../services/service/topic/",
    "/devguidesample/services/service/topic/%2e/",
    "/devguidesample/services/service/topic/%2E%2e/topic/",
    "/devguidesample/services/service/topic/%2f..%2ftopic/",
    "/devguidesample/services/service/topic/index.html/.",
    "/devguidesample/services/service/topic/index.html/%2e",
    "/devguidesample/services/service/topic/index.html/",
])
def test_review_url_semantics_do_not_collapse_into_existing_files(site_repo, raw):
    root, _ = site_repo
    write(root, "mkdocs.yml", "site_url: https://hellices.github.io/devguidesample/\n")
    write(root, "site/" + CHILD.replace(".md", ".html"), html(f'<a href="{raw}">Document</a>'))
    assert raw in findings(site_repo)


@pytest.mark.parametrize("location", [
    "/services/service/topic/",
    "/devguidesample/../services/service/topic/",
    "services/service/topic/%2e/",
    "services/service/topic/%2e%2e/topic/",
    "services/service/topic/index.html/.",
    "services/service/topic/index.html/",
])
def test_review_search_rejects_url_to_filesystem_aliases(site_repo, location):
    root, _ = site_repo
    write(root, "mkdocs.yml", "site_url: https://hellices.github.io/devguidesample/\n")
    entries = [dict(search_entry(ENTRY), location=location), search_entry(CHILD)]
    write(root, "site/search/search_index.json", json.dumps({"docs": entries}))
    assert "malformed or missing search index" in findings(site_repo)


@pytest.mark.parametrize("raw", [
    "C:/images/a.png", r"C:\images\a.png", "C:images/a.png",
    "file:///C:/images/a.png", r"\\hellices.github.io\devguidesample\image.png",
    "https://external.test\\image.png", "%43%3a/images/a.png",
])
def test_review_windows_and_local_file_syntax_cannot_be_ignored_as_external(site_repo, raw):
    root, _ = site_repo
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(f'<img src="{raw}">'))
    assert "unsafe" in findings(site_repo)


@pytest.mark.parametrize("authority", [
    "hellices.github.io", "hellices.github.io:443", "HELLICES.github.io",
])
def test_review_same_origin_protocol_relative_targets_are_inspected(site_repo, authority):
    root, _ = site_repo
    write(root, "mkdocs.yml", "site_url: https://hellices.github.io/devguidesample/\n")
    raw = f"//{authority}/devguidesample/images/missing.png"
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(f'<img src="{raw}">'))
    assert raw in findings(site_repo)


def test_review_protocol_relative_assets_preserve_origin_and_prefix(site_repo):
    root, _ = site_repo
    write(root, "mkdocs.yml", "site_url: https://hellices.github.io/devguidesample/\n")
    write(root, "site/images/present.png", b"image")
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(
        '<img src="//hellices.github.io/devguidesample/images/present.png">'
        '<img src="//external.test/devguidesample/images/not-built.png">'
        '<img src="//hellices.github.io:0/devguidesample/images/not-built.png">'
    ))
    assert inspect(site_repo).errors == ()
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(
        '<img src="//hellices.github.io/images/present.png">',
    ))
    assert "unsafe" in findings(site_repo)


@pytest.mark.parametrize("quotes", [
    ("''", "''"), ('""', '""'), ("'", '"'), ('"', "'"),
    ("", "'"), ("'", ""), ('"', ""), ("", '"'),
    ("'\"", "\"'"), ("\"'", "'\""), ('"""', '"""'),
])
def test_review_refresh_rejects_browser_invalid_url_quoting(site_repo, quotes):
    root, _ = site_repo
    target = "../../../services/service/topic/"
    value = "0; url=" + quotes[0] + target + quotes[1]
    path = root / "site" / OLD.replace(".md", ".html")
    path.write_text(path.read_text().replace("0; url=" + target, escape(value, quote=True)))
    assert "redirect refresh" in findings(site_repo)


@pytest.mark.parametrize("quote_character", ["", "'", '"'])
def test_review_refresh_accepts_exactly_one_matching_quote_pair(site_repo, quote_character):
    root, _ = site_repo
    target = "../../../services/service/topic/"
    value = f" 0 ; URL = {quote_character}{target}{quote_character} \t"
    path = root / "site" / OLD.replace(".md", ".html")
    path.write_text(path.read_text().replace("0; url=" + target, escape(value, quote=True)))
    assert inspect(site_repo).errors == ()


@pytest.mark.parametrize("attribute", ["inert", 'inert="false"'])
@pytest.mark.parametrize("page", ["service", "explore", "redirect"])
def test_review_nested_inert_anchors_cannot_prove_reachability(site_repo, attribute, page):
    root, _ = site_repo
    if page == "service":
        path = "services/service/index.html"
    elif page == "explore":
        path = "explore/index.html"
    else:
        path = OLD.replace(".md", ".html")
    document = (root / "site" / path).read_text()
    document = document.replace(
        "<main>", f"<main><section {attribute}><div><span>",
    ).replace("</main>", "</span></div></section></main>")
    write(root, "site/" + path, document)
    error = findings(site_repo)
    assert "redirect fallback" in error if page == "redirect" else "not linked" in error
    assert path in error or OLD in error


def test_review_inert_descendants_still_check_image_and_source_assets(site_repo):
    root, _ = site_repo
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(
        '<section inert><div><img src="images/missing.png">'
        '<source srcset="images/missing-source.png 2x"></div></section>'
    ))
    error = findings(site_repo)
    assert "images/missing.png" in error
    assert "images/missing-source.png" in error


def test_review_inert_state_ends_with_the_owning_element(site_repo):
    root, _ = site_repo
    write(root, "site/services/service/index.html", html(
        '<section inert><div><a href="topic/">Inert</a></div></section>'
        '<a href="topic/">Reachable</a>'
    ))
    assert inspect(site_repo).errors == ()


@pytest.mark.parametrize("descriptor,valid", [
    ("1x", True), (".5x", True), ("1.5x", True), ("0x", True), ("-0x", True),
    ("1e2x", True), ("1E+2x", True), ("1e-2x", True), ("100w", True), ("00100w", True),
    ("١x", False), ("１x", False), ("1٢w", False), ("١٠٠w", False),
    ("1x\u00a0", False), ("1x\u2003", False),
    ("0w", False), ("000w", False), ("-1x", False), ("+1x", False),
    ("1.x", False), ("NaNx", False), ("Infinityx", False), ("1e999x", False),
    ("100h", False), ("100w 100h", False), ("100h 100w", False),
    ("0h", False), ("١٠٠h", False), ("100w 1x", False), ("1x 2x", False),
])
def test_review_srcset_ascii_descriptor_grammar(site_repo, descriptor, valid):
    root, _ = site_repo
    write(root, "site/services/service/topic/images/a.png", b"image")
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(
        f'<source srcset="images/a.png {descriptor}">',
    ))
    result = inspect(site_repo)
    if valid:
        assert result.errors == ()
    else:
        assert "malformed HTML" in "\n".join(result.errors)


@pytest.mark.parametrize("separator", ["\u00a0", "\u2003", "\u2028"])
def test_review_srcset_non_ascii_whitespace_remains_part_of_the_url(site_repo, separator):
    root, _ = site_repo
    raw = f"images/a.png{separator}1x"
    write(root, "site/services/service/topic/images/a.png", b"only the shorter filename exists")
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(f'<source srcset="{raw}">'))
    assert inspect(site_repo).errors
    write(root, "site/services/service/topic/" + raw, b"the actual URL now exists")
    assert inspect(site_repo).errors == ()


@pytest.mark.parametrize("srcset,valid", [
    ("images/a.png, images/b.png 2x", True),
    ("images/a.png 1x,images/b.png 2x", True),
    ("\t images/a.png\n1x,\rimages/b.png\f2x\t", True),
    ("images/a.png,", True), ("images/a.png 1x,", True),
    ("images/a.png,b.png", True),
    ("data:image/png;base64,AAAA 1x, images/a.png 2x", True),
    ("data:image/svg+xml,%3Csvg%3E,%3C/svg%3E 1x, images/a.png 2x", True),
    ("", False), (" \t\r\n\f", False), (",images/a.png", False),
    ("images/a.png,, images/b.png", False),
    ("images/a.png 1x,,images/b.png", False),
    ("images/a.png, ,images/b.png", False),
    ("images/a.png 1x,\u00a0images/b.png 2x", False),
    ("images/a.png\v1x", False),
])
def test_review_srcset_commas_data_urls_and_empty_candidates(site_repo, srcset, valid):
    root, _ = site_repo
    for name in ("a.png", "b.png", "a.png,b.png"):
        write(root, "site/services/service/topic/images/" + name, b"image")
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(
        f'<source srcset="{escape(srcset, quote=True)}">',
    ))
    result = inspect(site_repo)
    assert (not result.errors) == valid, result.errors


def publish_markdown_download(site_repo, name="raw.md"):
    root, _ = site_repo
    manifest_path = root / "docs/services/service/topic/samples/example/sample.yml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["publish"].append({"source": "README.md", "target": "downloads/" + name})
    manifest_path.write_text(yaml.safe_dump(manifest))
    payload = (manifest_path.parent / "README.md").read_bytes()
    return write(root, "site/services/service/topic/downloads/" + name, payload)


@pytest.mark.parametrize("name,alias", [
    ("raw.md", "raw/index.html"), ("raw.md", "raw.html"),
    ("index.md", "index.html"),
])
def test_review_published_markdown_generated_html_aliases_are_forbidden(site_repo, name, alias):
    root, _ = site_repo
    raw_file = publish_markdown_download(site_repo, name)
    payload = raw_file.read_bytes()
    write(root, "site/services/service/topic/downloads/" + alias, html("Leaked sample source"))
    error = findings(site_repo)
    assert "published Markdown" in error and "built HTML alias" in error
    assert alias in error
    assert raw_file.read_bytes() == payload


@pytest.mark.parametrize("location", ["raw/", "raw/index.html#section", "raw.html", "./"])
@pytest.mark.parametrize("build_alias", [False, True])
def test_review_published_markdown_search_aliases_are_forbidden(site_repo, location, build_alias):
    root, _ = site_repo
    name = "index.md" if location == "./" else "raw.md"
    publish_markdown_download(site_repo, name)
    base = "services/service/topic/downloads/"
    if build_alias:
        alias = "index.html" if location == "./" else "raw.html" if location == "raw.html" else "raw/index.html"
        write(root, "site/" + base + alias, html("Leaked sample source"))
    search_path = root / "site/search/search_index.json"
    data = json.loads(search_path.read_text())
    data["docs"].append({"location": base + location, "title": "Sample", "text": "Leaked source"})
    search_path.write_text(json.dumps(data))
    assert "published Markdown search alias" in findings(site_repo)


def test_review_exact_raw_md_page_and_search_leak_with_intact_raw_bytes(site_repo):
    root, _ = site_repo
    raw_file = publish_markdown_download(site_repo)
    original_bytes = raw_file.read_bytes()
    base = "services/service/topic/downloads/raw/"
    write(root, "site/" + base + "index.html", html("Sample"))
    search_path = root / "site/search/search_index.json"
    data = json.loads(search_path.read_text())
    data["docs"].append({"location": base, "title": "Sample", "text": "Sample"})
    search_path.write_text(json.dumps(data))
    error = findings(site_repo)
    assert "built HTML alias" in error
    assert "published Markdown search alias" in error
    assert raw_file.read_bytes() == original_bytes


def test_review_markdown_alias_detection_is_independent_of_raw_byte_validation(site_repo):
    root, _ = site_repo
    raw_file = publish_markdown_download(site_repo)
    raw_file.write_text("Modified payload")
    write(root, "site/services/service/topic/downloads/raw/index.html", html("Sample"))
    error = findings(site_repo)
    assert "published bytes differ" in error
    assert "built HTML alias" in error


def test_review_plain_raw_markdown_download_is_still_published_unchanged(site_repo):
    root, _ = site_repo
    publish_markdown_download(site_repo)
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(
        '<a href="downloads/raw.md" download>Raw Markdown</a>',
    ))
    assert inspect(site_repo).errors == ()


@pytest.mark.parametrize("raw", [
    "images//../index.html", "images///../index.html",
    "images/%2f/../index.html", "images%2f/../index.html",
    "images/%2F/../index.html", "images%2F%2F../index.html",
    "/project/services/service/topic/images//../index.html",
    "//example.test/project/services/service/topic//index.html",
    "//example.test/project/services/service/topic/%2findex.html",
    "images/%2e/../index.html",
])
def test_rereview_repeated_or_encoded_slashes_fail_before_url_normalization(site_repo, raw):
    root, _ = site_repo
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(f'<img src="{raw}">'))
    assert "unsafe" in findings(site_repo)


@pytest.mark.parametrize("suffix", [
    "images//../index.html", "images/%2f/../index.html",
    "images%2f/../index.html", "/index.html",
])
def test_rereview_search_rejects_repeated_slash_aliases(site_repo, suffix):
    root, _ = site_repo
    location = "services/service/topic/" + suffix
    write(root, "site/search/search_index.json", json.dumps({
        "docs": [dict(search_entry(ENTRY), location=location), search_entry(CHILD)],
    }))
    assert "unsafe" in findings(site_repo)


@pytest.mark.parametrize("page,target", [
    ("services/service/index.html", "topic/images//../index.html"),
    ("explore/index.html", "../services/service/topic/images%2f/../index.html"),
])
def test_rereview_navigation_cannot_use_repeated_slash_aliases(site_repo, page, target):
    root, _ = site_repo
    write(root, "site/" + page, html(f'<a href="{target}">Topic</a>'))
    error = findings(site_repo)
    assert "unsafe" in error
    assert "not linked" in error


@pytest.mark.parametrize("raw", [
    "https://example.test/project/images/ok.png",
    "//example.test/project/images/ok.png",
    "/project/images/ok.png",
    "../../../images/ok.png",
    "data:image/png;base64,AA//BB",
])
def test_rereview_normal_scheme_separators_are_not_path_slashes(site_repo, raw):
    root, _ = site_repo
    write(root, "site/images/ok.png", b"image")
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(f'<img src="{raw}">'))
    assert inspect(site_repo).errors == ()


@pytest.mark.parametrize("raw", [
    "https://%68ellices.github.io/devguidesample/not-present.png",
    "//%68ellices.github.io/devguidesample/not-present.png",
    "https://hellices%2egithub.io/devguidesample/not-present.png",
    "https://hellices.github.io:%34%34%33/devguidesample/not-present.png",
    "https://reader@hellices.github.io/devguidesample/images/ok.png",
    "https://@external.test/not-present.png",
    "https://reader%40example@external.test/not-present.png",
    "https://hellices.github.io:bad/devguidesample/not-present.png",
    "https://hellices.github.io:99999/devguidesample/not-present.png",
    "https://hellices.github.io:-1/devguidesample/not-present.png",
    "https://hellices.github.io:/devguidesample/images/ok.png",
    "https://hellices.github.io:４４３/devguidesample/not-present.png",
    "https://ℎellices.github.io/devguidesample/not-present.png",
    "https://hellices。github.io/devguidesample/not-present.png",
    "https://hellices..github.io/devguidesample/not-present.png",
    "https://hellices.github.io./devguidesample/not-present.png",
    "https://external.\tinvalid/not-present.png",
    "https://[::1]garbage/not-present.png",
    "https://[fe80::1%25eth0]/not-present.png",
    "https://127.1/not-present.png",
    "https://2130706433/not-present.png",
    "https://0x7f000001/not-present.png",
    "https://127.000.000.001/not-present.png",
    "https:images/ok.png",
    "https:///hellices.github.io/devguidesample/not-present.png",
])
def test_rereview_unsupported_authorities_fail_before_external_classification(site_repo, raw):
    root, _ = site_repo
    write(root, "mkdocs.yml", "site_url: https://hellices.github.io/devguidesample/\n")
    write(root, "site/images/ok.png", b"image")
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(f'<img src="{raw}">'))
    assert "unsafe" in findings(site_repo)


@pytest.mark.parametrize("authority", [
    "hellices.github.io", "HELLICES.GITHUB.IO", "hellices.github.io:443",
])
def test_rereview_ordinary_canonical_authority_stays_local(site_repo, authority):
    root, _ = site_repo
    write(root, "mkdocs.yml", "site_url: https://hellices.github.io/devguidesample/\n")
    raw = f"https://{authority}/devguidesample/images/ok.png"
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(f'<img src="{raw}">'))
    assert "missing rendered" in findings(site_repo)
    write(root, "site/images/ok.png", b"image")
    assert inspect(site_repo).errors == ()


@pytest.mark.parametrize("authority", [
    "external.example:443", "xn--bcher-kva.example", "127.0.0.1:8080", "[2001:db8::1]",
])
def test_rereview_supported_external_authorities_remain_ignored(site_repo, authority):
    root, _ = site_repo
    write(root, "site/" + ENTRY.replace(".md", ".html"), html(
        f'<img src="https://{authority}/not-present.png">',
    ))
    assert inspect(site_repo).errors == ()


def test_rereview_encoded_site_authority_is_invalid_configuration(site_repo):
    root, _ = site_repo
    write(root, "mkdocs.yml", "site_url: https://%68ellices.github.io/devguidesample/\n")
    assert "site configuration" in findings(site_repo)


MKDOCS_MARKDOWN_NAMES = [
    "raw.md", "raw.markdown", "raw.mdown", "raw.mkdn", "raw.mkd",
    "README.md", "README.markdown", "README.mdown", "README.mkdn", "README.mkd",
    "readme.md", "Readme.md", "index.md", "INDEX.md", "한 글.markdown",
]


@pytest.mark.parametrize("name", MKDOCS_MARKDOWN_NAMES)
@pytest.mark.parametrize("directory_urls", [True, False])
@pytest.mark.parametrize("channel", ["built", "search"])
def test_rereview_published_page_aliases_follow_installed_mkdocs(site_repo, name, directory_urls, channel):
    root, _ = site_repo
    raw_file = publish_markdown_download(site_repo, name)
    original = raw_file.read_bytes()
    source = "services/service/topic/downloads/" + name
    generated = File(source, str(root / "docs"), str(root / "site"), directory_urls)
    assert generated.is_documentation_page()
    if channel == "built":
        write(root, "site/" + generated.dest_uri, html("Generated sample page"))
        assert "built HTML alias" in findings(site_repo)
    else:
        index = root / "site/search/search_index.json"
        data = json.loads(index.read_text())
        data["docs"].append({"location": generated.url, "title": "Sample", "text": "Sample source"})
        index.write_text(json.dumps(data))
        assert "published Markdown search alias" in findings(site_repo)
    assert raw_file.read_bytes() == original


@pytest.mark.parametrize("name", [
    "raw.MD", "raw.MARKDOWN", "raw.Mdown", "raw.MKDN", "raw.MKD", "README.MD",
])
def test_rereview_mkdocs_non_markdown_case_is_a_static_file(site_repo, name):
    root, _ = site_repo
    raw_file = publish_markdown_download(site_repo, name)
    source = "services/service/topic/downloads/" + name
    file = File(source, str(root / "docs"), str(root / "site"), True)
    assert not file.is_documentation_page()
    assert file.dest_uri == source
    unrelated = str(PurePosixPath(source).with_suffix(".html"))
    write(root, "site/" + unrelated, html("Independent content, not a generated sample page"))
    index = root / "site/search/search_index.json"
    data = json.loads(index.read_text())
    data["docs"].append({"location": unrelated, "title": "Independent", "text": "Unrelated content"})
    index.write_text(json.dumps(data))
    assert raw_file.is_file()
    assert inspect(site_repo).errors == ()


@pytest.mark.parametrize("name", MKDOCS_MARKDOWN_NAMES)
def test_rereview_all_mkdocs_markdown_extensions_allow_plain_raw_publication(site_repo, name):
    raw = publish_markdown_download(site_repo, name)
    assert raw.read_bytes() == b"# Sample\n"
    assert inspect(site_repo).errors == ()


def test_rereview_index_md_has_no_invented_index_subdirectory_alias(site_repo):
    root, _ = site_repo
    publish_markdown_download(site_repo, "index.md")
    write(root, "site/services/service/topic/downloads/index/index.html", html("Independent page"))
    assert inspect(site_repo).errors == ()


AMBIGUOUS_LEADING_SLASHES = [
    "///", "////", "/////", "//////",
    "%2f%2f%2f", "/%2F%2f", "//%2F", "%2F//", "%2f%2f%2f%2f",
]


@pytest.mark.parametrize("prefix", AMBIGUOUS_LEADING_SLASHES)
@pytest.mark.parametrize("element", [
    '<img src="{raw}">', '<source srcset="{raw} 1x">', '<a href="{raw}">Document</a>',
])
def test_raw_leading_slashes_are_rejected_for_rendered_references(site_repo, prefix, element):
    root, _ = site_repo
    write(root, "mkdocs.yml", "site_url: https://hellices.github.io/devguidesample/\n")
    raw = prefix + "devguidesample/services/service/topic/index.html"
    write(root, "site/" + CHILD.replace(".md", ".html"), html(element.format(raw=raw)))
    assert "ambiguous leading slashes" in findings(site_repo)


@pytest.mark.parametrize("prefix", AMBIGUOUS_LEADING_SLASHES)
def test_raw_leading_slashes_are_preserved_until_search_validation(site_repo, prefix):
    root, _ = site_repo
    write(root, "mkdocs.yml", "site_url: https://hellices.github.io/devguidesample/\n")
    raw = prefix + "devguidesample/services/service/topic/"
    write(root, "site/search/search_index.json", json.dumps({
        "docs": [dict(search_entry(ENTRY), location=raw), search_entry(CHILD)],
    }))
    assert "ambiguous leading slashes" in findings(site_repo)


@pytest.mark.parametrize("prefix", ["///", "////", "%2f%2f%2f", "//%2F"])
def test_leading_slash_guard_runs_before_urlsplit(site_repo, prefix, monkeypatch):
    from scripts.docs import pre_pages_site
    from scripts.docs.pre_pages import AuditFormatError

    root, _ = site_repo
    site = pre_pages_site._Site(root / "site", "https://hellices.github.io/devguidesample/")
    original = pre_pages_site.urlsplit
    parsed = []

    def record_parse(raw):
        parsed.append(raw)
        return original(raw)

    monkeypatch.setattr(pre_pages_site, "urlsplit", record_parse)
    with pytest.raises(AuditFormatError):
        site.resolve(
            root / "site" / CHILD.replace(".md", ".html"),
            prefix + "devguidesample/services/service/topic/index.html",
        )
    assert parsed == []


@pytest.mark.parametrize("raw", [
    "/devguidesample/services/service/topic/",
    "//hellices.github.io/devguidesample/services/service/topic/",
])
def test_valid_root_and_authority_leading_slashes_remain_reachable(site_repo, raw):
    root, _ = site_repo
    write(root, "mkdocs.yml", "site_url: https://hellices.github.io/devguidesample/\n")
    write(root, "site/services/service/index.html", html(f'<a href="{raw}">Topic</a>'))
    index = root / "site/search/search_index.json"
    entries = json.loads(index.read_text())
    entries["docs"][0]["location"] = "/devguidesample/services/service/topic/"
    index.write_text(json.dumps(entries))
    assert inspect(site_repo).errors == ()


def test_leading_slashes_have_browser_whatwg_origin_expectations():
    references = [
        ("///devguidesample/services/service/topic/", "https://devguidesample"),
        ("////devguidesample/services/service/topic/", "https://devguidesample"),
        ("//////devguidesample/services/service/topic/", "https://devguidesample"),
        ("/devguidesample/services/service/topic/", "https://hellices.github.io"),
        ("//hellices.github.io/devguidesample/services/service/topic/", "https://hellices.github.io"),
        ("///hellices.github.io/devguidesample/services/service/topic/", "https://hellices.github.io"),
        ("%2f%2f%2fdevguidesample/services/service/topic/", "https://hellices.github.io"),
    ]
    command = subprocess.run([
        "node", "-e",
        "const refs=JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify(refs.map(raw=>new URL(raw,"
        "'https://hellices.github.io/devguidesample/').origin)));",
        json.dumps([raw for raw, _ in references]),
    ], check=True, capture_output=True, text=True)
    assert json.loads(command.stdout) == [origin for _, origin in references]


def test_search_resolver_receives_original_locations_including_fragments(site_repo, monkeypatch):
    from scripts.docs.pre_pages_site import _Site

    root, _ = site_repo
    write(root, "site/index.html", html())
    path = root / "site/search/search_index.json"
    data = json.loads(path.read_text())
    data["docs"].extend({"location": raw, "title": "Home", "text": "Home"} for raw in ("", "#home"))
    path.write_text(json.dumps(data))
    original = _Site.resolve
    received = []

    def record_resolve(self, page, raw, **kwargs):
        if page == root / "site/index.html":
            received.append(raw)
        return original(self, page, raw, **kwargs)

    monkeypatch.setattr(_Site, "resolve", record_resolve)
    assert inspect(site_repo).errors == ()
    assert {"", "#home", search_entry(CHILD, "#heading")["location"]} <= set(received)


@pytest.mark.parametrize("attribute", [
    "hidden", 'hidden="false"', 'aria-hidden="true"',
    'style="display:none"', 'style="visibility:hidden"',
    'style="display: /* hidden */ none !important; display:block"',
])
@pytest.mark.parametrize("container", ["article", "main", "inner", "body-only"])
def test_canonical_article_requires_visible_authored_content(site_repo, attribute, container):
    root, _ = site_repo
    content = html()
    if container == "article":
        content = content.replace("<article ", f"<article {attribute} ")
    elif container == "main":
        content = content.replace("<main>", f"<main {attribute}>")
    elif container == "inner":
        content = content.replace("<h1>", f'<div {attribute}><h1>').replace("</article>", "</div></article>")
    else:
        content = content.replace("<p>", f'<div {attribute}><p>').replace("</p>", "</p></div>")
    write(root, "site/" + ENTRY.replace(".md", ".html"), content)
    error = findings(site_repo)
    assert ENTRY.replace(".md", ".html") in error
    assert "authored" in error and ("hidden" in error or "visible" in error)


@pytest.mark.parametrize("replacement", [
    '<article><h1>Document</h1><p>Preserved prose.</p></article>',
    '<article class="md-content__inner md-typeset"><h1>Unrelated</h1><p>Preserved prose.</p></article>',
    '<article class="md-content__inner md-typeset"><h1>Document</h1></article>',
    '<article class="md-content__inner md-typeset"><h1>Document</h1><p>Unrelated text.</p></article>',
    '<article class="md-content__inner md-typeset"><nav><h1>Document</h1></nav><p>Preserved prose.</p></article>',
    '<article class="md-content__inner md-typeset"><div class="md-search"><h1>Document</h1></div><p>Preserved prose.</p></article>',
    '<nav>' + ARTICLE + '</nav>',
])
def test_canonical_article_rejects_absent_or_unauthored_structure(site_repo, replacement):
    root, _ = site_repo
    content = html('<nav><h1>Document</h1><p>Preserved prose.</p></nav>').replace(ARTICLE, replacement, 1)
    write(root, "site/" + ENTRY.replace(".md", ".html"), content)
    assert "authored" in findings(site_repo)


@pytest.mark.parametrize("replacement", [
    ARTICLE.replace("<article ", "<article inert "),
    ARTICLE.replace("<p>", '<details><summary>More</summary><p>').replace("</p>", "</p></details>"),
    ARTICLE.replace("<article ", '<article style="display:none;display:block" '),
    ARTICLE.replace("<article ", '<article style="--display:none;--visibility:hidden" '),
    ARTICLE.replace("<p>", '<div style="visibility:hidden"><p style="visibility:visible">').replace("</p>", "</p></div>"),
    ARTICLE + '<nav hidden><h1>Mobile navigation</h1></nav><noscript><p hidden>Fallback</p></noscript>',
])
def test_canonical_article_browser_visible_text_and_openable_details_are_valid(site_repo, replacement):
    root, _ = site_repo
    write(root, "site/" + ENTRY.replace(".md", ".html"), html().replace(ARTICLE, replacement))
    assert inspect(site_repo).errors == ()


@pytest.fixture(scope="module")
def real_built_site(tmp_path_factory):
    from mkdocs.commands.build import build
    from mkdocs.config import load_config
    from scripts.docs.content import load_taxonomy

    site = tmp_path_factory.mktemp("final-review-real-build") / "site"
    build(load_config(str(ROOT / "mkdocs.yml"), site_dir=str(site), strict=True))
    inventory = load_inventory(ROOT / "scripts/docs/pre_pages_inventory.yml")
    catalog = build_topic_catalog(ROOT / "docs", load_taxonomy(ROOT / "docs-taxonomy.yml"))
    assert inspect_built_site(ROOT, site, inventory, catalog).errors == ()
    return site, inventory, catalog


@pytest.mark.parametrize("attribute", [
    "hidden", 'aria-hidden="true"', 'style="display:none"', 'style="visibility:hidden"',
])
@pytest.mark.parametrize("container", ["article", "body-only"])
def test_real_foundry_local_built_article_hiding_fails(real_built_site, attribute, container):
    site, inventory, catalog = real_built_site
    path = site / FOUNDRY_HTML
    original = path.read_text()
    article = '<article class="md-content__inner md-typeset">'
    assert original.count(article) == 1
    if container == "article":
        changed = original.replace(article, article.replace("<article ", f"<article {attribute} "))
    else:
        prefix, body = original.split(article, 1)
        heading, rest = body.split("</h1>", 1)
        changed = prefix + article + heading + f'</h1><div {attribute}>' + rest.replace("</article>", "</div></article>", 1)
    try:
        path.write_text(changed)
        errors = inspect_built_site(ROOT, site, inventory, catalog).errors
        assert any(FOUNDRY_HTML in error and "authored" in error for error in errors)
    finally:
        path.write_text(original)


def test_authored_heading_can_restore_inherited_visibility_with_visible_children(site_repo):
    root, _ = site_repo
    content = html().replace(
        "<h1>Document</h1>",
        '<h1 style="visibility:hidden"><span style="visibility:visible">Document</span></h1>',
    )
    write(root, "site/" + ENTRY.replace(".md", ".html"), content)
    assert inspect(site_repo).errors == ()


def test_redirect_fallback_can_be_visible_through_a_visibility_override(site_repo):
    root, _ = site_repo
    target = "../../../services/service/topic/"
    content = redirect(target).replace(
        f'<a href="{target}">Moved document</a>',
        f'<a style="visibility:hidden" href="{target}">'
        '<span style="visibility:visible">Moved document</span></a>',
    )
    write(root, "site/" + OLD.replace(".md", ".html"), content)
    assert inspect(site_repo).errors == ()


FRONTEND_ELEMENTS = (
    '<script src="{url}"></script>',
    '<script type="module" src="{url}"></script>',
    '<link rel="stylesheet" href="{url}">',
    '<link rel="alternate stylesheet" href="{url}">',
    '<link rel="preload" as="style" href="{url}">',
    '<link rel="preload" as="script" href="{url}">',
    '<link rel="modulepreload" href="{url}">',
    '<link rel="modulepreload" as="script" href="{url}">',
)


@pytest.mark.parametrize("element", FRONTEND_ELEMENTS)
def test_missing_frontend_assets_have_source_and_raw_url_diagnostics(site_repo, element):
    root, _ = site_repo
    raw = "assets/missing-frontend.js"
    write(root, "site/index.html", html(head=element.format(url=raw)))
    assert any(
        "index.html" in error and repr(raw) in error and "missing" in error
        for error in inspect(site_repo).errors
    )


@pytest.mark.parametrize("element", FRONTEND_ELEMENTS)
@pytest.mark.parametrize("raw", [
    "/outside/asset.js", "assets/%2e%2e/asset.js", "assets/%ZZ.js",
    "///devguidesample/assets/asset.js",
])
def test_frontend_assets_use_the_strict_shared_url_resolver(site_repo, element, raw):
    root, _ = site_repo
    write(root, "site/index.html", html(head=element.format(url=raw)))
    assert any(
        "index.html" in error and repr(raw) in error and "unsafe" in error
        for error in inspect(site_repo).errors
    )


@pytest.mark.parametrize("element", FRONTEND_ELEMENTS)
def test_frontend_asset_symlinks_cannot_escape_the_site(site_repo, element):
    root, _ = site_repo
    outside = write(root, "outside-frontend.js", "outside site")
    target = root / "site/linked-frontend.js"
    target.symlink_to(outside)
    write(root, "site/index.html", html(head=element.format(url="linked-frontend.js")))
    assert any(
        "index.html" in error and "linked-frontend.js" in error and "outside" in error
        for error in inspect(site_repo).errors
    )


@pytest.mark.parametrize("element", FRONTEND_ELEMENTS)
@pytest.mark.parametrize("raw", [
    "/project/assets/valid%20frontend.js",
    "https://example.test/project/assets/valid%20frontend.js",
    "assets/valid%20frontend.js",
])
def test_frontend_asset_project_prefixes_and_encoded_paths_resolve(site_repo, element, raw):
    root, _ = site_repo
    write(root, "site/assets/valid frontend.js", "published frontend")
    write(root, "site/index.html", html(head=element.format(url=raw)))
    assert inspect(site_repo).errors == ()


@pytest.mark.parametrize("element", FRONTEND_ELEMENTS)
def test_frontend_asset_empty_urls_fail_closed(site_repo, element):
    root, _ = site_repo
    write(root, "site/index.html", html(head=element.format(url="")))
    assert any("index.html" in error and "empty" in error for error in inspect(site_repo).errors)


@pytest.mark.parametrize("head", [
    '<link rel="canonical" href="canonical-page/">',
    '<link rel="alternate" href="another-language/">',
    '<link rel="alternate" type="application/atom+xml" href="feed.xml">',
    '<link rel="preload" as="image" href="unrelated-image.png">',
    '<link rel="stylesheet" href="https://cdn.example.test/external.css">',
    '<script src="https://cdn.example.test/external.js"></script>',
    '<template><script src="inert.js"></script><link rel="stylesheet" href="inert.css"></template>',
    '<noscript><link rel="stylesheet" href="no-scripting.css"></noscript>',
])
def test_nonfrontend_or_inactive_link_resources_are_not_required(site_repo, head):
    root, _ = site_repo
    write(root, "site/index.html", html(head=head))
    assert inspect(site_repo).errors == ()


def test_hidden_frontend_elements_are_still_fetched(site_repo):
    root, _ = site_repo
    write(root, "site/index.html", html(
        '<div hidden><script src="still-fetched.js"></script>'
        '<link rel="stylesheet" href="still-fetched.css"></div>'
    ))
    errors = inspect(site_repo).errors
    for raw in ("still-fetched.js", "still-fetched.css"):
        assert any("index.html" in error and repr(raw) in error for error in errors)


@pytest.mark.parametrize(("element", "suffix"), [
    ("script", "assets/javascripts/explore.js"),
    ("stylesheet", "assets/stylesheets/extra.css"),
])
def test_removing_actual_explore_script_or_custom_stylesheet_fails(real_built_site, element, suffix):
    site, inventory, catalog = real_built_site
    source = site / "explore/index.html"
    pattern = (
        r'<script[^>]+src="([^"]+)"'
        if element == "script" else r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"'
    )
    raw = next(url for url in re.findall(pattern, source.read_text()) if url.endswith(suffix))
    asset = (source.parent / raw).resolve()
    assert asset.is_relative_to(site) and asset.is_file()
    original = asset.read_bytes()
    try:
        asset.unlink()
        errors = inspect_built_site(ROOT, site, inventory, catalog).errors
        assert any("explore/index.html" in error and repr(raw) in error and "missing" in error for error in errors)
    finally:
        asset.write_bytes(original)


@pytest.mark.parametrize("opened", [False, True])
@pytest.mark.parametrize("container", ["details", "summary", "ancestor"])
def test_inert_details_body_is_visible_only_when_already_open(site_repo, opened, container):
    root, _ = site_repo
    attribute = " open" if opened else ""
    article = ARTICLE.replace(
        "<h1>", f'<details{attribute}><summary>Disclosure</summary><h1>',
    ).replace("</article>", "</details></article>")
    article = f"<div inert>{article}</div>" if container == "ancestor" else article.replace(f"<{container}", f"<{container} inert")
    write(root, "site/" + ENTRY.replace(".md", ".html"), html().replace(ARTICLE, article))
    errors = inspect(site_repo).errors
    if opened:
        assert errors == ()
    else:
        assert any("authored" in error for error in errors)


@pytest.mark.parametrize("case", CHROMIUM_VISIBILITY["css"], ids=lambda case: case["id"])
def test_chromium_css_built_visibility_or_path_specific_rejection(site_repo, case):
    root, _ = site_repo
    content = html().replace(ARTICLE, f'<section style="{escape(case["style"], quote=True)}">{ARTICLE}</section>')
    write(root, "site/" + ENTRY.replace(".md", ".html"), content)
    errors = inspect(site_repo).errors
    if case["audit"] == "visible":
        assert errors == ()
    else:
        assert any(ENTRY.replace(".md", ".html") in error for error in errors)
        if case["audit"] == "unsupported":
            assert any("inline CSS" in error for error in errors)


def disclosure(body, case):
    return (
        f'<div {case["ancestor"]}><details><summary {case["summary"]}>'
        f'<{case["tag"]} {case["child"]}>Open</{case["tag"]}></summary>{body}</details></div>'
    )


@pytest.mark.parametrize("case", CHROMIUM_VISIBILITY["disclosures"], ids=lambda case: case["id"])
@pytest.mark.parametrize("channel", ["service", "explore", "redirect"])
def test_chromium_disclosure_state_is_shared_by_reachability_channels(site_repo, case, channel):
    root, _ = site_repo
    if channel == "service":
        path, raw = "services/service/index.html", "topic/"
        content = html(disclosure(f'<a href="{raw}">Topic</a>', case))
    elif channel == "explore":
        path, raw = "explore/index.html", "../services/service/topic/"
        content = html(
            disclosure(f'<a href="{raw}">Topic</a>', case)
            + '<a href="../services/service/topic/child/">Child</a>'
        )
    else:
        path, raw = OLD.replace(".md", ".html"), "../../../services/service/topic/"
        anchor = f'<a href="{raw}">Moved document</a>'
        content = redirect(raw).replace(anchor, disclosure(anchor, case))
    write(root, "site/" + path, content)
    errors = inspect(site_repo).errors
    if case["audit_open"]:
        assert errors == ()
    else:
        assert any("not linked" in error or "redirect fallback" in error for error in errors)


@pytest.mark.parametrize("case", CHROMIUM_VISIBILITY["disclosures"], ids=lambda case: case["id"])
def test_chromium_summary_descendants_determine_built_authored_visibility(site_repo, case):
    root, _ = site_repo
    body = "<h1>Document</h1><p>Preserved prose.</p>"
    article = ARTICLE.replace(body, disclosure(body, case))
    write(root, "site/" + ENTRY.replace(".md", ".html"), html().replace(ARTICLE, article))
    errors = inspect(site_repo).errors
    if case["audit_open"]:
        assert errors == ()
    else:
        assert any("authored" in error for error in errors)


def test_inaccessible_disclosure_still_checks_all_asset_targets(site_repo):
    root, _ = site_repo
    content = html(
        '<details><summary inert>Closed</summary><a href="topic/">Topic</a>'
        '<img src="missing-hidden.png"><script src="missing-hidden.js"></script>'
        '<link rel="stylesheet" href="missing-hidden.css"></details>'
    )
    write(root, "site/services/service/index.html", content)
    errors = inspect(site_repo).errors
    assert any("not linked" in error for error in errors)
    for raw in ("missing-hidden.png", "missing-hidden.js", "missing-hidden.css"):
        assert any("services/service/index.html" in error and repr(raw) in error for error in errors)


@pytest.mark.parametrize("mutation", ["none", "removed", "hidden"])
def test_visible_authored_svg_text_matches_source_and_built_article(site_repo, mutation):
    from scripts.docs.pre_pages_content import create_semantic_renderer

    root, _ = site_repo
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><text x="0" y="20">Authored <tspan>diagram label</tspan></text></svg>'
    document = root / "docs" / ENTRY
    document.write_text(document.read_text() + "\n\n" + svg + "\n")
    body = create_semantic_renderer().convert("# Document\n\nPreserved prose.\n\n" + svg)
    if mutation == "removed":
        body = re.sub(r"<text\b.*?</text>", '<path d="M0 0h10v10z"/>', body)
    elif mutation == "hidden":
        body = body.replace("<text ", '<text style="display:none" ')
    article = '<article class="md-content__inner md-typeset">' + body + "</article>"
    write(root, "site/" + ENTRY.replace(".md", ".html"), html().replace(ARTICLE, article))
    errors = inspect(site_repo).errors
    if mutation == "none":
        assert errors == ()
    else:
        assert any("authored" in error for error in errors)


@pytest.mark.parametrize("svg", [
    '<svg aria-hidden="true"><text>Decorative label</text><path d="M0 0h10v10z"/></svg>',
    '<svg class="md-icon" aria-hidden="true"><title>Icon</title><path d="M0 0h10v10z"/></svg>',
    '<svg><defs><text>Definition, not a painted label</text></defs><path d="M0 0h10v10z"/></svg>',
    '<svg><g aria-hidden="true"><text>Decorative group label</text></g></svg>',
    '<svg><text aria-hidden="true">Decorative text label</text></svg>',
])
def test_generated_svg_icons_do_not_supply_built_authored_content(site_repo, svg):
    root, _ = site_repo
    write(root, "site/" + ENTRY.replace(".md", ".html"), html().replace("</h1>", svg + "</h1>"))
    assert inspect(site_repo).errors == ()


def test_late_inert_summary_cannot_expose_earlier_reachability_links(site_repo):
    root, _ = site_repo
    write(root, "site/services/service/index.html", html(
        '<details><a href="topic/">Topic</a><summary inert>Cannot open</summary></details>'
    ))
    assert "not linked" in findings(site_repo)


@pytest.mark.parametrize("style", CHROMIUM_VISIBILITY["unresolved_css"])
def test_unresolved_inline_css_reports_the_built_source_path(site_repo, style):
    root, _ = site_repo
    write(root, "site/" + ENTRY.replace(".md", ".html"), html().replace(
        ARTICLE, f'<div style="{escape(style, quote=True)}">{ARTICLE}</div>',
    ))
    assert any(
        ENTRY.replace(".md", ".html") in error and "inline CSS" in error
        for error in inspect(site_repo).errors
    )


def test_unresolved_source_css_becomes_a_canonical_path_finding(site_repo):
    root, _ = site_repo
    document = root / "docs" / ENTRY
    document.write_text(document.read_text() + '\n<div style="display:var(--visibility)">Authored text.</div>\n')
    assert any(ENTRY in error and "inline CSS" in error for error in inspect(site_repo).errors)


def add_current_document(root, path="services/service/extra/index.md", redirects=(), order=None):
    metadata = {"title": "Document", "document_type": "guide", "services": ["service"]}
    if redirects:
        metadata["redirect_from"] = list(redirects)
    if order is not None:
        metadata["topic_order"] = order
    write(root / "docs", path, "---\n" + yaml.safe_dump(metadata) + "---\n\n# Document\n\nCurrent-only prose.\n")
    write(root / "site", path.replace(".md", ".html"), html().replace("Preserved prose.", "Current-only prose."))
    topic = PurePosixPath(path).parts[2]
    service = root / "site/services/service/index.html"
    service.write_text(service.read_text().replace("</main>", f'<a href="{topic}/">Current topic</a></main>'))
    explore = root / "site/explore/index.html"
    explore.write_text(explore.read_text().replace(
        "</main>", f'<a href="../{PurePosixPath(path).parent}/">Current member</a></main>',
    ))
    search = root / "site/search/search_index.json"
    data = json.loads(search.read_text())
    data["docs"].append(search_entry(path))
    search.write_text(json.dumps(data))
    for old in redirects:
        target = posixpath.relpath(str(PurePosixPath(path).parent), str(PurePosixPath(old).parent)) + "/"
        write(root / "site", old.replace(".md", ".html"), redirect(target))
    return path


@pytest.mark.parametrize("extra_count", [1, 4])
@pytest.mark.parametrize("content_only", [False, True])
def test_repository_reports_baseline_and_dynamic_current_counts(historical_repo, tmp_path, extra_count, content_only):
    root = tmp_path / "repo"
    shutil.copytree(historical_repo, root)
    for index in range(extra_count):
        add_current_document(root, f"services/service/new-{index}/index.md")
    result = audit_repository(
        root, root / "site", root / "scripts/docs/pre_pages_inventory.yml", content_only=content_only,
    )
    assert result.errors == ()
    assert result.document_count == result.preserved_documents == 62
    assert getattr(result, "current_document_count", None) == 62 + extra_count
    assert result.details.get("current_document_count") == 62 + extra_count
    assert len(result.details["documents"]) == 62
    assert not any("new-" in str(document["current_path"]) for document in result.details["documents"])
    if not content_only:
        for key in ("canonical_html", "searchable_documents", "explore_documents"):
            assert result.details["site"][key] == 62 + extra_count


@pytest.mark.parametrize("content_only", [False, True])
def test_cli_distinguishes_baseline_preservation_from_growing_current_coverage(historical_repo, tmp_path, content_only):
    root = tmp_path / "repo"
    shutil.copytree(historical_repo, root)
    add_current_document(root)
    output = root / "current-audit.json"
    command = [
        sys.executable, str(CLI), "--repo-root", str(root), "--json-output", str(output),
    ]
    if content_only:
        command += ["--content-only", "--site-dir", "not-built"]
    run = subprocess.run(command, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "62/62 baseline documents mapped and preserved" in run.stdout
    assert "63 current documents" in run.stdout
    data = json.loads(output.read_text())
    assert data["document_count"] == 62
    assert data.get("current_document_count") == data["details"].get("current_document_count") == 63
    assert len(data["details"]["documents"]) == 62
    if content_only:
        assert "built site not inspected" in run.stdout and "searchable" not in run.stdout
    else:
        assert "63 current documents searchable and visible" in run.stdout


def test_extra_current_documents_are_all_counted_without_inventory_entries(site_repo):
    root, inventory = site_repo
    add_current_document(root)
    result = inspect(site_repo)
    assert result.errors == ()
    assert len(inventory.documents) == 2
    assert result.details.get("current_document_count") == 3
    assert result.details["canonical_html"] == result.details["searchable_documents"] == result.details["explore_documents"] == 3


@pytest.mark.parametrize("mutation", ["hidden", "search", "explore", "omitted"])
def test_extra_current_child_cannot_be_hidden_or_omitted_from_built_coverage(site_repo, mutation):
    root, _ = site_repo
    extra = add_current_document(root, "services/service/topic/extra/index.md", order=2)
    assert inspect(site_repo).errors == ()
    page = root / "site" / extra.replace(".md", ".html")
    if mutation == "hidden":
        page.write_text(page.read_text().replace("<article ", "<article hidden "))
    if mutation in {"search", "omitted"}:
        search = root / "site/search/search_index.json"
        data = json.loads(search.read_text())
        data["docs"] = [entry for entry in data["docs"] if entry["location"] != search_entry(extra)["location"]]
        search.write_text(json.dumps(data))
    if mutation in {"explore", "omitted"}:
        explore = root / "site/explore/index.html"
        explore.write_text(explore.read_text().replace(
            f'<a href="../{PurePosixPath(extra).parent}/">Current member</a>', "",
        ))
    if mutation == "omitted":
        page.unlink()
    errors = inspect(site_repo).errors
    assert any("services/service/topic/extra/" in error for error in errors)
    if mutation == "hidden":
        assert any("authored" in error for error in errors)
    elif mutation == "omitted":
        assert any("canonical" in error and "missing" in error for error in errors)


@pytest.mark.parametrize("mutation", ["missing", "canonical", "refresh", "fallback", "search"])
def test_every_extra_current_document_redirect_is_verified(site_repo, mutation):
    root, _ = site_repo
    old = "research/service/extra-v2/index.md"
    extra = add_current_document(root, redirects=("guides/service/extra-v1/index.md", old))
    assert inspect(site_repo).errors == ()
    page = root / "site" / old.replace(".md", ".html")
    if mutation == "missing":
        page.unlink()
    elif mutation == "canonical":
        page.write_text(re.sub(r'rel="canonical" href="[^"]+"', 'rel="canonical" href="../wrong/"', page.read_text()))
    elif mutation == "refresh":
        page.write_text(page.read_text().replace("0; url=", "1; url="))
    elif mutation == "fallback":
        page.write_text(re.sub(r'<a href="[^"]+">Moved document</a>', "<span>Moved document</span>", page.read_text()))
    else:
        search = root / "site/search/search_index.json"
        data = json.loads(search.read_text())
        data["docs"].append(search_entry(old, "#moved"))
        search.write_text(json.dumps(data))
    assert any(old.removesuffix(".md") in error and "redirect" in error for error in inspect(site_repo).errors)


def test_all_redirect_aliases_of_baseline_members_are_verified(site_repo):
    root, _ = site_repo
    old = "research/service/also-old/index.md"
    document = root / "docs" / ENTRY
    document.write_text(document.read_text().replace(f"- {OLD}\n", f"- {OLD}\n- {old}\n"))
    write(root / "site", old.replace(".md", ".html"), redirect("../../../services/service/topic/"))
    result = inspect(site_repo)
    assert result.errors == ()
    assert result.details["redirects"] == 3
    (root / "site" / old.replace(".md", ".html")).unlink()
    assert any(old.removesuffix(".md") in error and "redirect" in error for error in inspect(site_repo).errors)


@pytest.mark.parametrize("element", [
    '<script src="missing-extra.js"></script>',
    '<link rel="stylesheet" href="missing-extra.css">',
    '<img src="missing-extra.png">',
])
def test_extra_current_pages_keep_frontend_and_asset_validation(site_repo, element):
    root, _ = site_repo
    extra = add_current_document(root)
    page = root / "site" / extra.replace(".md", ".html")
    page.write_text(page.read_text().replace("</main>", element + "</main>"))
    assert any(extra.replace(".md", ".html") in error and "missing-extra" in error for error in inspect(site_repo).errors)


def test_real_s1_hidden_svg_artifact_cannot_supply_visible_image_evidence(real_built_site):
    site, inventory, catalog = real_built_site
    relative = "services/azure-monitor/azure-sre-agent/validation-results/index.html"
    path = site / relative
    original = path.read_text()
    images = [image for image in re.findall(r"<img\b[^>]*>", original) if "s1-investigation.gif" in image]
    assert len(images) == 1 and "S1 SRE Agent investigation" in images[0]
    hidden = '<svg aria-hidden="true" style="display:none"><foreignObject>' + images[0] + "</foreignObject></svg>"
    try:
        path.write_text(original.replace(images[0], hidden))
        errors = inspect_built_site(ROOT, site, inventory, catalog).errors
        assert any(relative in error and "authored" in error for error in errors)
        assert not any("missing rendered" in error and "s1-investigation.gif" in error for error in errors)
    finally:
        path.write_text(original)


@pytest.mark.parametrize("raw", [
    "javascript:void(0)", "JaVaScRiPt:void(0)", "java\tscript:void(0)",
    "java\nscript:void(0)", "\x1f \tJAVASCRIPT:void(0)\r",
    "jav&#x61;script&#58;void(0)", "java&Tab;script&colon;void(0)",
    "&#x20;&#x09;JaVaScRiPt&#58;void(0)",
    "vbscript:code", "VbScRiPt:code", "vb&#x0a;script:code",
    "file:///example.txt", "FiLe:///example.txt", "fi&NewLine;le:///example.txt",
])
@pytest.mark.parametrize("element", [
    '<a href="{raw}">Unsafe link</a>',
    '<img src="{raw}">',
    '<script src="{raw}"></script>',
    '<link rel="stylesheet" href="{raw}">',
    '<link rel="modulepreload" href="{raw}">',
])
def test_executable_and_local_url_schemes_fail_before_external_classification(site_repo, raw, element):
    root, _ = site_repo
    write(root, "site/index.html", html(element.format(raw=raw)))
    errors = inspect(site_repo).errors
    assert any("index.html" in error and "unsafe URL" in error and "scheme" in error for error in errors)


@pytest.mark.parametrize("raw", [
    "javascript:void(0)", "JaVaScRiPt:void(0)", "java\tscript:void(0)",
    "vbscript:code", "VBScript:code", "file:///example.txt", "fi\rle:///example.txt",
])
def test_unsafe_scheme_search_locations_are_rejected_with_index_path(site_repo, raw):
    root, _ = site_repo
    entries = [search_entry(ENTRY), search_entry(CHILD), {"location": raw, "title": "Unsafe", "text": "Unsafe"}]
    write(root, "site/search/search_index.json", json.dumps({"docs": entries}))
    assert any("search/search_index.json" in error and repr(raw) in error for error in inspect(site_repo).errors)


@pytest.mark.parametrize("raw", [
    "data:image/png;base64,AAAA", "DATA:image/png;base64,AAAA",
    "mailto:reader@example.test", "MAILTO:reader@example.test",
    "https://external.test/asset.png", "HTTP://external.test/asset.png",
])
def test_explicitly_allowed_nonlocal_url_schemes_remain_ignored(site_repo, raw):
    root, _ = site_repo
    write(root, "site/index.html", html(f'<a href="{raw}">Allowed</a><img src="{raw}">'))
    assert inspect(site_repo).errors == ()


def test_html_entity_decoding_for_scheme_checks_happens_only_once(site_repo):
    root, _ = site_repo
    write(root, "site/&", "Literal local URL before its fragment")
    write(root, "site/index.html", html('<a href="&amp;#x6a;avascript:fixture">Literal reference</a>'))
    assert inspect(site_repo).errors == ()


@pytest.mark.parametrize("opened", [False, True])
def test_built_summaryless_details_are_accessible_closed_or_open(site_repo, opened):
    root, _ = site_repo
    article = ARTICLE.replace("<h1>", f'<details{" open" if opened else ""}><h1>').replace(
        "</article>", "</details></article>",
    )
    write(root, "site/" + ENTRY.replace(".md", ".html"), html().replace(ARTICLE, article))
    errors = inspect(site_repo).errors
    assert errors == ()


@pytest.mark.parametrize("channel", ["service", "explore", "redirect"])
@pytest.mark.parametrize("late_summary", [False, True])
def test_generated_page_disclosures_allow_default_or_late_summary(site_repo, channel, late_summary):
    root, _ = site_repo
    summary = "<p>before</p><summary>Late</summary>" if late_summary else ""
    if channel == "service":
        path, target = "services/service/index.html", "topic/"
        body = f'<details>{summary}<a href="{target}">Topic</a></details>'
        content = html(body)
    elif channel == "explore":
        path, target = "explore/index.html", "../services/service/topic/"
        body = f'<details>{summary}<a href="{target}">Topic</a></details>'
        content = html(body + '<a href="../services/service/topic/child/">Child</a>')
    else:
        path, target = OLD.replace(".md", ".html"), "../../../services/service/topic/"
        anchor = f'<a href="{target}">Moved document</a>'
        content = redirect(target).replace(anchor, f"<details>{summary}{anchor}</details>")
    write(root, "site/" + path, content)
    errors = inspect(site_repo).errors
    assert errors == ()


def test_summaryless_details_still_validate_fetched_assets(site_repo):
    root, _ = site_repo
    write(root, "site/index.html", html('<details><img src="missing-summaryless.png"></details>'))
    assert any("index.html" in error and "missing-summaryless.png" in error for error in inspect(site_repo).errors)


IMPLIED_END_ORACLE = json.loads((ROOT / "tests/docs/fixtures/pre_pages_implied_end_chromium.json").read_text())


@pytest.mark.parametrize("case", IMPLIED_END_ORACLE["cases"], ids=lambda case: case["id"])
def test_built_optional_end_tags_match_chromium_visibility(site_repo, case):
    from scripts.docs.pre_pages_content import create_semantic_renderer

    root, _ = site_repo
    source_path = root / "docs" / ENTRY
    metadata = source_path.read_text().split("\n---\n", 1)[0]
    body = "# Document\n\n" + case["html"]
    source_path.write_text(metadata + "\n---\n\n" + body)
    rendered = create_semantic_renderer().convert(body)
    article = '<article class="md-content__inner md-typeset">' + rendered + "</article>"
    write(root, "site/" + ENTRY.replace(".md", ".html"), html().replace(ARTICLE, article))
    errors = inspect(site_repo).errors
    if case["visible"]:
        assert errors == ()
    else:
        assert any("authored" in error for error in errors)


@pytest.mark.parametrize("body", [
    "<table hidden><p>text</p></table>",
    "<table><tbody><div>text</div></tbody></table>",
    "<table><tbody><tr>text</tr></tbody></table>",
    "<table>&nbsp;</table>",
])
def test_built_table_foster_ambiguity_reports_the_source_path(site_repo, body):
    root, _ = site_repo
    write(root, "site/index.html", html(body))
    assert any("index.html" in error and "foster" in error for error in inspect(site_repo).errors)


@pytest.mark.parametrize("tag", ["textarea", "xmp", "iframe", "noembed", "noframes"])
def test_parent_page_ignores_raw_fallback_assets_but_checks_following_content(site_repo, tag):
    root, _ = site_repo
    write(root, "site/real.png", b"real")
    body = f'<{tag}><img src="fake.png"><a href="fake.html">Fake</a></{tag}><img src="real.png">'
    write(root, "site/index.html", html(body))
    assert inspect(site_repo).errors == ()
    (root / "site/real.png").unlink()
    errors = findings(site_repo)
    assert "real.png" in errors and "fake.png" not in errors and "fake.html" not in errors


def test_iframe_src_is_checked_without_parsing_its_fallback(site_repo):
    root, _ = site_repo
    write(root, "site/index.html", html('<iframe src="missing-frame.html"><img src="fake.png"></iframe>'))
    errors = findings(site_repo)
    assert "missing-frame.html" in errors and "fake.png" not in errors


@pytest.mark.parametrize("slash", ["", "/"])
def test_plaintext_to_eof_never_promotes_parent_page_targets(site_repo, slash):
    from scripts.docs.pre_pages_site import _Page

    reader = _Page()
    reader.finish(html(f'<plaintext{slash}>Literal</plaintext><img src="fake.png"><a href="fake.html">Fake</a>'))
    assert not any(raw in {"fake.png", "fake.html"} for _, raw in reader.targets)
    assert reader.errors


FOURTH_ORACLE = json.loads((ROOT / "tests/docs/fixtures/pre_pages_fourth_chromium.json").read_text())


@pytest.mark.parametrize("case", FOURTH_ORACLE["srcset"], ids=lambda case: case["id"])
def test_srcset_url_tokens_match_the_permanent_chromium_oracle(case):
    from scripts.docs.pre_pages_site import _srcset

    assert _srcset(case["value"]) == case["candidates"]
    if case["id"] == "combined":
        assert case["requested"] == [case["current_src"]]
        assert case["current_src"] == FOURTH_ORACLE["base_url"] + "images/a.png,b.png"
        assert case["natural_width"] == 1


def test_comma_without_ascii_whitespace_requires_the_combined_local_asset(site_repo):
    root, _ = site_repo
    write(root, "site/images/a.png", b"a")
    write(root, "site/images/b.png", b"b")
    write(root, "site/index.html", html('<img srcset="images/a.png,b.png">'))
    assert "images/a.png,b.png" in findings(site_repo)
    write(root, "site/images/a.png,b.png", b"combined")
    assert inspect(site_repo).errors == ()


@pytest.mark.parametrize("case", FOURTH_ORACLE["css"], ids=lambda case: case["id"])
def test_built_visibility_inherit_unset_and_restore_controls(site_repo, case):
    root, _ = site_repo
    article = ARTICLE.replace(
        "<h1>Document</h1>", f'<h1 style="visibility:hidden!important"><span style="{case["style"]}">Document</span></h1>',
    )
    write(root, "site/" + ENTRY.replace(".md", ".html"), html().replace(ARTICLE, article))
    errors = inspect(site_repo).errors
    assert errors == () if case["visible"] else any("authored" in error for error in errors)


DEFAULT_SUMMARY_ORACLE = json.loads((ROOT / "tests/docs/fixtures/pre_pages_default_summary_chromium.json").read_text())


@pytest.mark.parametrize("case", DEFAULT_SUMMARY_ORACLE["cases"], ids=lambda case: case["id"])
def test_native_summaryless_built_article_inherits_blockers(site_repo, case):
    root, _ = site_repo
    article = ARTICLE.replace("<h1>", f'<div {case["ancestor"]}><details><h1>').replace(
        "</article>", "</details></div></article>",
    )
    write(root, "site/" + ENTRY.replace(".md", ".html"), html().replace(ARTICLE, article))
    errors = inspect(site_repo).errors
    assert errors == () if case["audit_open"] else any("authored" in error for error in errors)


@pytest.mark.parametrize("case", DEFAULT_SUMMARY_ORACLE["cases"], ids=lambda case: case["id"])
@pytest.mark.parametrize("channel", ["service", "explore", "redirect"])
def test_native_summaryless_reachability_inherits_blockers(site_repo, case, channel):
    root, _ = site_repo

    def wrapped(anchor):
        return f'<div {case["ancestor"]}><details>{anchor}</details></div>'

    if channel == "service":
        path = "services/service/index.html"
        content = html(wrapped('<a href="topic/">Topic</a>'))
    elif channel == "explore":
        path = "explore/index.html"
        content = html(wrapped('<a href="../services/service/topic/">Topic</a>') +
                       '<a href="../services/service/topic/child/">Child</a>')
    else:
        path = OLD.replace(".md", ".html")
        target = "../../../services/service/topic/"
        anchor = f'<a href="{target}">Moved document</a>'
        content = redirect(target).replace(anchor, wrapped(anchor))
    write(root, "site/" + path, content)
    errors = inspect(site_repo).errors
    if case["audit_open"]:
        assert errors == ()
    else:
        assert any("not linked" in error or "fallback" in error for error in errors)
