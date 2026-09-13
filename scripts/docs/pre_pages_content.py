"""Source-structure preservation against the fixed pre-Pages Git baseline."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from hashlib import sha256
from html import escape, unescape
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
from typing import Mapping
from types import MappingProxyType
import unicodedata
from urllib.parse import unquote, urlsplit

import markdown
from markdown.blockprocessors import ReferenceProcessor

from scripts.docs.pre_pages import (
    AuditFormatError,
    FileEvidence,
    PrePagesInventory,
    ReviewedChange,
    STRUCTURE_CATEGORIES,
    StructureEvidence,
    git_text,
    resolve_current_documents,
    resolve_public_evidence_files,
    validate_reviewed_changes,
)


@dataclass(frozen=True)
class MarkdownStructure:
    title: str
    headings: tuple[str, ...]
    prose: tuple[str, ...]
    code: tuple[str, ...]
    tables: tuple[str, ...]
    images: tuple[str, ...]
    local_link_labels: tuple[str, ...]
    links: tuple[str, ...] = ()


@dataclass(frozen=True)
class StructureFinding:
    category: str
    fingerprint: str
    excerpt: str


@dataclass(frozen=True)
class DocumentPreservation:
    baseline_path: PurePosixPath
    current_path: PurePosixPath
    status: str
    text_similarity: float
    missing: tuple[StructureFinding, ...]
    reviewed: tuple[StructureFinding, ...]


_DESTINATION = r'(<[^>\n]*>|(?:\\.|[^\s()\\]|\([^()\n]*\))*)'
_LINK_END = r'''(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*\)'''
_LINK = re.compile(
    r'(!?)\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]\(\s*' + _DESTINATION
    + _LINK_END
)
_IMAGE = re.compile(r'!\[([^\[\]]*)\]\(\s*' + _DESTINATION + _LINK_END)
_REFERENCE = re.compile(r"(!?)\[([^\[\]]+)\](?:\[([^\[\]]*)\])?")
_DEFINITION = ReferenceProcessor.RE
_HTML_TAG = re.compile(
    r"""</?([A-Za-z][A-Za-z0-9:_-]*)(?=[\s/>])(?:"[^"]*"|'[^']*'|[^'">])*>""",
    re.DOTALL,
)
_HTML_OPEN = re.compile(r"</?[A-Za-z][A-Za-z0-9:_-]*(?=[\s/>])")
_AUTOLINK = re.compile(r"<((?:https?://|mailto:)[^<>\s]+)>", re.IGNORECASE)
_FENCE_OPEN = re.compile(r"((?:[ \t]{0,3}>[ \t]?)*)([ \t]*)(`{3,}|~{3,})(.*)")
_PRESENTATION_TAGS = frozenset((
    "div", "section", "article", "aside", "nav", "p", "span", "strong",
    "em", "b", "i", "a", "ol", "ul", "li", "br",
))
_RAW_TAGS = frozenset((
    "script", "style", "code", "pre", "textarea", "title", "xmp", "iframe",
    "noembed", "noframes", "noscript", "template", "plaintext",
))
_TEXT_RAW_TAGS = _RAW_TAGS - {"code", "pre", "template"}
_WRAPPER = re.compile(
    r"</?(?:div|section|article|aside|nav|p|span|strong|em|b|i|a|ol|ul|li|br)\b[^>]*>",
    re.IGNORECASE,
)
# Source-semantic subset of mkdocs.yml, shared with renderer-oracle tests:
# attr_list changes final href/src/alt; md_in_html enables nested Markdown.
# tables/admonition/details/tabbed/tasklist expose source content in containers.
# highlight/inlinehilite/superfences identify code that must not supply evidence.
# Coloring is disabled only for speed; generated code markup is ignored either way.
SEMANTIC_MARKDOWN_CONFIG = MappingProxyType({
    "extensions": (
        "admonition", "attr_list", "md_in_html", "tables", "pymdownx.details",
        "pymdownx.highlight", "pymdownx.inlinehilite", "pymdownx.superfences",
        "pymdownx.tabbed", "pymdownx.tasklist",
    ),
    "extension_configs": MappingProxyType({
        "pymdownx.highlight": MappingProxyType({"anchor_linenums": True, "use_pygments": False}),
        "pymdownx.tabbed": MappingProxyType({"alternate_style": True}),
        "pymdownx.tasklist": MappingProxyType({"custom_checkbox": True}),
    }),
})
SEMANTIC_MARKDOWN_EXCLUSIONS = MappingProxyType({
    "toc": "Generated TOC/permalink navigation is not authored evidence; source headings are compared separately.",
    "pymdownx.snippets": "File inclusion has side effects; no snippet directives occur in the audited source corpus.",
})
_VOID_TAGS = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"))
_HIDDEN_TAGS = frozenset(("script", "style", "template", "iframe", "noembed", "noframes", "noscript", "title"))


def create_semantic_renderer() -> markdown.Markdown:
    """Build a fresh renderer from the single audited, side-effect-free site configuration."""
    return markdown.Markdown(
        extensions=list(SEMANTIC_MARKDOWN_CONFIG["extensions"]),
        extension_configs={
            name: dict(options)
            for name, options in SEMANTIC_MARKDOWN_CONFIG["extension_configs"].items()
        },
    )


def _space(text: str) -> str:
    return " ".join(text.split())


def _escaped_match(match: re.Match) -> bool:
    prefix = match.string[:match.start()]
    return (len(prefix) - len(prefix.rstrip("\\"))) % 2 == 1


@dataclass(frozen=True)
class _CodeSpan:
    start: int
    end: int
    value: str


def _backtick_run_end(text: str, start: int) -> int:
    end = start
    while end < len(text) and text[end] == "`":
        end += 1
    return end


def _code_span_at(text: str, start: int, limit: int | None = None) -> _CodeSpan | None:
    if text[start:start + 1] != "`" or start and text[start - 1] == "`":
        return None
    prefix = text[:start]
    if (len(prefix) - len(prefix.rstrip("\\"))) % 2:
        return None
    opening_end = _backtick_run_end(text, start)
    width = opening_end - start
    stop = len(text) if limit is None else limit
    position = opening_end
    while position < stop:
        closing = text.find("`", position, stop)
        if closing < 0:
            return None
        end = _backtick_run_end(text, closing)
        if end - closing == width and end <= stop:
            value = text[opening_end:closing].replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
            if value.startswith(" ") and value.endswith(" ") and value.strip(" "):
                value = value[1:-1]
            return _CodeSpan(start, end, value)
        position = end
    return None


def _code_spans(text: str) -> tuple[_CodeSpan, ...]:
    spans = []
    position = 0
    while position < len(text):
        start = text.find("`", position)
        if start < 0:
            break
        span = _code_span_at(text, start)
        if span is None:
            position = _backtick_run_end(text, start)
        else:
            spans.append(span)
            position = span.end
    return tuple(spans)


class _RenderedSemantics(HTMLParser):
    """Collect only rendered element semantics; Markdown grammar belongs to the renderer."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parents: list[str] = []
        self.blocked: list[str] = []
        self.anchor: tuple[str, list[str]] | None = None
        self.links: list[str] = []
        self.local_link_labels: list[str] = []
        self.images: list[str] = []

    def _finish_anchor(self) -> None:
        if self.anchor is not None:
            target, parts = self.anchor
            label = _space(unicodedata.normalize("NFKC", "".join(parts)))
            self.links.append(f"{label}\n{target}")
            if not re.match(r"^(?:[a-z][\w+.-]*:|//)", target, re.IGNORECASE):
                self.local_link_labels.append(label)
            self.anchor = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        blocked = bool(self.blocked)
        attributes = {}
        for key, value in attrs:
            attributes.setdefault(key, value or "")
        if not blocked:
            if tag == "a" and "href" in attributes:
                self._finish_anchor()
                self.anchor = (unicodedata.normalize("NFKC", attributes["href"]), [])
            elif tag == "img" and "src" in attributes:
                alt = _space(unicodedata.normalize("NFKC", attributes.get("alt", "")))
                source = unicodedata.normalize("NFKC", attributes["src"])
                self.images.append(f"{alt}\n{PurePosixPath(unquote(urlsplit(source).path)).name}")
                if self.anchor is not None:
                    self.anchor[1].append(alt)
        if tag not in _VOID_TAGS:
            self.parents.append(tag)
        if tag in _RAW_TAGS:
            self.blocked.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag in _RAW_TAGS or tag == "a":
            return
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.anchor is not None and not any(parent in _HIDDEN_TAGS for parent in self.blocked):
            self.anchor[1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and not self.blocked:
            self._finish_anchor()
        if tag in self.blocked:
            index = len(self.blocked) - 1 - self.blocked[::-1].index(tag)
            del self.blocked[index:]
        if tag in self.parents:
            index = len(self.parents) - 1 - self.parents[::-1].index(tag)
            del self.parents[index:]


def _literal_markdown_characters(text: str) -> str:
    return "".join(f"&#{ord(char)};" if char in "\\`*_{}[]!" else char for char in text)


class _RendererHtmlBoundary(HTMLParser):
    """Keep raw HTML literal while the pinned renderer owns all Markdown grammar."""

    CDATA_CONTENT_ELEMENTS = tuple(_RAW_TAGS - {"template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.output: list[str] = []
        self.raw: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        original = self.get_starttag_text()
        if any(value and any(char in value for char in "\\`*_{}[]!<>\n\r") for _, value in attrs):
            pieces = ["<", tag]
            for name, value in attrs:
                pieces.append(f" {name}")
                if value is not None:
                    value = _literal_markdown_characters(escape(value, quote=True))
                    value = value.replace("\n", "&#10;").replace("\r", "&#13;")
                    pieces.append(f'="{value}"')
            pieces.append("/>" if original.endswith("/>") else ">")
            self.output.append("".join(pieces))
        else:
            self.output.append(original)
        if tag in _RAW_TAGS:
            self.raw.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag in _RAW_TAGS:
            if tag != "template":
                self.set_cdata_mode(tag)
        elif tag in self.raw:
            self.raw.remove(tag)

    def handle_endtag(self, tag: str) -> None:
        self.output.append(f"</{tag}>")
        if tag in self.raw:
            index = len(self.raw) - 1 - self.raw[::-1].index(tag)
            del self.raw[index:]

    def handle_data(self, data: str) -> None:
        self.output.append(_literal_markdown_characters(data) if self.raw else data)

    def handle_entityref(self, name: str) -> None:
        self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.output.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.output.append(f"<!--{data}-->")


def _rendered_semantics(
    text: str, html_spans: list[tuple[int, int]],
) -> tuple[_RenderedSemantics, dict]:
    for start, end in reversed(html_spans):
        reader = _RendererHtmlBoundary()
        reader.feed(text[start:end])
        reader.close()
        text = text[:start] + "".join(reader.output) + text[end:]
    renderer = create_semantic_renderer()
    output = renderer.convert(text)
    collector = _RenderedSemantics()
    collector.feed(output)
    collector.close()
    collector._finish_anchor()
    return collector, renderer.references


@dataclass(frozen=True)
class _HtmlFragment:
    raw: str
    rendered: str
    label: str
    wrapper: bool = False


class _HtmlElementReader(HTMLParser):
    """Read source prose text; semantic links/images are collected only after rendering."""

    CDATA_CONTENT_ELEMENTS = tuple(_RAW_TAGS - {"template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.raw_tag: str | None = None
        self.template_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.template_depth:
            self.template_depth += tag == "template"
            return
        if tag == "template":
            self.template_depth = 1
            return
        if tag in _RAW_TAGS:
            self.raw_tag = tag
            return
        if tag in {"br", "hr", "p", "div", "li", "tr"}:
            self.text.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag in _RAW_TAGS:
            if tag != "template":
                self.set_cdata_mode(tag)
            return
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.template_depth:
            self.template_depth -= tag == "template"
        elif self.raw_tag == tag:
            self.raw_tag = None
        elif tag in {"p", "div", "li", "tr"}:
            self.text.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.template_depth and self.raw_tag not in {"script", "style", "iframe", "noembed", "noframes", "noscript"}:
            self.text.append(unescape(data) if self.raw_tag else data)


def _html_element_end(text: str, start: int, tag: str) -> int | None:
    if tag == "plaintext":
        return len(text)
    if tag in _TEXT_RAW_TAGS:
        closing = re.search(r"</" + re.escape(tag) + r"\s*>", text[start:], re.IGNORECASE)
        return start + closing.end() if closing else None
    depth = 1
    position = start
    while position < len(text):
        position = text.find("<", position)
        if position < 0:
            return None
        if text.startswith("<!--", position):
            end = text.find("-->", position + 4)
            position = len(text) if end < 0 else end + 3
            continue
        token = _HTML_TAG.match(text, position)
        if token is None:
            position += 1
            continue
        name = token[1].lower()
        closing = token[0].startswith("</")
        position = token.end()
        if name == tag:
            depth += -1 if closing else 1
            if not depth:
                return position
        elif not closing and name in _RAW_TAGS:
            position = _html_element_end(text, position, name) or len(text)
    return None


def _html_fragment(text: str, position: int) -> tuple[int, _HtmlFragment] | None:
    token = _HTML_TAG.match(text, position)
    if token is None:
        if _HTML_OPEN.match(text, position):
            raw = text[position:]
            return len(text), _HtmlFragment(raw, raw, raw)
        return None
    raw, tag, end = token[0], token[1].lower(), token.end()
    escaped = _escaped_match(token)
    opening = not raw.startswith("</")
    if opening and not escaped and (tag == "a" or tag in _RAW_TAGS):
        complete = _html_element_end(text, end, tag)
        if complete is not None or tag in _RAW_TAGS:
            end = complete or len(text)
            raw = text[position:end]
            reader = _HtmlElementReader()
            reader.feed(raw)
            reader.close()
            label = _space("".join(reader.text))
            if tag == "a":
                return end, _HtmlFragment(raw, f" {label} ", label)
            return end, _HtmlFragment(raw, raw, label)
    if opening and tag == "img" and not escaped:
        return end, _HtmlFragment(raw, "", "")
    if opening and tag == "details" and not escaped and re.fullmatch(
        r"""<details\s+markdown=(?:"1"|'1'|1)\s*>""", raw, re.IGNORECASE,
    ):
        # The rendering opt-in is not historical prose; keep raw HTML for link semantics.
        return end, _HtmlFragment(raw, "<details>", "")
    wrapper = tag in _PRESENTATION_TAGS
    return end, _HtmlFragment(raw, " " if wrapper else raw, raw if escaped else "", wrapper=wrapper)


def _source_line(
    text: str, position: int, html: dict[str, _HtmlFragment], prefix: str,
    literals: dict[str, str],
    html_spans: list[tuple[int, int]],
) -> tuple[str, int]:
    parts = []
    while position < len(text) and text[position] != "\n":
        if text.startswith("<!--", position):
            end = text.find("-->", position + 4)
            position = len(text) if end < 0 else end + 3
            continue
        if text[position] == "`":
            boundary = re.search(r"\n(?:[ \t]*\n| {0,3}#{1,6}[ \t]+| {0,3}(?:`{3,}|~{3,}))", text[position:])
            limit = position + boundary.start() if boundary else len(text)
            span = _code_span_at(text, position, limit)
            if span:
                key = f"{prefix}code{len(literals)}\ue101"
                literals[key] = span.value
                parts.append(key)
                position = span.end
            else:
                end = _backtick_run_end(text, position)
                parts.append(text[position:end])
                position = end
            continue
        autolink = _AUTOLINK.match(text, position)
        if autolink:
            parts.append(autolink[0])
            position = autolink.end()
            continue
        if text[position] == "<":
            fragment = _html_fragment(text, position)
            if fragment:
                start = position
                position, value = fragment
                key = f"{prefix}{len(html)}\ue101"
                html[key] = value
                parts.append(key)
                if not (len(text[:start]) - len(text[:start].rstrip("\\"))) % 2:
                    html_spans.append((start, position))
                continue
        parts.append(text[position])
        position += 1
    return "".join(parts), position + (position < len(text))


def _unquote(line: str, depth: int) -> str | None:
    for _ in range(depth):
        prefix = re.match(r"^[ \t]{0,3}>[ \t]?", line)
        if prefix is None:
            return None
        line = line[prefix.end():]
    return line


def _segments(
    text: str, html: dict[str, _HtmlFragment] | None = None,
    literals: dict[str, str] | None = None,
    html_spans: list[tuple[int, int]] | None = None,
) -> list[tuple[str | None, str]]:
    """Separate fences before applying any prose-only normalization."""
    segments = []
    normal: list[str] = []
    code: list[str] = []
    fence = ""
    language = ""
    indent = ""
    quote_depth = 0
    html = html if html is not None else {}
    literals = literals if literals is not None else {}
    html_spans = html_spans if html_spans is not None else []
    prefix = "\ue100html"
    while prefix in text:
        prefix += "x"
    position = 0
    while position < len(text):
        end = text.find("\n", position)
        end = len(text) if end < 0 else end
        line = text[position:end]
        if fence:
            code_line = _unquote(line, quote_depth)
            if code_line is None:
                segments.append((language, "\n".join(code).strip("\n")))
                fence, code = "", []
            elif re.fullmatch(
                r"\s*" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", code_line,
            ):
                segments.append((language, "\n".join(code).strip("\n")))
                fence, code = "", []
                position = end + 1
                continue
            else:
                code.append(code_line.removeprefix(indent).rstrip())
                position = end + 1
                continue
        opening = _FENCE_OPEN.fullmatch(line)
        if opening and opening[3].startswith("`") and "`" in opening[4]:
            opening = None
        if opening:
            position = end + 1
        else:
            line, position = _source_line(text, position, html, prefix, literals, html_spans)
            opening = _FENCE_OPEN.fullmatch(line)
            if opening and opening[3].startswith("`") and "`" in opening[4]:
                opening = None
        if opening:
            segments.append((None, "\n".join(normal)))
            normal = []
            quotes, indent, fence, language = opening.groups()
            quote_depth = quotes.count(">")
            language = language.strip()
        else:
            normal.append(line)
    if fence:
        segments.append((language, "\n".join(code).strip("\n")))
    segments.append((None, "\n".join(normal)))
    return segments


def _table_cells(line: str) -> list[str]:
    line = line.strip()
    cells = []
    start = 0
    spans = {span.start: span for span in _code_spans(line)}
    position = 0
    while position < len(line):
        if position in spans:
            position = spans[position].end
            continue
        if line[position] == "\\":
            position += 2
            continue
        if line[position] == "|":
            cells.append(line[start:position])
            start = position + 1
        position += 1
    cells.append(line[start:])
    if line.startswith("|") and not cells[0]:
        cells.pop(0)
    if line.endswith("|") and not cells[-1]:
        cells.pop()
    return [cell.strip() for cell in cells]


def _separator(line: str) -> bool:
    cells = _table_cells(line)
    return "|" in line and bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def extract_markdown_structure(text: str) -> MarkdownStructure:
    text = unicodedata.normalize("NFKC", text.replace("\r\n", "\n").replace("\r", "\n")).lstrip("\ufeff")
    text = re.sub(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n|$)", "", text, count=1, flags=re.DOTALL)
    literal_prefix = "\ue000code"
    while literal_prefix in text:
        literal_prefix += "x"
    html: dict[str, _HtmlFragment] = {}
    source_literals: dict[str, str] = {}
    html_spans: list[tuple[int, int]] = []
    segments = _segments(text, html, source_literals, html_spans)
    semantics, rendered_references = _rendered_semantics(text, html_spans)
    definitions = {key: value[0] for key, value in rendered_references.items()}
    title = ""
    headings: list[str] = []
    prose: list[str] = []
    code: list[str] = []
    tables: list[str] = []

    def html_text(value: str, field: str) -> str:
        for token, fragment in html.items():
            value = value.replace(token, getattr(fragment, field))
        return value

    def visible(value: str) -> str:
        value = _WRAPPER.sub(" ", unescape(value))
        for _ in range(2):
            value = re.sub(r"(\*\*|\*)(.+?)\1", r"\2", value)
            value = re.sub(r"(?<!\w)(__|_)(.+?)\1(?!\w)", r"\2", value)
        return _space(value)

    def link(label: str, target: str, image: bool) -> str:
        # Source-only prose normalization; semantic evidence never comes from these regexes.
        markup = visible(label)
        if image:
            return ""
        return markup

    def inline(value: str) -> str:
        literals: dict[str, str] = {}

        def restore(text: str) -> str:
            for token, literal in literals.items():
                text = text.replace(token, literal)
            for token, literal in source_literals.items():
                text = text.replace(token, literal)
            return text

        for span in reversed(_code_spans(value)):
            token = f"{literal_prefix}{len(literals)}\ue001"
            literals[token] = span.value
            value = value[:span.start] + token + value[span.end:]

        def markdown_image(match: re.Match) -> str:
            return match[0] if _escaped_match(match) else link(match[1], match[2], True)

        def reference_image(match: re.Match) -> str:
            if not match[1] or _escaped_match(match):
                return match[0]
            key = _space(match[3] or match[2]).lower()
            return link(match[2], definitions[key], True) if key in definitions else match[0]

        value = _IMAGE.sub(markdown_image, value)
        value = _REFERENCE.sub(reference_image, value)

        def markdown_link(match: re.Match) -> str:
            if _escaped_match(match):
                if match[1]:
                    return "!" + link(match[2], match[3], False)
                return match[0]
            return link(match[2], match[3], bool(match[1]))

        value = _LINK.sub(markdown_link, value)

        def reference(match: re.Match) -> str:
            escaped = _escaped_match(match)
            if escaped and not match[1]:
                return match[0]
            key = _space(match[3] or match[2]).lower()
            if key not in definitions:
                return match[0]
            if escaped:
                return "!" + link(match[2], definitions[key], False)
            return link(match[2], definitions[key], bool(match[1]))

        value = _REFERENCE.sub(reference, value)

        result = _space(html_text(visible(value), "rendered"))
        return restore(result)

    def heading(value: str, level: int) -> None:
        nonlocal title
        value = re.sub(r"\s+#+\s*$", "", value)
        value = re.sub(r"^(?:\d+[.)]|\d+(?:\.\d+)+\.?)\s+", "", inline(value))
        if level == 1 and not title:
            title = value
        else:
            headings.append(value)

    for language, body in segments:
        if language is not None:
            code.append(f"{language}\n{body}")
            continue
        body = _DEFINITION.sub("", body)
        lines = body.split("\n")
        paragraph: list[str] = []

        def flush() -> None:
            value = inline(" ".join(paragraph))
            if value:
                prose.append(value)
            paragraph.clear()

        in_table = False
        index = 0
        while index < len(lines):
            line = lines[index].strip()
            if line in html and html[line].wrapper:
                line = ""
            following = lines[index + 1].strip() if index + 1 < len(lines) else ""
            index += 1
            if not line:
                flush()
                in_table = False
                continue
            atx = re.match(r"^(#{1,6})[ \t]+(.*)", line)
            if atx:
                flush()
                heading(atx[2], len(atx[1]))
                in_table = False
            elif re.fullmatch(r"={3,}|-{3,}", following) and not re.match(r"[-*+] ", line):
                flush()
                heading(line, 1 if following.startswith("=") else 2)
                index += 1
                in_table = False
            elif "|" in line and (line.startswith("|") or in_table or _separator(following)):
                flush()
                in_table = True
                if not _separator(line):
                    tables.append(" | ".join(
                        inline(cell).replace(r"\|", "|").replace("\\", "\\\\").replace("|", r"\|")
                        for cell in _table_cells(line)
                    ))
            elif re.fullmatch(r"(?:[-*_]\s*){3,}", line):
                flush()
                in_table = False
            else:
                in_table = False
                line = re.sub(r"^(?:>\s*)+", "", line)
                if re.match(r"^(?:\d+[.)]|[-*+])\s+", line):
                    flush()
                    line = re.sub(r"^\d+[.)]\s+", "1. ", line)
                    line = re.sub(r"^[-*+]\s+", "- ", line)
                paragraph.append(line)
        flush()
    return MarkdownStructure(
        title, tuple(headings), tuple(prose), tuple(code), tuple(tables),
        tuple(semantics.images), tuple(semantics.local_link_labels),
        tuple(semantics.links),
    )


def _values(structure: MarkdownStructure, category: str) -> tuple[str, ...]:
    if category == "title":
        return (structure.title,) if structure.title else ()
    return getattr(structure, category)


def _verify_current_evidence(
    repo_root: Path,
    baseline_path: PurePosixPath,
    reviewed_changes: Mapping[str, Mapping[str, ReviewedChange]],
) -> None:
    files = resolve_public_evidence_files(repo_root, tuple({
        ref.path for group in reviewed_changes.values() for approval in group.values()
        for ref in approval.evidence
    }))
    contents: dict[PurePosixPath, bytes] = {}
    structures: dict[PurePosixPath, MarkdownStructure] = {}
    for category, approvals in reviewed_changes.items():
        for fingerprint, approval in approvals.items():
            for index, reference in enumerate(approval.evidence):
                label = f"{baseline_path}.{category}.{fingerprint}.evidence[{index}] ({reference.path})"
                if reference.path not in contents:
                    try:
                        contents[reference.path] = files[reference.path].read_bytes()
                    except OSError as error:
                        raise AuditFormatError(f"{label}: cannot read current evidence: {error}") from error
                data = contents[reference.path]
                if isinstance(reference, FileEvidence):
                    actual_hash = sha256(data).hexdigest()
                    if actual_hash != reference.sha256:
                        raise AuditFormatError(f"{label}: evidence SHA-256 changed: {actual_hash}")
                    continue
                if reference.path not in structures:
                    try:
                        structures[reference.path] = extract_markdown_structure(data.decode("utf-8"))
                    except UnicodeError as error:
                        raise AuditFormatError(f"{label}: structure evidence is not UTF-8: {error}") from error
                counts = Counter(
                    sha256(f"{reference.category}\0{value}".encode("utf-8")).hexdigest()
                    for value in _values(structures[reference.path], reference.category)
                )
                actual_count = counts[reference.fingerprint]
                if actual_count != reference.count:
                    raise AuditFormatError(
                        f"{label}: evidence {reference.category} fingerprint {reference.fingerprint} "
                        f"count changed: expected {reference.count}, found {actual_count}"
                    )


def _verify_self_link_removal(
    baseline_path: PurePosixPath,
    current_path: PurePosixPath,
    baseline: MarkdownStructure,
    current: MarkdownStructure,
    fingerprint: str,
    approval: ReviewedChange,
) -> None:
    labels = {
        label for label in baseline.local_link_labels
        if sha256(f"local_link_labels\0{label}".encode("utf-8")).hexdigest() == fingerprint
    }
    links = [value.partition("\n")[2] for value in baseline.links if value.partition("\n")[0] in labels]
    if len(links) < approval.missing_count:
        raise AuditFormatError(f"{baseline_path}: self-link removal has no matching baseline link evidence")
    for target in links:
        url = urlsplit(target)
        if (
            url.scheme or url.netloc or url.query or url.fragment or not url.path or url.path.startswith("/")
            or PurePosixPath(posixpath.normpath(str(baseline_path.parent / unquote(url.path)))) != baseline_path
        ):
            raise AuditFormatError(f"{baseline_path}: removal is not a redundant document self-link")
    identities = [
        ref for ref in approval.evidence
        if isinstance(ref, StructureEvidence) and ref.path == current_path
        and ref.fingerprint in {
            sha256(f"{ref.category}\0{value}".encode("utf-8")).hexdigest()
            for value in _values(current, ref.category)
        }
    ]
    if not {"title", "headings"} <= {ref.category for ref in identities}:
        raise AuditFormatError(f"{baseline_path}: self-link removal must bind current document identity/topic structure")


def compare_markdown(
    baseline_path: PurePosixPath,
    current_path: PurePosixPath,
    baseline: MarkdownStructure,
    current: MarkdownStructure,
    reviewed_changes: Mapping[str, Mapping[str, ReviewedChange]],
    *,
    repo_root: Path | None = None,
) -> DocumentPreservation:
    """Compare source structures; approvals require repo_root for fresh evidence reads."""
    reviewed_changes = validate_reviewed_changes(reviewed_changes, f"{baseline_path}.reviewed_changes")
    raw_missing: list[StructureFinding] = []
    for category in STRUCTURE_CATEGORIES:
        remaining = Counter(_values(current, category))
        for value in _values(baseline, category):
            if remaining[value]:
                remaining[value] -= 1
                continue
            fingerprint = sha256(f"{category}\0{value}".encode("utf-8")).hexdigest()
            raw_missing.append(StructureFinding(category, fingerprint, value[:160]))
    missing_counts = Counter((finding.category, finding.fingerprint) for finding in raw_missing)
    approved = set()
    for category, approvals in reviewed_changes.items():
        for fingerprint, approval in approvals.items():
            actual = missing_counts[(category, fingerprint)]
            if not actual:
                raise AuditFormatError(
                    f"{baseline_path}: stale reviewed_changes.{category}.{fingerprint}; "
                    "the exact baseline structure is not missing"
                )
            if actual != approval.missing_count:
                raise AuditFormatError(
                    f"{baseline_path}.{category}.{fingerprint}: missing_count changed: "
                    f"approved {approval.missing_count}, found {actual}"
                )
            if approval.link_change == "redundant-self-link":
                _verify_self_link_removal(
                    baseline_path, current_path, baseline, current, fingerprint, approval,
                )
            approved.add((category, fingerprint))
    if approved:
        if repo_root is None:
            raise AuditFormatError(f"{baseline_path}: repo_root is required to verify current approval evidence")
        _verify_current_evidence(repo_root, baseline_path, reviewed_changes)
    missing = tuple(f for f in raw_missing if (f.category, f.fingerprint) not in approved)
    reviewed = tuple(f for f in raw_missing if (f.category, f.fingerprint) in approved)
    before_text = "\n".join((baseline.title, *baseline.headings, *baseline.prose))
    after_text = "\n".join((current.title, *current.headings, *current.prose))
    similarity = SequenceMatcher(None, before_text, after_text, autojunk=False).ratio()
    status = "missing" if missing else "reviewed" if reviewed else "preserved"
    return DocumentPreservation(
        baseline_path, current_path, status, similarity, missing, reviewed,
    )


def audit_document_content(
    repo_root: Path, inventory: PrePagesInventory,
) -> tuple[DocumentPreservation, ...]:
    documents = resolve_current_documents(repo_root, inventory)
    return tuple(
        compare_markdown(
            entry.baseline_path,
            PurePosixPath("docs") / documents[entry.baseline_path].relative_path,
            extract_markdown_structure(git_text(repo_root, inventory.baseline_commit, entry.baseline_path)),
            extract_markdown_structure(documents[entry.baseline_path].body),
            entry.reviewed_changes,
            repo_root=repo_root,
        )
        for entry in inventory.documents
    )


def write_content_review_json(
    path: Path, results: tuple[DocumentPreservation, ...],
) -> None:
    documents = [
        {
            **asdict(result),
            "baseline_path": result.baseline_path.as_posix(),
            "current_path": result.current_path.as_posix(),
        }
        for result in results
    ]
    data = {
        "summary": {
            "documents": len(results),
            "missing": sum(len(result.missing) for result in results),
            "reviewed": sum(len(result.reviewed) for result in results),
            "statuses": dict(sorted(Counter(result.status for result in results).items())),
        },
        "documents": documents,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
