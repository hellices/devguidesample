"""MkDocs hooks for reader navigation, article tags, summaries, and sources."""

from __future__ import annotations

from collections import defaultdict
from html import escape
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Mapping

from mkdocs.structure import StructureItem
from mkdocs.structure.nav import Navigation, Section
from mkdocs.structure.pages import Page


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.docs.content import iter_public_documents, load_taxonomy
from scripts.docs.generate_indexes import build_tag_links


def _navigation_pages(
    items: list[StructureItem], parent: Section | None = None
) -> list[Page]:
    pages: list[Page] = []
    for item in items:
        item.parent = parent
        if isinstance(item, Page):
            pages.append(item)
        elif isinstance(item, Section):
            pages.extend(_navigation_pages(item.children, item))
    return pages


def on_nav(nav: Navigation, config: Mapping[str, Any], files: Any) -> Navigation:
    """Keep each article under its primary service without changing its URL."""
    docs_dir = Path(config["docs_dir"])
    taxonomy = load_taxonomy(docs_dir.parent / "docs-taxonomy.yml")
    document_titles = {
        document.relative_path.as_posix(): str(document.metadata.get("title", "")).casefold()
        for document in iter_public_documents(docs_dir, taxonomy)
    }
    collections = {entry["path"] for entry in taxonomy["collections"].values()}
    collection_indexes = {f"{collection}/index.md" for collection in collections}
    pages_by_path = {page.file.src_uri: page for page in nav.pages}
    by_service: dict[str, list[Page]] = defaultdict(list)
    for page in nav.pages:
        parts = PurePosixPath(page.file.src_uri).parts
        if len(parts) == 4 and parts[0] in collections and parts[-1] == "index.md":
            by_service[parts[1]].append(page)
        page.parent = None
        page.previous_page = None
        page.next_page = None

    items: list[StructureItem] = []
    for item in nav.items:
        children = item.children if isinstance(item, Section) else [item]
        direct_pages = [child for child in children if isinstance(child, Page)]
        if any(page.file.src_uri in collection_indexes for page in direct_pages):
            continue
        if isinstance(item, Section) and any(
            page.file.src_uri == "services/index.md" for page in direct_pages
        ):
            service_items: list[StructureItem] = [pages_by_path["services/index.md"]]
            services = taxonomy["services"]
            for slug in sorted(services, key=lambda value: str(services[value]).casefold()):
                page = pages_by_path[f"services/{slug}/index.md"]
                documents = sorted(
                    by_service.get(slug, []),
                    key=lambda entry: document_titles[entry.file.src_uri],
                )
                if not documents:
                    service_items.append(page)
                else:
                    service_items.append(Section(services[slug], [page, *documents]))
            item.children = service_items
        items.append(item)

    pages = _navigation_pages(items)
    for index, page in enumerate(pages):
        page.previous_page = pages[index - 1] if index else None
        page.next_page = pages[index + 1] if index + 1 < len(pages) else None
    return Navigation(items, pages)


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
    intro = ""
    if description:
        intro = f'<p class="dg-article-lead">{escape(str(description))}</p>\n\n'
    tags = metadata.get("tags")
    if isinstance(tags, list) and tags:
        taxonomy = load_taxonomy(Path(config["docs_dir"]).parent / "docs-taxonomy.yml")
        intro += build_tag_links(
            PurePosixPath(page.file.src_uri),
            [tag for tag in tags if isinstance(tag, str)],
            taxonomy,
        )
    if intro:
        markdown = _insert_after_title(markdown, intro)
    if source_links:
        markdown = (
            markdown.rstrip()
            + '\n\n<details class="doc-sources">\n'
            + "<summary>참고 문서</summary>\n<ul>\n"
            + source_links
            + "\n</ul>\n</details>\n"
        )
    return markdown
