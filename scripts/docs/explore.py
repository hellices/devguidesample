"""Pre-rendered topic discovery and taxonomy-owned compatibility redirects."""

from __future__ import annotations

from html import escape
import json
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

import yaml

from scripts.docs.content import Document
from scripts.docs.topics import TopicCatalog


def topic_groups(
    documents: Sequence[Document], catalog: TopicCatalog | None
) -> list[tuple[Document, list[Document]]]:
    groups: dict[PurePosixPath, tuple[Document, list[Document]]] = {}
    for document in documents:
        topic = catalog.by_document.get(document.relative_path) if catalog else None
        entry = topic.entry if topic else document
        _, members = groups.setdefault(entry.relative_path, (entry, []))
        if document not in members:
            members.append(document)
    if catalog:
        for entry, members in groups.values():
            members.sort(key=lambda doc: catalog.position_by_document.get(doc.relative_path, 0))
    return sorted(groups.values(), key=lambda group: str(group[0].metadata.get("title", "")).casefold())


def count_label(documents: Sequence[Document], catalog: TopicCatalog | None) -> str:
    return f"{len(topic_groups(documents, catalog))}개 주제 · {len(documents)}개 문서"


def _options(field: str, values: Sequence[str], vocabulary: Mapping[str, Any]) -> str:
    return '<div class="dg-filter-options">\n' + "\n".join(
        f'<label class="dg-filter-option"><input type="checkbox" name="{field}" '
        f'value="{escape(value, quote=True)}"><span>{escape(str(vocabulary.get(value, value)))}</span></label>'
        for value in values
    ) + "\n</div>\n"


def build_explore_page(
    documents: Sequence[Document], taxonomy: Mapping[str, Any], catalog: TopicCatalog | None
) -> str:
    description = "서비스·목적·주제·기술과 제목·설명으로 모든 주제를 찾습니다. 선택한 조건을 모두 갖춘 문서만 주제 안에 표시합니다."
    metadata = yaml.safe_dump(
        {"title": "글 찾기", "description": description, "hide": ["toc"]},
        allow_unicode=True, sort_keys=False,
    )
    pieces = [
        f"---\n{metadata}---\n\n# 글 찾기\n",
        '<div class="dg-landing dg-explore" data-explore>',
        f'<p class="dg-lead">{description}</p>',
        "<noscript>JavaScript가 꺼져 있어 필터를 사용할 수 없습니다. 모든 주제와 문서 링크를 표시합니다.</noscript>",
        '<form class="dg-explore-filters" data-explore-form aria-label="글 찾기 필터">',
        '<label class="dg-explore-search" for="explore-query">제목·설명 검색</label>',
        '<input id="explore-query" type="search" name="text" placeholder="제목 또는 설명의 단어" aria-describedby="explore-help">',
        '<p id="explore-help">여러 조건은 AND로 적용합니다. 한 문서가 선택한 모든 조건을 충족해야 합니다.</p>',
    ]
    for field, plural, label in (("service", "services", "서비스"), ("tag", "tags", "태그"), ("technology", "technologies", "기술")):
        vocabulary = taxonomy.get(plural, {})
        pieces.append(f"<fieldset><legend>{label}</legend>")
        if field == "tag" and taxonomy.get("tag_groups"):
            for group in taxonomy["tag_groups"].values():
                pieces.append(f'<fieldset><legend>{escape(group["label"])}</legend>')
                pieces.append(_options(field, group["tags"], vocabulary))
                pieces.append("</fieldset>")
        else:
            pieces.append(_options(field, list(vocabulary), vocabulary))
        pieces.append("</fieldset>")
    pieces.extend([
        '<button type="reset" class="dg-explore-reset">필터 초기화</button>',
        "</form>",
        '<p data-explore-alert role="alert" hidden></p>',
        '<div class="dg-explore-status" role="status" aria-live="polite" aria-atomic="true">',
        f'<p data-explore-count>{count_label(documents, catalog)}</p>',
        '<p data-explore-summary>모든 주제 · 선택한 조건 없음</p>',
        "</div>",
        '<p class="dg-empty-state" data-explore-empty hidden>일치하는 문서가 없습니다. 조건을 줄이거나 필터를 초기화하세요.</p>',
        '<div class="dg-explore-results">',
    ])
    for entry, members in topic_groups(documents, catalog):
        topic_id = entry.relative_path.parent.as_posix()
        pieces.extend([
            f'<article class="dg-explore-topic" data-explore-topic="{escape(topic_id, quote=True)}">',
            f'<h2>{escape(str(entry.metadata.get("title", "")))}</h2>',
            f'<p class="dg-card-count" data-explore-topic-count>{len(members)}개 문서</p>',
            '<ul class="dg-explore-members">',
        ])
        for member in members:
            metadata = member.metadata
            attributes = {
                "data-explore-member": member.relative_path.as_posix(),
                **{
                    f"data-{field}": json.dumps(metadata.get(field, []), ensure_ascii=False)
                    for field in ("services", "tags", "technologies")
                },
                "data-search": f'{metadata.get("title", "")}\n{metadata.get("description", "")}',
            }
            attrs = " ".join(f'{key}="{escape(value, quote=True)}"' for key, value in attributes.items())
            target = "../" + member.relative_path.parent.as_posix() + "/"
            services = " · ".join(
                str(taxonomy.get("services", {}).get(slug, slug))
                for slug in metadata.get("services", [])
            )
            pieces.extend([
                f'<li class="dg-explore-member" {attrs}>',
                f'<h3><a href="{escape(target, quote=True)}">{escape(str(metadata.get("title", "")))}</a></h3>',
                f'<p class="dg-doc-summary">{escape(str(metadata.get("description", "")))}</p>',
                f'<p class="dg-doc-meta">{escape(services)}</p>',
                '<div class="dg-doc-tags">',
            ])
            for tag in metadata.get("tags", []):
                href = "./?" + urlencode({"tag": tag})
                label = str(taxonomy.get("tags", {}).get(tag, tag))
                pieces.append(f'<a class="dg-tag" href="{escape(href, quote=True)}">{escape(label)}</a>')
            pieces.extend(["</div>", "</li>"])
        pieces.extend(["</ul>", "</article>"])
    pieces.extend(["</div>", "</div>\n"])
    return "\n".join(pieces)


def filter_redirect_targets(taxonomy: Mapping[str, Any]) -> dict[PurePosixPath, str]:
    targets = {
        PurePosixPath("tags/index.md"): "../explore/",
        PurePosixPath("articles/index.md"): "../explore/",
    }
    for slug, filters in taxonomy.get("legacy_tag_redirects", {}).items():
        targets[PurePosixPath(f"tags/{slug}.md")] = "../../explore/?" + urlencode(filters, doseq=True)
    return targets


def build_filter_redirect_pages(taxonomy: Mapping[str, Any]) -> dict[PurePosixPath, str]:
    front_matter = yaml.safe_dump(
        {"title": "글 찾기로 이동", "search": {"exclude": True}, "hide": ["navigation", "toc"]},
        allow_unicode=True, sort_keys=False,
    )
    return {
        path: (
            f"---\n{front_matter}---\n\n"
            f'<meta http-equiv="refresh" content="0; url={escape(target, quote=True)}">\n'
            f'<link rel="canonical" href="{escape(target, quote=True)}">\n\n'
            "# 글 찾기로 이동\n\n"
            f'<p><a href="{escape(target, quote=True)}">글 찾기에서 모든 주제 살펴보기</a></p>\n'
        )
        for path, target in filter_redirect_targets(taxonomy).items()
    }
