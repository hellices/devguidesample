"""MkDocs hooks for public document status and source provenance."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping


def _format_date(value: Any) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def _insert_after_title(markdown: str, block: str) -> str:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            lines[index + 1 : index + 1] = ["", block.rstrip(), ""]
            return "\n".join(lines).rstrip() + "\n"
    return block + "\n" + markdown


def on_page_markdown(markdown: str, page: Any, config: Mapping[str, Any], files: Any) -> str:
    """Render technical-page verification metadata into searchable content."""
    metadata = page.meta
    if not metadata.get("document_type"):
        return markdown

    status = metadata.get("verification_status")
    checked_at = _format_date(metadata.get("sources_checked_at", "unknown"))
    sources = metadata.get("official_sources", [])
    source_links = ", ".join(
        f"[{source['title']}]({source['url']})"
        for source in sources
        if isinstance(source, Mapping) and source.get("title") and source.get("url")
    )
    lines: list[str] = []
    if status == "needs-review":
        lines.extend(
            [
                '!!! warning "공식 문서 재검토 필요"',
                "    이 문서는 마이그레이션되었거나 공식 원문과의 의미 검증이 완료되지 않았습니다.",
                "",
            ]
        )
    description = metadata.get("description")
    if description:
        lines.extend([f"> {description}", ""])
    lines.extend(
        [
            '<div class="doc-verification" markdown>',
            f"- **공식 문서 검증:** `{status}`",
            f"- **출처 확인일:** {checked_at}",
            f"- **공식 근거:** {source_links or '등록되지 않음'}",
            "</div>",
        ]
    )
    return _insert_after_title(markdown, "\n".join(lines))
