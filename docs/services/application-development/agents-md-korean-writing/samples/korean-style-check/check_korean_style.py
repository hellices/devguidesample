"""Count Korean prose patterns that make agent-written docs read as machine-made.

The checker is a heuristic, not an AI-text detector. It reports pattern density
so a writer or agent can decide what to revise. Only the standard library is
used so it can run in any repository without installing dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
# Fence lines follow CommonMark: three or more backticks or tildes, and a backtick
# fence's info string cannot contain a backtick. Patterns below that take a line
# body are matched after the leading spaces are removed.
FENCE_OPEN = re.compile(r"(`{3,}(?=[^`]*$)|~{3,})")
LIST_ITEM = re.compile(r"( *)([-*+]|\d{1,9}[.)])( +|$)")
# MkDocs admonition, collapsible details and content tabs indent their body by four.
BLOCK_CONTAINER = re.compile(r"( *)(?:!!!|\?\?\?\+?|===)(?:\s|$)")
BLOCK_START = re.compile(r"(?:#{1,6}(?:\s|$)|>)")
TABLE_DELIMITER = re.compile(r"\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?")
TABLE_BREAK = re.compile(
    r"(?:#{1,6}(?:\s|$)|>|`{3,}|~{3,}|[-*+]\s|\d{1,9}[.)]\s|(?:[-*_]\s*){3,}$)"
)
INLINE_CODE = re.compile(r"`[^`\n]+`")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.M)
BOLD = re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__")
BOLD_LABEL = re.compile(r"^\s*(?:(?:[-*+]|\d+[.)])\s+)?\*\*[^*\n]+\*\*\s*[:：]", re.M)
EM_DASH = re.compile(r"—|(?<=\S) -- (?=\S)")
# Headings that end like a sentence ("~합니다", "~다", "~요") read as body text.
SENTENCE_HEADING = re.compile(r"(?:니다|세요|[가-힣]요|[가-힣]다)[.!?]?$")
HEADING_ANCHOR = re.compile(r"\s*\{[^}]*\}\s*$")

# A Hangul syllable followed by a connective ending and a comma.
CONNECTIVE_COMMA = re.compile(r"[가-힣](?:고|며|지만|면서|아서|어서|여서|는데|니까|므로)\s?,")
ADVERB_COMMA = re.compile(
    r"(?:^|[\s(])(?:그리고|그러나|그런데|하지만|그러므로|따라서|또한|즉|게다가|그래서)\s?,"
)

TRANSLATIONESE = {
    "~에 의해": re.compile(r"에\s?의해(?:서)?"),
    "이중 피동": re.compile(r"되어(?:지|져|진|졌)|지게\s?되"),
    "~에 있어(서)": re.compile(r"에\s?있어(?:서)?(?=[\s,.]|$)"),
    "~을/를 가지고 있다": re.compile(r"[을를]\s?가지고\s?있"),
    "~을/를 수행·진행·실시": re.compile(r"[을를]\s?(?:수행|진행|실시)(?:하|한|합|해|됩|된)"),
    "~에서의·~으로의": re.compile(r"(?:에서의|으로의|로의|에로의|에의)(?=\s)"),
    "~하는 것이 중요하다": re.compile(r"것이\s?(?:중요|필요|바람직)"),
    "~다는 것이다": re.compile(r"(?:다는|라는)\s?것이다"),
}

SIGNATURE = {
    "결산 접속어": re.compile(r"결론적으로|요약하면|요약하자면|종합하면|종합하자면|정리하자면"),
    "의미 부풀리기": re.compile(r"패러다임|게임\s?체인저|혁신적인|획기적인|시사하는\s?바가|주목할\s?만하"),
    "열거 도입": re.compile(r"(?:크게\s?)?(?:두|세|네)\s?가지로\s?(?:나눌|정리할|요약할)\s?수"),
}
CONTRAST = re.compile(r"[가-힣A-Za-z0-9)]+(?:이|가)\s?아니라(?=\s)")

FORMAL_END = re.compile(r"(?:니다|니까|세요|십시오|해요|에요|예요|까요)[.!?]$")
PLAIN_END = re.compile(r"[가-힣][.!?]$")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
# Quoted spans usually cite an example of a pattern rather than use it. A straight
# single quote next to an ASCII letter or digit is an apostrophe (don't, user's),
# so it can neither open nor close a quote.
QUOTED = re.compile(
    r"\"[^\"\n]*\"|“[^”\n]*”|‘[^’\n]*’|「[^」\n]*」"
    r"|(?<![A-Za-z0-9])'[^'\n]*'(?![A-Za-z0-9])"
)
# Inline Markdown that wraps heading text: images, link labels, emphasis.
INLINE_LINK = re.compile(r"!?\[([^\]]*)\]")
INLINE_EMPHASIS = re.compile(
    r"(\*\*|\*|~~)(?=\S)(.+?)(?<=\S)\1"
    r"|(?<![A-Za-z0-9])(__|_)(?=\S)(.+?)(?<=\S)\3(?![A-Za-z0-9])"
)


@dataclass
class Thresholds:
    bold_per_1000_chars: float = 2.0
    bold_label_lines: int = 0
    colon_headings: int = 0
    sentence_headings: int = 0
    connective_comma_per_100_sentences: float = 8.0
    adverb_comma: int = 0
    translationese_per_100_sentences: float = 6.0
    signature_phrases: int = 1
    contrast: int = 2
    em_dash: int = 0
    minority_ending_ratio: float = 0.15
    bullet_line_ratio: float = 0.35
    table_line_ratio: float = 0.30


@dataclass
class Report:
    path: str
    prose_chars: int = 0
    sentences: int = 0
    lines: int = 0
    metrics: dict[str, float | int] = field(default_factory=dict)
    examples: dict[str, list[str]] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)


def list_content_indent(match: re.Match[str]) -> int:
    indent, marker, spaces = (len(group) for group in match.groups())
    # A marker followed by nothing or by five or more spaces starts its content
    # one column after the marker.
    return indent + marker + (spaces if 1 <= spaces <= 4 else 1)


def remove_fenced_code(text: str) -> str:
    """Drop fenced code blocks, including their fence lines.

    As in CommonMark, an opening fence may be indented at most three spaces past
    the content indent of its container. List items and MkDocs admonition,
    details and tab blocks are tracked as containers, so a fence nested in them
    is recognized while a top-level line indented four or more spaces is not.
    A block closes on a line of the same fence character at least as long as
    the opening fence or when its container ends. An unclosed block runs to the
    end of the document.
    """
    kept: list[str] = []
    containers: list[int] = []
    fence: str | None = None
    fence_base = 0
    previous_blank = True
    for raw in text.splitlines():
        line = raw.expandtabs(4)
        body = line.lstrip(" ")
        indent = len(line) - len(body)
        closing = body.rstrip()
        if fence is not None:
            if not body or indent >= fence_base:
                if (
                    closing
                    and indent - fence_base <= 3
                    and set(closing) == {fence[0]}
                    and len(closing) >= len(fence)
                ):
                    fence, previous_blank = None, False
                continue
            # The container ended, which also closes the fence.
            fence, previous_blank = None, True
        if not body:
            kept.append(raw)
            previous_blank = True
            continue
        item = LIST_ITEM.match(line)
        block = BLOCK_CONTAINER.match(line)
        opener = FENCE_OPEN.match(body)
        # A less indented line ends deeper containers unless it is a lazy
        # continuation of the previous paragraph.
        if previous_blank or item or block or opener or BLOCK_START.match(body):
            while containers and indent < containers[-1]:
                containers.pop()
        base = containers[-1] if containers else 0
        relative = indent - base
        previous_blank = False
        if opener and 0 <= relative <= 3:
            fence, fence_base = opener.group(1), base
            continue
        if item and 0 <= relative <= 3:
            containers.append(list_content_indent(item))
        elif block and 0 <= relative <= 3:
            containers.append(indent + 4)
        kept.append(raw)
    return "\n".join(kept)


def table_cells(row: str) -> int:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return len(re.split(r"(?<!\\)\|", row))


def table_rows(lines: list[str]) -> set[int]:
    """Return line indexes of GFM tables, with or without outer pipes.

    A table starts with a header row followed by a delimiter row with the same
    number of cells and runs until a blank line or another block starts.
    """
    rows: set[int] = set()
    index = 1
    while index < len(lines):
        header, delimiter = lines[index - 1].strip(), lines[index].strip()
        if (
            index - 1 not in rows
            and "|" in header
            and "|" in delimiter
            and TABLE_DELIMITER.fullmatch(delimiter)
            and table_cells(header) == table_cells(delimiter)
        ):
            rows.update((index - 1, index))
            index += 1
            while index < len(lines):
                row = lines[index].strip()
                if not row or TABLE_BREAK.match(row):
                    break
                rows.add(index)
                index += 1
            continue
        index += 1
    return rows


def mask_quotes(prose: str) -> str:
    """Join each paragraph onto one line and replace quoted spans with a token."""
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", prose):
        joined = " ".join(part.strip() for part in paragraph.splitlines() if part.strip())
        if joined:
            paragraphs.append(QUOTED.sub("QUOTE", joined))
    return "\n\n".join(paragraphs)


def strip_markup(text: str) -> tuple[str, str]:
    """Return (markdown without code, prose-only text)."""
    text = FRONT_MATTER.sub("", text, count=1)
    text = HTML_COMMENT.sub("", text)
    text = remove_fenced_code(text)
    text = INLINE_CODE.sub("CODE", text)
    markdown = LINK_TARGET.sub("]", text)
    lines = markdown.splitlines()
    tables = table_rows(lines)
    prose_lines = []
    for index, line in enumerate(lines):
        if HEADING.match(line) or index in tables:
            prose_lines.append("")
            continue
        prose_lines.append(BULLET.sub("", line))
    prose = "\n".join(prose_lines)
    prose = re.sub(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__", lambda m: m.group(1) or m.group(2), prose)
    return markdown, prose


def normalize_inline(text: str) -> str:
    """Reduce link labels and emphasis to plain text."""
    text = INLINE_LINK.sub(r"\1", text)
    previous = None
    while previous != text:
        previous, text = text, INLINE_EMPHASIS.sub(lambda m: m.group(2) or m.group(4), text)
    return text.strip()


def split_sentences(prose: str) -> list[str]:
    sentences: list[str] = []
    for paragraph in re.split(r"\n\s*\n", prose):
        joined = " ".join(part.strip() for part in paragraph.splitlines() if part.strip())
        for sentence in SENTENCE_SPLIT.split(joined):
            sentence = sentence.strip()
            if re.search(r"[가-힣]", sentence):
                sentences.append(sentence)
    return sentences


def collect(pattern: re.Pattern[str], text: str, limit: int = 3) -> tuple[int, list[str]]:
    matches = list(pattern.finditer(text))
    examples = []
    for match in matches[:limit]:
        start, end = max(match.start() - 18, 0), min(match.end() + 18, len(text))
        examples.append(text[start:end].replace("\n", " ").strip())
    return len(matches), examples


def analyze(path: Path, limits: Thresholds) -> Report:
    markdown, prose = strip_markup(path.read_text(encoding="utf-8"))
    text = mask_quotes(prose)
    sentences = split_sentences(text)
    report = Report(
        path=str(path),
        prose_chars=len(re.sub(r"\s", "", prose)),
        sentences=len(sentences),
        lines=sum(1 for line in markdown.splitlines() if line.strip()),
    )
    metrics, examples = report.metrics, report.examples
    per100 = 100 / max(len(sentences), 1)

    headings = [
        normalize_inline(HEADING_ANCHOR.sub("", m.group(2)))
        for m in HEADING.finditer(markdown)
    ]
    colon_headings = [h for h in headings if re.search(r"\S\s?[:：]\s+\S", h)]
    metrics["colon_headings"] = len(colon_headings)
    if colon_headings:
        examples["colon_headings"] = colon_headings[:3]
    sentence_headings = [h for h in headings if SENTENCE_HEADING.search(h)]
    metrics["sentence_headings"] = len(sentence_headings)
    if sentence_headings:
        examples["sentence_headings"] = sentence_headings[:3]

    bold = len(BOLD.findall(markdown))
    metrics["bold"] = bold
    metrics["bold_per_1000_chars"] = round(bold * 1000 / max(report.prose_chars, 1), 2)
    metrics["bold_label_lines"] = len(BOLD_LABEL.findall(markdown))
    metrics["bullet_line_ratio"] = round(len(BULLET.findall(markdown)) / max(report.lines, 1), 2)
    table_lines = len(table_rows(markdown.splitlines()))
    metrics["table_line_ratio"] = round(table_lines / max(report.lines, 1), 2)

    count, found = collect(CONNECTIVE_COMMA, text)
    metrics["connective_comma"] = count
    metrics["connective_comma_per_100_sentences"] = round(count * per100, 1)
    if found:
        examples["connective_comma"] = found

    count, found = collect(ADVERB_COMMA, text)
    metrics["adverb_comma"] = count
    if found:
        examples["adverb_comma"] = found

    total = 0
    for name, pattern in TRANSLATIONESE.items():
        count, found = collect(pattern, text, limit=2)
        if count:
            total += count
            examples[f"translationese:{name}"] = found
    metrics["translationese"] = total
    metrics["translationese_per_100_sentences"] = round(total * per100, 1)

    total = 0
    for name, pattern in SIGNATURE.items():
        count, found = collect(pattern, text, limit=2)
        if count:
            total += count
            examples[f"signature:{name}"] = found
    metrics["signature_phrases"] = total

    count, found = collect(CONTRAST, text)
    metrics["contrast"] = count
    if found:
        examples["contrast"] = found

    metrics["em_dash"] = len(EM_DASH.findall(text))

    formal = sum(1 for s in sentences if FORMAL_END.search(s))
    plain = sum(1 for s in sentences if not FORMAL_END.search(s) and PLAIN_END.search(s))
    ended = formal + plain
    metrics["formal_endings"] = formal
    metrics["plain_endings"] = plain
    metrics["minority_ending_ratio"] = round(min(formal, plain) / ended, 2) if ended else 0.0

    lengths = [len(re.sub(r"\s", "", s)) for s in sentences]
    if len(lengths) >= 2:
        mean = statistics.mean(lengths)
        metrics["sentence_chars_mean"] = round(mean, 1)
        metrics["sentence_chars_cv"] = round(statistics.pstdev(lengths) / mean, 2)

    checks = [
        ("bold_per_1000_chars", limits.bold_per_1000_chars,
         "굵은 글씨가 많다. 처음 정의하는 용어나 놓치면 안 되는 한 곳에만 쓴다."),
        ("bold_label_lines", limits.bold_label_lines,
         "'**꼬리표**:'로 시작하는 줄이 있다. 문장으로 풀어 쓴다."),
        ("colon_headings", limits.colon_headings,
         "'X: Y' 형식 제목이 있다. 핵심을 담은 명사구 하나로 쓴다."),
        ("sentence_headings", limits.sentence_headings,
         "'~합니다'·'~다'로 끝나는 문장형 제목이 있다. 핵심을 담은 명사구로 줄인다."),
        ("connective_comma_per_100_sentences", limits.connective_comma_per_100_sentences,
         "연결어미(-고·-며·-지만) 뒤 쉼표가 많다. 쉼표를 지운다."),
        ("adverb_comma", limits.adverb_comma,
         "'그리고,'·'따라서,'처럼 접속부사 뒤에 쉼표가 있다. 쉼표를 지운다."),
        ("translationese_per_100_sentences", limits.translationese_per_100_sentences,
         "번역투 표현이 몰려 있다. 행위자를 주어로 세우고 동사로 끝낸다."),
        ("signature_phrases", limits.signature_phrases,
         "결산 접속어·의미 부풀리기·열거 도입이 있다. 지우거나 숫자·사례로 바꾼다."),
        ("contrast", limits.contrast,
         "'A가 아니라 B' 대조가 반복된다. 오해를 바로잡아야 하는 곳에만 남긴다."),
        ("em_dash", limits.em_dash,
         "대시(—)로 문장을 잇는다. 쉼표·괄호·새 문장으로 바꾼다."),
        ("minority_ending_ratio", limits.minority_ending_ratio,
         "'~다'와 '~니다' 종결이 섞여 있다. 문서 하나에서 한 가지로 통일한다."),
        ("bullet_line_ratio", limits.bullet_line_ratio,
         "글머리표 줄 비율이 높다. 설명은 문단으로 쓴다."),
        ("table_line_ratio", limits.table_line_ratio,
         "표 줄 비율이 높다. 같은 기준으로 여러 대상을 비교할 때만 표를 쓴다."),
    ]
    for key, limit, message in checks:
        value = metrics.get(key, 0)
        if value > limit:
            report.findings.append(f"{key}={value} (기준 {limit}) {message}")
    return report


def iter_markdown(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for item in paths:
        path = Path(item)
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*.md") if p.is_file()))
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(item)
    return files


def print_text(report: Report) -> None:
    status = "확인 필요" if report.findings else "통과"
    print(f"## {report.path} ({status})")
    print(f"문장 {report.sentences}개, 본문 {report.prose_chars}자")
    for key, value in report.metrics.items():
        print(f"  {key}: {value}")
    for finding in report.findings:
        print(f"  - {finding}")
    for key, found in report.examples.items():
        print(f"    예({key}): {' | '.join(found)}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Markdown files or directories")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--strict", action="store_true", help="exit 1 when any threshold is exceeded")
    args = parser.parse_args(argv)

    try:
        reports = [analyze(path, Thresholds()) for path in iter_markdown(args.paths)]
    except FileNotFoundError as error:
        print(f"not found: {error}", file=sys.stderr)
        return 2

    flagged = sum(1 for report in reports if report.findings)
    if args.json:
        print(json.dumps([asdict(report) for report in reports], ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print_text(report)
        print(f"{len(reports)}개 파일 중 {flagged}개 파일에 확인할 항목이 있다.")
    return 1 if args.strict and flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())
