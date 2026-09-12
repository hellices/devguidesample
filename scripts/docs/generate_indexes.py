"""Generate collection, service, and home landing pages from public document metadata."""

from __future__ import annotations

from collections import defaultdict
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

_HOME_SLOTS = ("<!-- home:stats -->", "<!-- home:featured -->", "<!-- home:collections -->")


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


def _collection_title(taxonomy: Mapping[str, Any], document_type: Any) -> str:
    collections = taxonomy.get("collections", {})
    config = collections.get(document_type) if isinstance(collections, Mapping) else None
    if isinstance(config, Mapping):
        title = config.get("title")
        if isinstance(title, str) and title:
            return title
    return str(document_type)


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
            joined = ", ".join(str(item) for item in applies_to)
            spans.append(f"<span>적용 대상: {_escape(joined)}</span>")
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
    collection_label = _collection_title(taxonomy, document_type)
    link = _relative_link(index_path, document)
    title = metadata.get("title", "")
    description = metadata.get("description", "")
    tags = taxonomy.get("tags", {})

    meta_spans = f'<span>{_escape(collection_label)}</span>'
    date_text = _doc_meta_date(document)
    if date_text:
        meta_spans += f'<span>{_escape(date_text)}</span>'

    tag_values = metadata.get("tags")
    tag_html = ""
    if isinstance(tag_values, list) and tag_values:
        tag_spans = "".join(
            f'<span class="dg-tag">{_escape(_label_for(tags, tag))}</span>'
            for tag in tag_values[:3]
            if isinstance(tag, str)
        )
        if tag_spans:
            tag_html = f'\n<div class="dg-doc-tags">\n{tag_spans}\n</div>\n'

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


def _build_collection_page(
    document_type: str,
    config: Mapping[str, Any],
    matching: list[Document],
    taxonomy: Mapping[str, Any],
) -> tuple[PurePosixPath, str]:
    index_path = PurePosixPath(config["path"]) / "index.md"
    title = config.get("title", document_type)
    description = config.get("description", "")
    eyebrow_prefix = _EYEBROW_LABELS.get(document_type, str(document_type).upper())
    services = taxonomy.get("services", {})

    by_service: dict[str, list[Document]] = defaultdict(list)
    for document in matching:
        parts = document.relative_path.parts
        if len(parts) >= 2:
            by_service[parts[1]].append(document)

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
            for document in by_service[slug]:
                body += _doc_card(index_path, document, taxonomy)
                body += "\n"
            body += "</div>\n\n"

    body += "</div>\n"
    return index_path, body


def _build_service_page(
    slug: str,
    matching: list[Document],
    taxonomy: Mapping[str, Any],
) -> tuple[PurePosixPath, str]:
    page_path = PurePosixPath(f"services/{slug}.md")
    services = taxonomy.get("services", {})
    collections = taxonomy.get("collections", {})
    label = _label_for(services, slug)
    description = f"{label}을 다룬 기록입니다. 지금 겪는 문제나 구현하려는 작업에 맞는 글부터 살펴보세요."

    body = _front_matter(label, description)
    body += '<div class="dg-landing dg-service" markdown="1">\n\n'
    body += _page_heading(_SERVICES_EYEBROW, len(matching), label, description)
    body += "\n"

    if not matching:
        body += _empty_state("아직 등록된 문서가 없습니다.")
    else:
        by_type: dict[str, list[Document]] = defaultdict(list)
        for document in matching:
            by_type[document.metadata.get("document_type")].append(document)
        for document_type in collections:
            typed = by_type.get(document_type, [])
            if not typed:
                continue
            group_title = _collection_title(taxonomy, document_type)
            body += f"## {_md_label(group_title)}\n\n"
            body += '<div class="dg-doc-grid" markdown="1">\n\n'
            for document in typed:
                body += _doc_card(page_path, document, taxonomy)
                body += "\n"
            body += "</div>\n\n"

    body += "</div>\n"
    return page_path, body


def _build_services_overview_page(
    by_service: Mapping[str, list[Document]],
    taxonomy: Mapping[str, Any],
    total_documents: int,
) -> tuple[PurePosixPath, str]:
    services_path = PurePosixPath("services/index.md")
    services = taxonomy.get("services", {})
    collections = taxonomy.get("collections", {})
    title = "서비스별 찾기"
    description = "사용 중인 서비스에서 출발하세요. 기록이 많은 순서로 살펴보고, 필요한 문제 해결·구현·비교 자료로 이어갈 수 있습니다."

    body = _front_matter(title, description)
    body += '<div class="dg-landing dg-services" markdown="1">\n\n'
    body += _page_heading(_SERVICES_EYEBROW, total_documents, title, description)
    body += "\n"

    if not services:
        body += _empty_state("아직 등록된 서비스가 없습니다.")
    else:
        # Nonempty services surface first (highest document count first, then
        # label) so zero-document services don't crowd out discovery; empty
        # services are still rendered afterward with an explicit 0 marker to
        # preserve their paths.
        ordered_slugs = sorted(
            services,
            key=lambda slug: (
                len(by_service.get(slug, [])) == 0,
                -len(by_service.get(slug, [])),
                _label_for(services, slug).casefold(),
            ),
        )
        body += '<div class="dg-service-grid" markdown="1">\n\n'
        for slug in ordered_slugs:
            label = services[slug]
            matching = by_service.get(slug, [])
            body += '<article class="dg-service-card" markdown="1">\n\n'
            body += f"## [{_md_label(label)}]({slug}.md)\n\n"
            body += f'<p>{_escape(f"{len(matching)}개 문서")}</p>\n'
            per_type_counts = [
                (document_type, sum(1 for doc in matching if doc.metadata.get("document_type") == document_type))
                for document_type in collections
            ]
            present_counts = [(document_type, count) for document_type, count in per_type_counts if count]
            if present_counts:
                items = "".join(
                    f"<li>{_escape(_collection_title(taxonomy, document_type))} {count}</li>"
                    for document_type, count in present_counts
                )
                body += f"<ul>\n{items}\n</ul>\n"
            body += "\n</article>\n\n"
        body += "</div>\n\n"

    body += "</div>\n"
    return services_path, body


def build_index_pages(
    documents: Iterable[Document], taxonomy: Mapping[str, Any]
) -> dict[PurePosixPath, str]:
    """Return virtual Markdown pages keyed by their docs-relative path."""
    docs = sorted(documents, key=lambda item: str(item.metadata.get("title", "")).casefold())
    pages: dict[PurePosixPath, str] = {}
    collections = taxonomy.get("collections", {})

    for document_type, config in collections.items():
        matching = [doc for doc in docs if doc.metadata.get("document_type") == document_type]
        index_path, body = _build_collection_page(document_type, config, matching, taxonomy)
        pages[index_path] = body

    by_service: dict[str, list[Document]] = defaultdict(list)
    for document in docs:
        services_meta = document.metadata.get("services")
        if isinstance(services_meta, list):
            for service in services_meta:
                if isinstance(service, str):
                    by_service[service].append(document)

    services = taxonomy.get("services", {})
    for slug in services:
        page_path, page_body = _build_service_page(slug, by_service.get(slug, []), taxonomy)
        pages[page_path] = page_body

    services_path, services_body = _build_services_overview_page(by_service, taxonomy, len(docs))
    pages[services_path] = services_body
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


def _feature_card(document: Document, taxonomy: Mapping[str, Any]) -> str:
    index_path = PurePosixPath("index.md")
    return _doc_card(index_path, document, taxonomy, extra_classes="dg-feature-card")


def _build_home_stats(documents: list[Document]) -> str:
    total = len(documents)
    used_services: set[str] = set()
    for document in documents:
        services_meta = document.metadata.get("services")
        if isinstance(services_meta, list):
            used_services.update(service for service in services_meta if isinstance(service, str))
    used_types = {
        document.metadata.get("document_type")
        for document in documents
        if document.metadata.get("document_type")
    }

    stats = [
        (total, "전체 문서"),
        (len(used_services), "다루는 서비스"),
        (len(used_types), "문서 유형"),
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


def _build_home_featured(documents: list[Document], taxonomy: Mapping[str, Any]) -> str:
    selected = _select_featured(documents, taxonomy)
    if not selected:
        return _empty_state("아직 소개할 문서가 없습니다.")

    body = '<div class="dg-feature-grid" markdown="1">\n\n'
    for document in selected:
        body += _feature_card(document, taxonomy)
        body += "\n"
    body += "</div>\n"
    return body


def _build_home_collections(documents: list[Document], taxonomy: Mapping[str, Any]) -> str:
    collections = taxonomy.get("collections", {})
    if not collections:
        return _empty_state("아직 등록된 컬렉션이 없습니다.")

    body = '<div class="dg-collection-grid" markdown="1">\n\n'
    for document_type, config in collections.items():
        count = sum(1 for doc in documents if doc.metadata.get("document_type") == document_type)
        path = config.get("path", document_type)
        title = config.get("title", document_type)
        description = config.get("description", "")
        body += f'<article class="dg-collection-card dg-collection-card--{document_type}" markdown="1">\n\n'
        body += f'<p class="dg-eyebrow">{_escape(_EYEBROW_LABELS.get(document_type, str(document_type).upper()))}</p>\n\n'
        body += f"### [{_md_label(title)}]({path}/index.md)\n\n"
        body += f'<p class="dg-doc-summary">{_escape(description)}</p>\n'
        body += f'<p class="dg-card-count">{_escape(f"{count}개 문서")}</p>\n\n'
        body += "</article>\n\n"
    body += "</div>\n"
    return body


def build_home_page(
    template: str, documents: Iterable[Document], taxonomy: Mapping[str, Any]
) -> str:
    """Render the home landing page by filling metadata-driven slots in ``template``."""
    for slot in _HOME_SLOTS:
        occurrences = template.count(slot)
        if occurrences == 0:
            raise ValueError(f"home template is missing required slot: {slot}")
        if occurrences > 1:
            raise ValueError(f"home template has duplicate slot: {slot}")

    docs = sorted(documents, key=lambda item: str(item.metadata.get("title", "")).casefold())

    rendered = template
    rendered = rendered.replace("<!-- home:stats -->", _build_home_stats(docs), 1)
    rendered = rendered.replace("<!-- home:featured -->", _build_home_featured(docs, taxonomy), 1)
    rendered = rendered.replace(
        "<!-- home:collections -->", _build_home_collections(docs, taxonomy), 1
    )
    return rendered


def write_generated_pages(repo_root: Path | None = None) -> None:
    """Write virtual pages through mkdocs-gen-files during a site build."""
    import mkdocs_gen_files

    root = repo_root or REPO_ROOT
    taxonomy = load_taxonomy(root / "docs-taxonomy.yml")
    documents = list(iter_public_documents(root / "docs", taxonomy))

    for path, content in build_index_pages(documents, taxonomy).items():
        with mkdocs_gen_files.open(path.as_posix(), "w") as generated:
            generated.write(content)

    template = (root / "docs" / "index.md").read_text(encoding="utf-8")
    home_page = build_home_page(template, documents, taxonomy)
    with mkdocs_gen_files.open("index.md", "w") as generated:
        generated.write(home_page)


if __name__ == "__main__" or __name__.startswith("<"):
    write_generated_pages()
