"""MkDocs hooks for article summaries and source references."""

from __future__ import annotations

from html import escape
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Mapping

from mkdocs.structure.nav import Navigation, Section
from mkdocs.structure.pages import Page


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.docs.content import load_taxonomy


def on_nav(nav: Navigation, config: Mapping[str, Any], files: Any) -> Navigation:
    """Expose bundles as document leaves, using metadata rather than folder labels."""
    taxonomy = load_taxonomy(Path(config["docs_dir"]).parent / "docs-taxonomy.yml")
    collections = {entry["path"] for entry in taxonomy["collections"].values()}
    for collection in nav.items:
        if not isinstance(collection, Section):
            continue
        for service in collection.children:
            if not isinstance(service, Section):
                continue
            for index, bundle in enumerate(service.children):
                if not isinstance(bundle, Section) or len(bundle.children) != 1:
                    continue
                page = bundle.children[0]
                if not isinstance(page, Page):
                    continue
                parts = PurePosixPath(page.file.src_uri).parts
                if len(parts) != 4 or parts[0] not in collections or parts[-1] != "index.md":
                    continue
                service.title = taxonomy["services"][parts[1]]
                page.parent = service
                service.children[index] = page
    return nav


def _insert_after_title(markdown: str, block: str) -> str:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            lines[index + 1 : index + 1] = ["", block.rstrip(), ""]
            return "\n".join(lines).rstrip() + "\n"
    return block + "\n" + markdown


def on_page_markdown(markdown: str, page: Any, config: Mapping[str, Any], files: Any) -> str:
    """Render reader-facing summaries and references without workflow notices."""
    metadata = page.meta
    if not metadata.get("document_type"):
        return markdown

    sources = metadata.get("official_sources") or []
    source_links = "\n".join(
        f'<li><a href="{escape(str(source["url"]), quote=True)}">'
        f'{escape(str(source["title"]))}</a></li>'
        for source in sources
        if isinstance(source, Mapping) and source.get("title") and source.get("url")
    )
    description = metadata.get("description")
    if description:
        markdown = _insert_after_title(
            markdown, f'<p class="dg-article-lead">{escape(str(description))}</p>'
        )
    if source_links:
        markdown = (
            markdown.rstrip()
            + '\n\n<details class="doc-sources">\n'
            + "<summary>참고 문서</summary>\n<ul>\n"
            + source_links
            + "\n</ul>\n</details>\n"
        )
    return markdown
