"""Source-structure preservation against the fixed pre-Pages Git baseline."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
from typing import Mapping
import unicodedata
from urllib.parse import unquote, urlsplit

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
_DEFINITION = re.compile(r"(?m)^ {0,3}\[([^\]]+)\]:\s*" + _DESTINATION + r"[^\n]*$")
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


def _space(text: str) -> str:
    return " ".join(text.split())


def _escaped_match(match: re.Match) -> bool:
    prefix = match.string[:match.start()]
    return (len(prefix) - len(prefix.rstrip("\\"))) % 2 == 1


@dataclass(frozen=True)
class _HtmlFragment:
    raw: str
    rendered: str
    label: str
    images: tuple[tuple[str, str], ...] = ()
    links: tuple[tuple[str, str], ...] = ()
    wrapper: bool = False


class _HtmlElementReader(HTMLParser):
    """Read element semantics without interpreting any attribute or text as Markdown."""

    CDATA_CONTENT_ELEMENTS = tuple(_RAW_TAGS - {"template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.images: list[tuple[str, str]] = []
        self.href: str | None = None
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
        values = {}
        for name, value in attrs:
            values.setdefault(name, value or "")
        if tag == "a" and self.href is None:
            self.href = values.get("href")
        elif tag == "img":
            self.images.append((values.get("alt", ""), values.get("src", "")))
        elif tag in {"br", "hr", "p", "div", "li", "tr"}:
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
                links = ((label, reader.href),) if label and reader.href is not None else ()
                return end, _HtmlFragment(raw, f" {label} ", label, tuple(reader.images), links)
            return end, _HtmlFragment(raw, raw, label)
    if opening and tag == "img" and not escaped:
        reader = _HtmlElementReader()
        reader.feed(raw)
        reader.close()
        return end, _HtmlFragment(raw, "", "", tuple(reader.images))
    wrapper = tag in _PRESENTATION_TAGS
    return end, _HtmlFragment(raw, " " if wrapper else raw, raw if escaped else "", wrapper=wrapper)


def _source_line(
    text: str, position: int, html: dict[str, _HtmlFragment], prefix: str,
) -> tuple[str, int]:
    parts = []
    while position < len(text) and text[position] != "\n":
        if text.startswith("<!--", position):
            end = text.find("-->", position + 4)
            position = len(text) if end < 0 else end + 3
            continue
        code = re.match(r"(`+)(.*?)\1", text[position:]) if text[position] == "`" else None
        if code:
            parts.append(code[0])
            position += code.end()
            continue
        autolink = _AUTOLINK.match(text, position)
        if autolink:
            parts.append(autolink[0])
            position = autolink.end()
            continue
        if text[position] == "<":
            fragment = _html_fragment(text, position)
            if fragment:
                position, value = fragment
                key = f"{prefix}{len(html)}\ue101"
                html[key] = value
                parts.append(key)
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
        if opening:
            position = end + 1
        else:
            line, position = _source_line(text, position, html, prefix)
            opening = _FENCE_OPEN.fullmatch(line)
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
    for token in re.finditer(r"(?P<ticks>`+).*?(?P=ticks)|\\.|(?P<bar>\|)", line):
        if token["bar"]:
            cells.append(line[start:token.start()])
            start = token.end()
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
    segments = _segments(text, html)
    definitions = {
        _space(match[1]).casefold(): match[2].strip("<>")
        for language, body in segments if language is None
        for match in _DEFINITION.finditer(body)
    }
    title = ""
    headings: list[str] = []
    prose: list[str] = []
    code: list[str] = []
    tables: list[str] = []
    images: list[str] = []
    local_link_labels: list[str] = []
    links: list[str] = []

    def html_text(value: str, field: str) -> str:
        for token, fragment in html.items():
            value = value.replace(token, getattr(fragment, field))
        return value

    def visible(value: str) -> str:
        value = _WRAPPER.sub(" ", unescape(value))
        value = re.sub(r"(`+)(.*?)\1", r"\2", value)
        for _ in range(2):
            value = re.sub(r"(\*\*|\*)(.+?)\1", r"\2", value)
            value = re.sub(r"(?<!\w)(__|_)(.+?)\1(?!\w)", r"\2", value)
        return _space(value)

    def link(label: str, target: str, image: bool) -> str:
        markup = visible(label)
        label = _space(html_text(markup, "label"))
        target = unescape(html_text(target, "raw").strip("<>"))
        if image:
            images.append(f"{label}\n{PurePosixPath(unquote(urlsplit(target).path)).name}")
            return ""
        if label:
            links.append(f"{label}\n{target}")
        if label and not re.match(r"^(?:[a-z][\w+.-]*:|//)", target, re.IGNORECASE):
            local_link_labels.append(label)
        return markup

    def inline(value: str) -> str:
        literals: dict[str, str] = {}
        image_start, label_start, link_start = len(images), len(local_link_labels), len(links)

        def protect(match: re.Match) -> str:
            token = f"{literal_prefix}{len(literals)}\ue001"
            literals[token] = match[2]
            return token

        def restore(text: str) -> str:
            for token, literal in literals.items():
                text = text.replace(token, literal)
            return text

        value = re.sub(r"(`+)(.*?)\1", protect, value)

        def markdown_image(match: re.Match) -> str:
            return match[0] if _escaped_match(match) else link(match[1], match[2], True)

        def reference_image(match: re.Match) -> str:
            if not match[1] or _escaped_match(match):
                return match[0]
            key = _space(match[3] or match[2]).casefold()
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
            key = _space(match[3] or match[2]).casefold()
            if key not in definitions:
                return match[0]
            if escaped:
                return "!" + link(match[2], definitions[key], False)
            return link(match[2], definitions[key], bool(match[1]))

        value = _REFERENCE.sub(reference, value)

        def autolink(match: re.Match) -> str:
            if not _escaped_match(match):
                link(match[1], match[1], False)
            return match[0]

        value = re.sub(r"<((?:https?://|mailto:)[^<>\s]+)>", autolink, value, flags=re.IGNORECASE)
        for token, fragment in html.items():
            for _ in range(value.count(token)):
                for alt, source in fragment.images:
                    alt = _space(unicodedata.normalize("NFKC", alt))
                    images.append(f"{alt}\n{PurePosixPath(unquote(urlsplit(source).path)).name}")
                for label, target in fragment.links:
                    label = _space(unicodedata.normalize("NFKC", label))
                    target = unicodedata.normalize("NFKC", target)
                    links.append(f"{label}\n{target}")
                    if not re.match(r"^(?:[a-z][\w+.-]*:|//)", target, re.IGNORECASE):
                        local_link_labels.append(label)
        result = _space(html_text(visible(value), "rendered"))
        images[image_start:] = [restore(image) for image in images[image_start:]]
        local_link_labels[label_start:] = [restore(label) for label in local_link_labels[label_start:]]
        links[link_start:] = [restore(value) for value in links[link_start:]]
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
                        inline(cell.replace(r"\|", "|")).replace("\\", "\\\\").replace("|", r"\|")
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
        tuple(images), tuple(local_link_labels),
        tuple(links),
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
