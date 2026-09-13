"""Source-structure preservation against the fixed pre-Pages Git baseline."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from hashlib import sha256
from html import unescape
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
_ATTRIBUTE = re.compile(r'''([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))''')
_HTML_LINK = re.compile(
    r"""<a\b((?:"[^"]*"|'[^']*'|[^'">])*)>(.*?)</a\s*>""",
    re.IGNORECASE | re.DOTALL,
)
_WRAPPER = re.compile(
    r"</?(?:div|section|article|aside|nav|p|span|strong|em|b|i|a|ol|ul|li|br)\b[^>]*>",
    re.IGNORECASE,
)


def _space(text: str) -> str:
    return " ".join(text.split())


def _escaped_match(match: re.Match) -> bool:
    prefix = match.string[:match.start()]
    return (len(prefix) - len(prefix.rstrip("\\"))) % 2 == 1


def _unquote(line: str, depth: int) -> str | None:
    for _ in range(depth):
        prefix = re.match(r"^[ \t]{0,3}>[ \t]?", line)
        if prefix is None:
            return None
        line = line[prefix.end():]
    return line


def _segments(text: str) -> list[tuple[str | None, str]]:
    """Separate fences before applying any prose-only normalization."""
    segments = []
    normal: list[str] = []
    code: list[str] = []
    fence = ""
    language = ""
    indent = ""
    quote_depth = 0
    comment = False
    for line in text.split("\n"):
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
                continue
            else:
                code.append(code_line.removeprefix(indent).rstrip())
                continue
        visible = []
        offset = 0
        while offset < len(line):
            if comment:
                end = line.find("-->", offset)
                if end < 0:
                    break
                offset, comment = end + 3, False
                continue
            token = re.search(r"(`+).*?\1|<!--", line[offset:])
            if token is None:
                visible.append(line[offset:])
                break
            visible.append(line[offset:offset + token.start()])
            if token[0] == "<!--":
                comment = True
            else:
                visible.append(token[0])
            offset += token.end()
        line = "".join(visible)
        opening = re.fullmatch(r"((?:[ \t]{0,3}>[ \t]?)*)([ \t]*)(`{3,}|~{3,})(.*)", line)
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
    segments = _segments(text)
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

    def visible(value: str) -> str:
        value = _WRAPPER.sub(" ", unescape(value))
        value = re.sub(r"(`+)(.*?)\1", r"\2", value)
        for _ in range(2):
            value = re.sub(r"(\*\*|\*)(.+?)\1", r"\2", value)
            value = re.sub(r"(?<!\w)(__|_)(.+?)\1(?!\w)", r"\2", value)
        return _space(value)

    def link(label: str, target: str, image: bool) -> str:
        label = visible(label)
        target = unescape(target.strip("<>"))
        if image:
            images.append(f"{label}\n{PurePosixPath(unquote(urlsplit(target).path)).name}")
            return ""
        if label:
            links.append(f"{label}\n{target}")
        if label and not re.match(r"^(?:[a-z][\w+.-]*:|//)", target, re.IGNORECASE):
            local_link_labels.append(label)
        return label

    def inline(value: str) -> str:
        literals: dict[str, str] = {}
        image_start, label_start, link_start = len(images), len(local_link_labels), len(links)

        def protect(match: re.Match) -> str:
            token = f"\ue000{len(literals)}\ue001"
            literals[token] = match[2]
            return token

        def restore(text: str) -> str:
            for token, literal in literals.items():
                text = text.replace(token, literal)
            return text

        value = re.sub(r"(`+)(.*?)\1", protect, value)

        def attributes(raw: str) -> dict[str, str]:
            return {
                name.lower(): double or single or bare
                for name, double, single, bare in _ATTRIBUTE.findall(raw)
            }

        def html_image(match: re.Match) -> str:
            attrs = attributes(match[0])
            return link(attrs.get("alt", ""), attrs.get("src", ""), True)

        def html_link(match: re.Match) -> str:
            if _escaped_match(match):
                return match[0]
            attrs = attributes(match[1])
            label = link(match[2], attrs["href"], False) if "href" in attrs else match[2]
            return f" {label} "

        value = re.sub(r"<img\b[^>]*>", html_image, value, flags=re.IGNORECASE)
        value = _IMAGE.sub(lambda match: link(match[1], match[2], True), value)
        value = _HTML_LINK.sub(html_link, value)

        def markdown_link(match: re.Match) -> str:
            if _escaped_match(match):
                return match[0]
            return link(match[2], match[3], bool(match[1]))

        value = _LINK.sub(markdown_link, value)

        def reference(match: re.Match) -> str:
            if _escaped_match(match):
                return match[0]
            key = _space(match[3] or match[2]).casefold()
            if key not in definitions:
                return match[0]
            return link(match[2], definitions[key], bool(match[1]))

        value = _REFERENCE.sub(reference, value)

        def autolink(match: re.Match) -> str:
            if not _escaped_match(match):
                link(match[1], match[1], False)
            return match[0]

        value = re.sub(r"<((?:https?://|mailto:)[^<>\s]+)>", autolink, value, flags=re.IGNORECASE)
        result = visible(value)
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
        body = re.sub(
            r"(?m)^[ \t]*" + _WRAPPER.pattern + r"[ \t]*$",
            lambda match: match[0] if re.match(r"\s*</?a\b", match[0], re.IGNORECASE) else "",
            _DEFINITION.sub("", body),
            flags=re.IGNORECASE,
        )
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
