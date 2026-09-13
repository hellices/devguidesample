"""Generate reader destinations and legacy indexes from public document metadata."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import html
from pathlib import Path, PurePosixPath
import posixpath
import sys
from typing import Any, Iterable, Mapping, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.docs.content import Document, iter_public_documents, load_taxonomy
from scripts.docs.topics import Topic, TopicCatalog, build_topic_catalog


# Static English eyebrow labels for each document type / overview page, matching
# the visual style already used on the hand-authored home template.
_EYEBROW_LABELS: dict[str, str] = {
    "case": "CASE FILES",
    "guide": "GUIDES",
    "lab": "LABS",
    "research": "RESEARCH",
}
_SERVICES_EYEBROW = "SERVICES"

# Raw metadata values are never surfaced verbatim when a friendlier label exists.
_STATUS_LABELS: dict[str, str] = {
    "resolved": "해결 기록",
    "unresolved": "조사 중",
    "historical": "과거 사례",
}

# document_type -> (metadata field holding the date, label for that date).
_DATE_FIELD_BY_TYPE: dict[str, tuple[str, str]] = {
    "case": ("occurred_at", "관측일"),
    "guide": ("last_verified", "최종 확인일"),
    "lab": ("last_verified", "최종 확인일"),
    "research": ("published_at", "게시일"),
}

_HOME_SLOTS = ("<!-- home:stats -->", "<!-- home:featured -->", "<!-- home:browse -->")


@dataclass(frozen=True)
class TopicMatch:
    topic: Topic
    matching_count: int


def _escape(value: Any) -> str:
    """Escape text for use inside raw (non-markdown) HTML."""
    return html.escape(str(value), quote=True)


def _md_label(value: Any) -> str:
    """Preserve plain-text metadata inside Markdown labels and headings."""
    text = html.escape(str(value), quote=False)
    for marker in ("\\", "[", "]", "`", "*", "_"):
        text = text.replace(marker, "\\" + marker)
    return text


def _relative_link(index_path: PurePosixPath, document: Document) -> str:
    return posixpath.relpath(
        document.relative_path.as_posix(), start=index_path.parent.as_posix()
    )


def _front_matter(title: str, description: str) -> str:
    rendered = yaml.safe_dump(
        {
            "title": title,
            "description": description,
            "hide": ["toc"],
        },
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip()
    return f"---\n{rendered}\n---\n\n"


def _label_for(vocabulary: Mapping[str, Any], slug: str) -> str:
    """Look up a taxonomy label, gracefully falling back to the raw slug."""
    label = vocabulary.get(slug) if isinstance(vocabulary, Mapping) else None
    return label if isinstance(label, str) and label else slug


def _metadata_values(document: Document, field: str) -> list[str]:
    values = document.metadata.get(field)
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(value for value in values if isinstance(value, str)))


def build_tag_links(
    index_path: PurePosixPath, tag_values: Sequence[str], taxonomy: Mapping[str, Any]
) -> str:
    tags = taxonomy.get("tags", {})
    links = []
    for tag in dict.fromkeys(tag_values):
        target = posixpath.relpath(f"tags/{tag}.md", start=index_path.parent.as_posix())
        links.append(f"[{_md_label(_label_for(tags, tag))}]({target}){{ .dg-tag }}")
    if not links:
        return ""
    return '<div class="dg-doc-tags" markdown="1">\n\n' + " ".join(links) + "\n\n</div>\n"


def _ordered_keys(present: Iterable[str], preferred_order: Iterable[str]) -> list[str]:
    """Order group keys by a preferred sequence, appending unknown keys alphabetically."""
    present_set = set(present)
    ordered = [key for key in preferred_order if key in present_set]
    known = set(ordered)
    ordered.extend(sorted(key for key in present_set if key not in known))
    return ordered


def _doc_meta_date(document: Document) -> str | None:
    document_type = document.metadata.get("document_type")
    field_and_label = _DATE_FIELD_BY_TYPE.get(document_type)
    if not field_and_label:
        return None
    field, label = field_and_label
    value = document.metadata.get(field)
    if value is None:
        return None
    formatted = value.isoformat() if hasattr(value, "isoformat") else str(value)
    if not formatted:
        return None
    return f"{label}: {formatted}"


def _doc_detail_spans(document: Document, taxonomy: Mapping[str, Any]) -> list[str]:
    """Build type-specific detail spans, never fabricating missing metadata."""
    metadata = document.metadata
    document_type = metadata.get("document_type")
    technologies = taxonomy.get("technologies", {})
    spans: list[str] = []

    if document_type == "case":
        status = metadata.get("status")
        if isinstance(status, str) and status:
            label = _STATUS_LABELS.get(status, status)
            spans.append(f"<span>{_escape(label)}</span>")
    elif document_type == "guide":
        applies_to = metadata.get("applies_to")
        if isinstance(applies_to, list) and applies_to:
            scopes = [str(item) for item in applies_to if str(item).strip() != "공식 원문 재검토 필요"]
            if scopes:
                spans.append(f"<span>적용 대상: {_escape(', '.join(scopes))}</span>")
    elif document_type == "lab":
        estimated_time = metadata.get("estimated_time")
        if isinstance(estimated_time, str) and estimated_time.strip():
            spans.append(f"<span>소요 시간: {_escape(estimated_time)}</span>")
        cost = metadata.get("cost")
        if isinstance(cost, str) and cost.strip():
            spans.append(f"<span>예상 비용: {_escape(cost)}</span>")
        cleanup_required = metadata.get("cleanup_required")
        if isinstance(cleanup_required, bool):
            state = "필요" if cleanup_required else "불필요"
            spans.append(f"<span>정리 절차: {state}</span>")
    elif document_type == "research":
        techs = metadata.get("technologies")
        if isinstance(techs, list) and techs:
            joined = ", ".join(_label_for(technologies, tech) for tech in techs if isinstance(tech, str))
            if joined:
                spans.append(f"<span>다룬 기술: {_escape(joined)}</span>")

    return spans


def _doc_card(
    index_path: PurePosixPath,
    document: Document,
    taxonomy: Mapping[str, Any],
    extra_classes: str = "",
) -> str:
    metadata = document.metadata
    document_type = metadata.get("document_type", "")
    link = _relative_link(index_path, document)
    title = metadata.get("title", "")
    description = metadata.get("description", "")
    services = taxonomy.get("services", {})
    service_label = " · ".join(
        _label_for(services, service) for service in _metadata_values(document, "services")
    )

    meta_spans = f'<span>{_escape(service_label)}</span>' if service_label else ""
    date_text = _doc_meta_date(document)
    if date_text:
        meta_spans += f'<span>{_escape(date_text)}</span>'

    tag_html = build_tag_links(index_path, _metadata_values(document, "tags")[:3], taxonomy)

    detail_spans = _doc_detail_spans(document, taxonomy)
    detail_html = ""
    if detail_spans:
        detail_html = f'\n<div class="dg-doc-details">\n{"".join(detail_spans)}\n</div>\n'

    classes = f"dg-doc-card dg-doc-card--{document_type}"
    if extra_classes:
        classes = f"{classes} {extra_classes}"

    return (
        f'<article class="{classes}" markdown="1">\n\n'
        f'<div class="dg-doc-meta">\n{meta_spans}\n</div>\n\n'
        f'### [{_md_label(title)}]({link})\n\n'
        f'<p class="dg-doc-summary">{_escape(description)}</p>\n'
        f'{tag_html}'
        f'{detail_html}'
        f'\n</article>\n'
    )


def _topic_match_key(topic: Topic) -> tuple[str, str]:
    return (topic.primary_service, topic.slug)


def _display_title(item: Document | TopicMatch) -> str:
    if isinstance(item, TopicMatch):
        return str(item.topic.entry.metadata.get("title", ""))
    return str(item.metadata.get("title", ""))


def _topic_tags(topic: Topic) -> list[str]:
    tags: list[str] = []
    for member in topic.members:
        tags.extend(_metadata_values(member, "tags"))
    return list(dict.fromkeys(tags))


def _topic_card(
    index_path: PurePosixPath,
    match: TopicMatch,
    taxonomy: Mapping[str, Any],
    *,
    extra_classes: str = "",
) -> str:
    topic = match.topic
    entry = topic.entry
    metadata = entry.metadata
    document_type = metadata.get("document_type", "")
    link = _relative_link(index_path, entry)
    title = metadata.get("title", "")
    description = metadata.get("description", "")
    services = taxonomy.get("services", {})
    if index_path.parts[:1] == ("services",) and len(index_path.parts) == 3:
        service_label = _label_for(services, index_path.parts[1])
    else:
        service_label = " · ".join(
            _label_for(services, service) for service in _metadata_values(entry, "services")
        )
    topic_count = len(topic.members)
    if match.matching_count == topic_count:
        count_label = f"{topic_count}개 문서"
    else:
        count_label = f"{match.matching_count} / {topic_count}개 문서 일치"

    meta_spans = ""
    if service_label:
        meta_spans += f"<span>{_escape(service_label)}</span>"
    meta_spans += f"<span>{_escape(count_label)}</span>"

    classes = f"dg-doc-card dg-topic-card dg-doc-card--{document_type}"
    if extra_classes:
        classes = f"{classes} {extra_classes}"

    tag_html = build_tag_links(index_path, _topic_tags(topic)[:3], taxonomy)
    return (
        f'<article class="{classes}" markdown="1">\n\n'
        f'<div class="dg-doc-meta">\n{meta_spans}\n</div>\n\n'
        f'### [{_md_label(title)}]({link})\n\n'
        f'<p class="dg-doc-summary">{_escape(description)}</p>\n'
        f"{tag_html}"
        f"\n</article>\n"
    )


def _collapse_documents(
    documents: Sequence[Document], catalog: TopicCatalog | None
) -> list[Document | TopicMatch]:
    if catalog is None:
        return sorted(documents, key=lambda document: str(document.metadata.get("title", "")).casefold())

    matched_paths: dict[tuple[str, str], set[PurePosixPath]] = {}
    standalone: dict[PurePosixPath, Document] = {}
    for document in documents:
        topic = catalog.by_document.get(document.relative_path)
        if topic is None:
            standalone.setdefault(document.relative_path, document)
            continue
        key = _topic_match_key(topic)
        member_paths = {member.relative_path for member in topic.members}
        if len(topic.members) <= 1:
            standalone.setdefault(
                document.relative_path if document.relative_path not in member_paths else topic.entry.relative_path,
                document if document.relative_path not in member_paths else topic.entry,
            )
            continue
        if document.relative_path not in member_paths:
            standalone.setdefault(document.relative_path, document)
            continue
        if topic.entry.relative_path.parts[0] != "services":
            standalone.setdefault(document.relative_path, document)
            continue
        matched_paths.setdefault(key, set()).add(document.relative_path)

    topic_matches = [
        TopicMatch(topic=catalog.topics[key], matching_count=len(paths))
        for key, paths in matched_paths.items()
    ]
    collapsed: list[Document | TopicMatch] = [*standalone.values(), *topic_matches]
    return sorted(collapsed, key=lambda item: _display_title(item).casefold())


def _visible_documents(
    documents: Sequence[Document], catalog: TopicCatalog | None
) -> list[Document]:
    return list(documents)


def _page_heading(eyebrow_prefix: str, count: int, title: str, description: str) -> str:
    eyebrow = f"{eyebrow_prefix} / {count} DOCUMENTS"
    return (
        '<div class="dg-page-heading" markdown="1">\n\n'
        f'<p class="dg-eyebrow">{_escape(eyebrow)}</p>\n\n'
        f'# {_md_label(title)}\n\n'
        f'<p class="dg-lead">{_escape(description)}</p>\n\n'
        '</div>\n'
    )


def _jump_links(entries: Sequence[tuple[str, str]]) -> str:
    """entries: sequence of (anchor, label) pairs, in display order."""
    if not entries:
        return ""
    links = " ".join(f"[{_md_label(label)}](#{anchor})" for anchor, label in entries)
    # A plain Markdown paragraph (not a raw <p>) so md_in_html re-processes the
    # links; python-markdown auto-wraps it in a <p> for the .dg-jump-links CSS.
    return f'<div class="dg-jump-links" markdown="1">\n\n{links}\n\n</div>\n'


def _empty_state(message: str) -> str:
    return f'<p class="dg-empty-state">{_escape(message)}</p>\n'


def _primary_service(document: Document, catalog: TopicCatalog | None) -> str | None:
    if catalog is not None:
        topic = catalog.by_document.get(document.relative_path)
        if topic is not None:
            return topic.primary_service
    parts = document.relative_path.parts
    return parts[1] if len(parts) >= 2 else None


def _document_grid(
    index_path: PurePosixPath,
    documents: list[Document],
    taxonomy: Mapping[str, Any],
    *,
    catalog: TopicCatalog | None = None,
) -> str:
    if not documents:
        return _empty_state("아직 등록된 문서가 없습니다.")
    cards = "\n".join(
        (
            _topic_card(index_path, item, taxonomy)
            if isinstance(item, TopicMatch)
            else _doc_card(index_path, item, taxonomy)
        )
        for item in _collapse_documents(documents, catalog)
    )
    return f'<div class="dg-doc-grid" markdown="1">\n\n{cards}\n</div>\n'


def _build_collection_page(
    document_type: str,
    config: Mapping[str, Any],
    matching: list[Document],
    taxonomy: Mapping[str, Any],
    *,
    catalog: TopicCatalog | None = None,
) -> tuple[PurePosixPath, str]:
    index_path = PurePosixPath(config["path"]) / "index.md"
    title = config.get("title", document_type)
    description = config.get("description", "")
    eyebrow_prefix = _EYEBROW_LABELS.get(document_type, str(document_type).upper())
    services = taxonomy.get("services", {})

    by_service: dict[str, list[Document]] = defaultdict(list)
    for document in matching:
        service = _primary_service(document, catalog)
        if service:
            by_service[service].append(document)

    ordered_service_keys = _ordered_keys(by_service.keys(), services.keys())

    body = _front_matter(title, description)
    body += f'<div class="dg-landing dg-collection dg-collection--{document_type}" markdown="1">\n\n'
    body += _page_heading(eyebrow_prefix, len(matching), title, description)
    body += "\n"

    if not matching:
        body += _empty_state("아직 등록된 문서가 없습니다.")
    else:
        jump_entries = [
            (f"service-{slug}", _label_for(services, slug)) for slug in ordered_service_keys
        ]
        body += _jump_links(jump_entries)
        body += "\n"
        for slug in ordered_service_keys:
            label = _label_for(services, slug)
            body += f"## {_md_label(label)} {{ #service-{slug} }}\n\n"
            body += '<div class="dg-doc-grid" markdown="1">\n\n'
            for item in _collapse_documents(by_service[slug], catalog):
                body += (
                    _topic_card(index_path, item, taxonomy)
                    if isinstance(item, TopicMatch)
                    else _doc_card(index_path, item, taxonomy)
                )
                body += "\n"
            body += "</div>\n\n"

    body += "</div>\n"
    return index_path, body


def _build_service_page(
    slug: str,
    matching: list[Document],
    taxonomy: Mapping[str, Any],
    *,
    page_path: PurePosixPath | None = None,
    catalog: TopicCatalog | None = None,
) -> tuple[PurePosixPath, str]:
    if page_path is None:
        page_path = PurePosixPath("services") / slug / "index.md"
    services = taxonomy.get("services", {})
    label = _label_for(services, slug)
    description = f"{label} 관련 설계·구현·운영 기록을 제목순으로 살펴보세요."

    body = _front_matter(label, description)
    body += '<div class="dg-landing dg-service" markdown="1">\n\n'
    body += _page_heading(_SERVICES_EYEBROW, len(matching), label, description)
    body += "\n"

    body += _document_grid(page_path, matching, taxonomy, catalog=catalog)
    body += "</div>\n"
    return page_path, body


def _build_services_overview_page(
    by_service: Mapping[str, list[Document]],
    taxonomy: Mapping[str, Any],
    total_documents: int,
) -> tuple[PurePosixPath, str]:
    services_path = PurePosixPath("services/index.md")
    services = taxonomy.get("services", {})
    title = "서비스별 보기"
    description = "사용 중인 서비스를 선택해 설계·구현·운영 기록을 살펴보세요."

    body = _front_matter(title, description)
    body += '<div class="dg-landing dg-services" markdown="1">\n\n'
    body += _page_heading(_SERVICES_EYEBROW, total_documents, title, description)
    body += "\n"

    if not services:
        available_slugs = sorted(by_service)
    else:
        available_slugs = _ordered_keys(set(services) | set(by_service), services.keys())
    if not available_slugs:
        body += _empty_state("아직 등록된 서비스가 없습니다.")
    else:
        # Nonempty services surface first (highest document count first, then
        # label) so zero-document services don't crowd out discovery; empty
        # services are still rendered afterward with an explicit 0 marker to
        # preserve their paths.
        ordered_slugs = sorted(
            available_slugs,
            key=lambda slug: (
                len(by_service.get(slug, [])) == 0,
                -len(by_service.get(slug, [])),
                _label_for(services, slug).casefold(),
            ),
        )
        body += '<div class="dg-service-grid" markdown="1">\n\n'
        for slug in ordered_slugs:
            label = _label_for(services, slug)
            matching = by_service.get(slug, [])
            body += '<article class="dg-service-card" markdown="1">\n\n'
            body += f"## [{_md_label(label)}]({slug}/index.md)\n\n"
            body += f'<p>{_escape(f"{len(matching)}개 문서")}</p>\n'
            body += "\n</article>\n\n"
        body += "</div>\n\n"

    body += "</div>\n"
    return services_path, body


def _build_tag_pages(
    documents: list[Document],
    taxonomy: Mapping[str, Any],
    *,
    catalog: TopicCatalog | None = None,
) -> dict[PurePosixPath, str]:
    by_tag: dict[str, list[Document]] = defaultdict(list)
    for document in documents:
        for tag in _metadata_values(document, "tags"):
            by_tag[tag].append(document)

    tags = taxonomy.get("tags", {})
    ordered_tags = sorted(by_tag, key=lambda tag: (_label_for(tags, tag).casefold(), tag))
    title = "태그별 보기"
    description = "태그를 선택하면 같은 주제를 다룬 글을 볼 수 있습니다."
    overview = _front_matter(title, description)
    overview += '<div class="dg-landing dg-tags" markdown="1">\n\n'
    overview += _page_heading("TAGS", len(documents), title, description)
    overview += "\n"
    pages: dict[PurePosixPath, str] = {}
    if not ordered_tags:
        overview += _empty_state("아직 사용 중인 태그가 없습니다.")
    else:
        overview += '<div class="dg-tag-grid" markdown="1">\n\n'
        for tag in ordered_tags:
            label = _label_for(tags, tag)
            matching = by_tag[tag]
            overview += '<article class="dg-tag-card" markdown="1">\n\n'
            overview += f"## [{_md_label(label)}]({tag}.md) {{ #tag:{tag} }}\n\n"
            overview += f"<p>{len(matching)}개 문서</p>\n\n</article>\n\n"

            page_path = PurePosixPath(f"tags/{tag}.md")
            tag_description = f"{label} 태그가 붙은 글을 제목순으로 모았습니다."
            body = _front_matter(label, tag_description)
            body += '<div class="dg-landing dg-tag-results" markdown="1">\n\n'
            body += _page_heading("TAG", len(matching), label, tag_description)
            body += '\n[모든 태그](index.md){ .dg-text-link }\n\n'
            body += _document_grid(page_path, matching, taxonomy, catalog=catalog)
            body += "</div>\n"
            pages[page_path] = body
        overview += "</div>\n"
    overview += "</div>\n"
    pages[PurePosixPath("tags/index.md")] = overview
    return pages


def _build_articles_page(
    documents: list[Document],
    taxonomy: Mapping[str, Any],
    *,
    catalog: TopicCatalog | None = None,
) -> tuple[PurePosixPath, str]:
    page_path = PurePosixPath("articles/index.md")
    title = "전체 글"
    description = "설계·구현·운영 기록을 제목순으로 살펴보세요. 서비스와 태그로도 찾아볼 수 있습니다."
    body = _front_matter(title, description)
    body += '<div class="dg-landing dg-articles" markdown="1">\n\n'
    body += _page_heading("ARTICLES", len(documents), title, description)
    body += '\n[서비스별 보기](../services/index.md){ .dg-text-link } · [태그별 보기](../tags/index.md){ .dg-text-link }\n\n'
    body += _document_grid(page_path, documents, taxonomy, catalog=catalog)
    body += "</div>\n"
    return page_path, body


def build_index_pages(
    documents: Iterable[Document],
    taxonomy: Mapping[str, Any],
    *,
    catalog: TopicCatalog | None = None,
) -> dict[PurePosixPath, str]:
    """Return virtual Markdown pages keyed by their docs-relative path."""
    docs = sorted(
        _visible_documents(list(documents), catalog),
        key=lambda item: str(item.metadata.get("title", "")).casefold(),
    )
    pages: dict[PurePosixPath, str] = {}
    collections = taxonomy.get("collections", {})

    for document_type, config in collections.items():
        matching = [doc for doc in docs if doc.metadata.get("document_type") == document_type]
        index_path, body = _build_collection_page(
            document_type, config, matching, taxonomy, catalog=catalog
        )
        pages[index_path] = body
        by_primary_service: dict[str, list[Document]] = defaultdict(list)
        for document in matching:
            service = _primary_service(document, catalog)
            if service:
                by_primary_service[service].append(document)
        for slug, service_docs in by_primary_service.items():
            # A real section index prevents Material from promoting the first bundle.
            service_path, service_body = _build_service_page(
                slug,
                service_docs,
                taxonomy,
                page_path=PurePosixPath(config["path"]) / slug / "index.md",
                catalog=catalog,
            )
            pages[service_path] = service_body

    by_service: dict[str, list[Document]] = defaultdict(list)
    for document in docs:
        for service in _metadata_values(document, "services"):
            by_service[service].append(document)

    services = taxonomy.get("services", {})
    for slug in _ordered_keys(set(services) | set(by_service), services.keys()):
        page_path, page_body = _build_service_page(
            slug,
            by_service.get(slug, []),
            taxonomy,
            catalog=catalog,
        )
        pages[page_path] = page_body

    services_path, services_body = _build_services_overview_page(by_service, taxonomy, len(docs))
    pages[services_path] = services_body
    pages.update(_build_tag_pages(docs, taxonomy, catalog=catalog))
    articles_path, articles_body = _build_articles_page(docs, taxonomy, catalog=catalog)
    pages[articles_path] = articles_body
    return pages


def _collection_order(taxonomy: Mapping[str, Any]) -> list[str]:
    collections = taxonomy.get("collections", {})
    return list(collections) if isinstance(collections, Mapping) else []


def _select_featured(documents: list[Document], taxonomy: Mapping[str, Any]) -> list[Document]:
    order = _collection_order(taxonomy)

    def sort_key(document: Document) -> tuple[int, str]:
        document_type = document.metadata.get("document_type")
        try:
            rank = order.index(document_type)
        except ValueError:
            rank = len(order)
        return rank, str(document.metadata.get("title", "")).casefold()

    ordered = sorted(documents, key=sort_key)
    featured = [doc for doc in ordered if doc.metadata.get("featured") is True][:3]
    if featured:
        return featured

    selected: list[Document] = []
    seen_types: set[Any] = set()
    for document_type in order:
        if len(selected) >= 3:
            break
        for document in ordered:
            if document.metadata.get("document_type") != document_type:
                continue
            if document in selected:
                continue
            selected.append(document)
            seen_types.add(document_type)
            break

    if len(selected) < 3:
        for document in ordered:
            if len(selected) >= 3:
                break
            if document in selected:
                continue
            selected.append(document)

    return selected[:3]


def _feature_card(
    document: Document | TopicMatch, taxonomy: Mapping[str, Any]
) -> str:
    index_path = PurePosixPath("index.md")
    if isinstance(document, TopicMatch):
        return _topic_card(index_path, document, taxonomy, extra_classes="dg-feature-card")
    return _doc_card(index_path, document, taxonomy, extra_classes="dg-feature-card")


def _build_home_stats(documents: list[Document]) -> str:
    total = len(documents)
    used_services: set[str] = set()
    for document in documents:
        services_meta = document.metadata.get("services")
        if isinstance(services_meta, list):
            used_services.update(service for service in services_meta if isinstance(service, str))
    used_tags = {tag for document in documents for tag in _metadata_values(document, "tags")}

    stats = [
        (total, "전체 문서"),
        (len(used_services), "다루는 서비스"),
        (len(used_tags), "다루는 태그"),
    ]
    body = '<div class="dg-stats" markdown="1">\n\n'
    for number, label in stats:
        body += (
            '<div class="dg-stat">'
            f"<strong>{_escape(number)}</strong>"
            f"<span>{_escape(label)}</span>"
            "</div>\n"
        )
    body += "\n</div>\n"
    return body


def _build_home_featured(
    documents: list[Document],
    taxonomy: Mapping[str, Any],
    *,
    catalog: TopicCatalog | None = None,
) -> str:
    selected = _select_featured(documents, taxonomy)
    if not selected:
        return _empty_state("아직 소개할 문서가 없습니다.")

    body = '<div class="dg-feature-grid" markdown="1">\n\n'
    for item in _collapse_documents(selected, catalog):
        body += _feature_card(item, taxonomy)
        body += "\n"
    body += "</div>\n"
    return body


def _build_home_browse(documents: list[Document]) -> str:
    used_services = {service for document in documents for service in _metadata_values(document, "services")}
    used_tags = {tag for document in documents for tag in _metadata_values(document, "tags")}
    destinations = (
        ("services", "SERVICES", "서비스별 보기", "사용 중인 서비스의 설계·구현·운영 기록을 함께 읽습니다.", f"{len(used_services)}개 서비스"),
        ("tags", "TAGS", "태그별 보기", "관심 있는 주제를 선택해 같은 태그가 붙은 글을 모아 봅니다.", f"{len(used_tags)}개 태그"),
        ("articles", "ARTICLES", "전체 글", "모든 기록을 제목순으로 살펴봅니다.", f"{len(documents)}개 문서"),
    )
    body = '<div class="dg-browse-grid" markdown="1">\n\n'
    for path, eyebrow, title, description, count in destinations:
        body += '<article class="dg-browse-card" markdown="1">\n\n'
        body += f'<p class="dg-eyebrow">{eyebrow}</p>\n\n'
        body += f"### [{_md_label(title)}]({path}/index.md)\n\n"
        body += f'<p class="dg-doc-summary">{_escape(description)}</p>\n'
        body += f'<p class="dg-card-count">{_escape(count)}</p>\n\n'
        body += "</article>\n\n"
    body += "</div>\n"
    return body


def build_redirect_pages(catalog: TopicCatalog) -> dict[PurePosixPath, str]:
    pages: dict[PurePosixPath, str] = {}
    front_matter = yaml.safe_dump(
        {
            "title": "문서 이동",
            "search": {"exclude": True},
            "hide": ["navigation", "toc"],
        },
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip()
    for redirect_path, canonical_path in sorted(catalog.redirects.items()):
        target = posixpath.relpath(
            canonical_path.parent.as_posix(), start=redirect_path.parent.as_posix()
        ).rstrip("/") + "/"
        label = canonical_path.as_posix()
        pages[redirect_path] = (
            f"---\n{front_matter}\n---\n\n"
            f'<meta http-equiv="refresh" content="0; url={_escape(target)}">\n'
            f'<link rel="canonical" href="{_escape(target)}">\n\n'
            "# 문서 이동\n\n"
            "이 문서는 새 위치로 이동했습니다.\n\n"
            f'<p><a href="{_escape(target)}">{_escape(label)}</a></p>\n'
        )
    return pages


def build_home_page(
    template: str,
    documents: Iterable[Document],
    taxonomy: Mapping[str, Any],
    *,
    catalog: TopicCatalog | None = None,
) -> str:
    """Render the home landing page by filling metadata-driven slots in ``template``."""
    for slot in _HOME_SLOTS:
        occurrences = template.count(slot)
        if occurrences == 0:
            raise ValueError(f"home template is missing required slot: {slot}")
        if occurrences > 1:
            raise ValueError(f"home template has duplicate slot: {slot}")

    docs = sorted(
        _visible_documents(list(documents), catalog),
        key=lambda item: str(item.metadata.get("title", "")).casefold(),
    )

    rendered = template
    rendered = rendered.replace("<!-- home:stats -->", _build_home_stats(docs), 1)
    rendered = rendered.replace(
        "<!-- home:featured -->",
        _build_home_featured(docs, taxonomy, catalog=catalog),
        1,
    )
    rendered = rendered.replace(
        "<!-- home:browse -->", _build_home_browse(docs), 1
    )
    return rendered


def write_generated_pages(repo_root: Path | None = None) -> None:
    """Write virtual pages through mkdocs-gen-files during a site build."""
    import mkdocs_gen_files

    root = repo_root or REPO_ROOT
    taxonomy = load_taxonomy(root / "docs-taxonomy.yml")
    public_documents = list(iter_public_documents(root / "docs", taxonomy))
    catalog = build_topic_catalog(root / "docs", taxonomy, documents=public_documents)
    documents = list(catalog.documents)

    for path, content in build_index_pages(documents, taxonomy, catalog=catalog).items():
        with mkdocs_gen_files.open(path.as_posix(), "w") as generated:
            generated.write(content)
    for path, content in build_redirect_pages(catalog).items():
        with mkdocs_gen_files.open(path.as_posix(), "w") as generated:
            generated.write(content)

    template = (root / "docs" / "index.md").read_text(encoding="utf-8")
    home_page = build_home_page(template, documents, taxonomy, catalog=catalog)
    with mkdocs_gen_files.open("index.md", "w") as generated:
        generated.write(home_page)


if __name__ == "__main__" or __name__.startswith("<"):
    write_generated_pages()
