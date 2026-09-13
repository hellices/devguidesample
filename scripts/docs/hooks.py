"""MkDocs hooks for reader navigation, article tags, summaries, and sources."""

from __future__ import annotations

from collections import defaultdict
from html import escape
from pathlib import Path, PurePosixPath
import posixpath
import re
import sys
from typing import Any, Mapping

from mkdocs.structure.files import File, InclusionLevel
from mkdocs.structure import StructureItem
from mkdocs.structure.nav import Navigation, Section
from mkdocs.structure.pages import Page


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.docs.content import load_taxonomy
from scripts.docs.generate_indexes import build_tag_links
from scripts.docs.explore import filter_redirect_targets
from scripts.docs.topics import TopicCatalog, build_topic_catalog, iter_topic_documents


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


class _PublishedAssetFile(File):
    def is_documentation_page(self) -> bool:
        return False


def on_files(files: Any, config: Mapping[str, Any]) -> Any:
    """Exclude sample sources and keep published Markdown payloads as raw assets."""
    try:
        config.pop("_topic_catalog", None)  # type: ignore[union-attr]
    except Exception:
        pass
    catalog = _topic_catalog_from_config(config)
    for file in list(files):
        src_uri = getattr(file, "src_uri", "")
        if isinstance(src_uri, str) and "/samples/" in src_uri:
            file.inclusion = InclusionLevel.EXCLUDED
        elif catalog is not None and PurePosixPath(src_uri) in catalog.published_assets:
            if file.is_documentation_page():
                published = _PublishedAssetFile(
                    src_uri, file.src_dir, file.dest_dir, file.use_directory_urls,
                    dest_uri=src_uri, inclusion=file.inclusion,
                )
                files.remove(file)
                files.append(published)
    return files


def _topic_catalog_for(docs_dir: str) -> TopicCatalog:
    docs_path = Path(docs_dir)
    taxonomy = load_taxonomy(docs_path.parent / "docs-taxonomy.yml")
    public_documents = list(iter_topic_documents(docs_path, taxonomy))
    return build_topic_catalog(docs_path, taxonomy, documents=public_documents)


def _topic_catalog_from_config(config: Mapping[str, Any]) -> TopicCatalog | None:
    cached = config.get("_topic_catalog") if hasattr(config, "get") else None
    if isinstance(cached, TopicCatalog):
        return cached

    docs_dir_value = config.get("docs_dir") if hasattr(config, "get") else None
    if not isinstance(docs_dir_value, str):
        return None

    catalog = _topic_catalog_for(docs_dir_value)
    try:
        config["_topic_catalog"] = catalog  # type: ignore[index]
    except Exception:
        pass
    return catalog


def _strip_index_markdown(path: PurePosixPath) -> PurePosixPath:
    if path.name == "index.md":
        return path.parent
    return path


def _relative_uri(source: PurePosixPath, target: PurePosixPath) -> str:
    is_index = target.name == "index.md"
    target_value = target.parent.as_posix() if is_index else target.as_posix()
    relative = posixpath.relpath(target_value, start=source.parent.as_posix())
    if is_index:
        return "./" if relative == "." else relative.rstrip("/") + "/"
    return relative


def _redirect_target(redirect_path: PurePosixPath, canonical_path: PurePosixPath) -> str:
    target = _strip_index_markdown(canonical_path)
    relative = posixpath.relpath(target.as_posix(), start=redirect_path.parent.as_posix())
    return "./" if relative == "." else relative.rstrip("/") + "/"


def _service_label(taxonomy: Mapping[str, Any], slug: str) -> str:
    services = taxonomy.get("services", {})
    value = services.get(slug) if isinstance(services, Mapping) else None
    return value if isinstance(value, str) and value else slug


def _sample_cards(document_path: PurePosixPath, catalog: TopicCatalog, config: Mapping[str, Any]) -> str:
    samples = catalog.samples_by_document.get(document_path, ())
    if not samples:
        return ""

    repo_url = str(config.get("repo_url", "")).rstrip("/")
    if not repo_url:
        return ""
    docs_dir_value = str(config.get("docs_dir", "")).strip()
    docs_prefix = Path(docs_dir_value).name.strip("/") if docs_dir_value else ""
    cards: list[str] = [
        '<section class="dg-related-samples" aria-label="관련 샘플" data-search-exclude="true">'
    ]
    cards.append('<p class="dg-eyebrow">RELATED SAMPLES</p>')
    cards.append('<div class="dg-sample-grid" markdown="1">')
    for sample in samples:
        href = (
            f"{repo_url}/tree/main/"
            f"{(docs_prefix + '/' if docs_prefix else '')}{sample.relative_path.as_posix()}"
        )
        cards.append('<article class="dg-sample-card" markdown="1">')
        cards.append(f"### [{escape(sample.title)}]({escape(href, quote=True)})")
        cards.append("")
        cards.append(f'<p class="dg-doc-summary">{escape(sample.description)}</p>')
        cards.append(f'<p class="dg-card-count">{escape(sample.kind)}</p>')
        cards.append("</article>")
        cards.append("")
    cards.append("</div>")
    cards.append("</section>")
    return "\n".join(cards) + "\n"


def _topic_intro(current_path: PurePosixPath, catalog: TopicCatalog) -> str:
    topic = catalog.by_document.get(current_path)
    if topic is None or topic.entry.relative_path.parts[0] != "services":
        return ""
    member_paths = [member.relative_path for member in topic.members]
    if current_path not in member_paths or len(member_paths) <= 1:
        return ""

    position = catalog.position_by_document[current_path]
    topic_title = escape(str(topic.entry.metadata.get("title", "")))
    pieces: list[str] = []

    if position == 0:
        pieces.append('<aside class="dg-topic-overview" aria-label="주제 문서 목차">')
        pieces.append(f'<p class="dg-eyebrow">TOPIC · {len(topic.members)} DOCUMENTS</p>')
        pieces.append(f"<p>{topic_title} · {position + 1} / {len(topic.members)}</p>")
        pieces.append('<ol class="dg-topic-list">')
        for child in topic.members[1:]:
            href = _relative_uri(current_path, child.relative_path)
            pieces.append(
                "<li>"
                f'<a href="{escape(href, quote=True)}">{escape(str(child.metadata.get("title", "")))}</a>'
                "</li>"
            )
        pieces.append("</ol>")
        pieces.append("</aside>")
    else:
        pieces.append('<nav class="dg-topic-context" aria-label="현재 주제">')
        pieces.append(f"<span>{topic_title} · {position + 1} / {len(topic.members)}</span>")
        pieces.append(
            f'<a href="{escape(_relative_uri(current_path, topic.entry.relative_path), quote=True)}">'
            "전체 목차</a>"
        )
        pieces.append("</nav>")

    return "\n".join(pieces) + "\n"


def _topic_nav(current_path: PurePosixPath, catalog: TopicCatalog) -> str:
    topic = catalog.by_document.get(current_path)
    if topic is None or topic.entry.relative_path.parts[0] != "services":
        return ""
    member_paths = [member.relative_path for member in topic.members]
    if current_path not in member_paths or len(member_paths) <= 1:
        return ""

    position = catalog.position_by_document[current_path]
    topic_title = escape(str(topic.entry.metadata.get("title", "")))
    pieces: list[str] = ['<nav class="dg-topic-nav" aria-label="주제 내 문서 이동">']
    pieces.append(f"<span>{topic_title} · {position + 1} / {len(topic.members)}</span>")
    previous_member = topic.members[position - 1] if position else None
    next_member = topic.members[position + 1] if position + 1 < len(topic.members) else None
    if previous_member is not None:
        pieces.append(
            f'<a href="{escape(_relative_uri(current_path, previous_member.relative_path), quote=True)}">'
            "이전 문서</a>"
        )
    if next_member is not None:
        pieces.append(
            f'<a href="{escape(_relative_uri(current_path, next_member.relative_path), quote=True)}">'
            "다음 문서</a>"
        )
    pieces.append("</nav>")

    return "\n".join(pieces) + "\n"


def on_nav(nav: Navigation, config: Mapping[str, Any], files: Any) -> Navigation:
    """Place canonical topic packages under their primary service."""
    docs_dir = Path(config["docs_dir"])
    taxonomy = load_taxonomy(docs_dir.parent / "docs-taxonomy.yml")
    catalog = _topic_catalog_from_config(config)
    if catalog is None:
        return nav
    collections = {entry["path"] for entry in taxonomy["collections"].values()}
    collection_indexes = {f"{collection}/index.md" for collection in collections}
    pages_by_path = {page.file.src_uri: page for page in nav.pages}
    by_service: dict[str, list[tuple[str, StructureItem]]] = defaultdict(list)
    for topic in catalog.topics.values():
        entry_parts = topic.entry.relative_path.parts
        if entry_parts[0] == "services":
            member_pages: list[Page] = []
            for position, member in enumerate(topic.members):
                page = pages_by_path.get(member.relative_path.as_posix())
                if page is None:
                    continue
                if position:
                    page.title = f"{position}. {member.metadata.get('title', '')}"
                else:
                    page.title = str(member.metadata.get("title", page.title or ""))
                member_pages.append(page)
            if not member_pages:
                continue
            if len(member_pages) == 1:
                by_service[topic.primary_service].append(
                    (str(topic.entry.metadata.get("title", "")).casefold(), member_pages[0])
                )
            else:
                by_service[topic.primary_service].append(
                    (
                        str(topic.entry.metadata.get("title", "")).casefold(),
                        Section(str(topic.entry.metadata.get("title", "")), member_pages),
                    )
                )
            continue

    for page in nav.pages:
        page.parent = None
        page.previous_page = None
        page.next_page = None

    items: list[StructureItem] = []
    for item in nav.items:
        children = item.children if isinstance(item, Section) else [item]
        direct_pages = [child for child in children if isinstance(child, Page)]
        if any(page.file.src_uri in collection_indexes for page in direct_pages):
            continue
        if any(
            page.file.src_uri.startswith(("tags/", "articles/"))
            for page in direct_pages
        ):
            continue
        if isinstance(item, Section) and any(
            page.file.src_uri == "services/index.md" for page in direct_pages
        ):
            service_items: list[StructureItem] = [pages_by_path["services/index.md"]]
            services = taxonomy.get("services", {})
            ordered_slugs = sorted(
                set(services) | set(by_service),
                key=lambda value: _service_label(taxonomy, value).casefold(),
            )
            for slug in ordered_slugs:
                page = pages_by_path[f"services/{slug}/index.md"]
                documents = [entry for _, entry in sorted(by_service.get(slug, []), key=lambda value: value[0])]
                if not documents:
                    service_items.append(page)
                else:
                    service_items.append(Section(_service_label(taxonomy, slug), [page, *documents]))
            item.children = service_items
        items.append(item)

    pages = _navigation_pages(items)
    for index, page in enumerate(pages):
        page.previous_page = pages[index - 1] if index else None
        page.next_page = pages[index + 1] if index + 1 < len(pages) else None
    for topic in catalog.topics.values():
        if topic.entry.relative_path.parts[0] != "services":
            continue
        member_pages = [
            pages_by_path[member.relative_path.as_posix()]
            for member in topic.members
            if member.relative_path.as_posix() in pages_by_path
        ]
        for index, page in enumerate(member_pages):
            page.previous_page = member_pages[index - 1] if index else None
            page.next_page = member_pages[index + 1] if index + 1 < len(member_pages) else None
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

    taxonomy: Mapping[str, Any] = {}
    catalog: TopicCatalog | None = None
    current_path: PurePosixPath | None = None
    docs_dir_value = config.get("docs_dir")
    page_file = getattr(page, "file", None)
    src_uri = getattr(page_file, "src_uri", None)
    if isinstance(docs_dir_value, str) and isinstance(src_uri, str):
        docs_dir = Path(docs_dir_value)
        taxonomy = load_taxonomy(docs_dir.parent / "docs-taxonomy.yml")
        catalog = _topic_catalog_from_config(config)
        current_path = PurePosixPath(src_uri)
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
    if isinstance(tags, list) and tags and current_path is not None:
        intro += build_tag_links(
            current_path,
            [tag for tag in tags if isinstance(tag, str)],
            taxonomy,
        )
    if current_path is not None and catalog is not None:
        topic_context = _topic_intro(current_path, catalog)
        if topic_context:
            intro += topic_context
    if intro:
        markdown = _insert_after_title(markdown, intro)
    if current_path is not None and catalog is not None:
        topic_nav = _topic_nav(current_path, catalog)
        if topic_nav:
            markdown = markdown.rstrip() + "\n\n" + topic_nav
        sample_cards = _sample_cards(current_path, catalog, config)
        if sample_cards:
            markdown += "\n" + sample_cards
    if source_links:
        markdown = (
            markdown.rstrip()
            + '\n\n<details class="doc-sources">\n'
            + "<summary>참고 문서</summary>\n<ul>\n"
            + source_links
            + "\n</ul>\n</details>\n"
        )
    return markdown


def on_post_page(output: str, page: Any, config: Mapping[str, Any]) -> str:
    """Move generated redirect metadata into the final HTML head."""
    page_file = getattr(page, "file", None)
    src_uri = getattr(page_file, "src_uri", None)
    if not isinstance(src_uri, str):
        return output

    catalog = _topic_catalog_from_config(config)
    if catalog is None:
        return output

    redirect_path = PurePosixPath(src_uri)
    taxonomy = load_taxonomy(Path(config["docs_dir"]).parent / "docs-taxonomy.yml")
    destination = filter_redirect_targets(taxonomy).get(redirect_path)
    canonical_path = catalog.redirects.get(redirect_path)
    if destination is None and canonical_path is not None:
        destination = _redirect_target(redirect_path, canonical_path)
    if destination is None:
        return output

    target = escape(destination, quote=True)
    output = re.sub(
        r'<link rel="canonical" href="[^"]*"\s*/?>',
        f'<link rel="canonical" href="{target}">',
        output,
        count=1,
    )
    output = re.sub(
        r"<p>\s*<meta http-equiv=\"refresh\"[^>]*>\s*<link rel=\"canonical\"[^>]*>\s*</p>",
        "",
        output,
        count=1,
        flags=re.MULTILINE,
    )
    head_match = re.search(r"<head>(.*?)</head>", output, flags=re.DOTALL)
    head_html = head_match.group(1) if head_match else ""
    additions: list[str] = []
    if 'rel="canonical"' not in head_html:
        additions.append(f'<link rel="canonical" href="{target}">')
    if f'content="0; url={target}"' not in head_html:
        additions.append(f'<meta http-equiv="refresh" content="0; url={target}">')
    if additions:
        output = output.replace("</head>", "".join(item + "\n" for item in additions) + "</head>", 1)
    return output
