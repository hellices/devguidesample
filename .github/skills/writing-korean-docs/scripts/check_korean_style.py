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
# Block patterns follow CommonMark and are matched against the part of a line left
# after the prefixes of its open containers are removed. A fence is three or more
# backticks or tildes, and a backtick fence's info string cannot contain a backtick.
FENCE_OPEN = re.compile(r" {0,3}(`{3,}(?=[^`]*$)|~{3,})")
QUOTE_MARKER = re.compile(r" {0,3}> ?")
LIST_ITEM = re.compile(r"( {0,3})([-*+]|\d{1,9}[.)])( +|$)")
THEMATIC_BREAK = re.compile(r" {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
# MkDocs admonition, collapsible details and content tabs indent their body by four.
BLOCK_CONTAINER = re.compile(r"( {0,3})(?:!!!|\?\?\?\+?|===)(?:\s|$)")
BLOCK_START = re.compile(
    r" {0,3}(?:#{1,6}(?:\s|$)|>|`{3,}|~{3,}|[-*+](?:\s|$)|\d{1,9}[.)](?:\s|$)"
    r"|!!!|\?\?\?|===)"
)
TABLE_DELIMITER = re.compile(r"\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?")
TABLE_BREAK = re.compile(
    r"(?:#{1,6}(?:\s|$)|>|`{3,}|~{3,}|[-*+]\s|\d{1,9}[.)]\s|(?:[-*_]\s*){3,}$)"
)
INLINE_CODE = re.compile(r"`[^`\n]+`")
# An inline comment inside a paragraph; it may wrap lines but not cross a blank line.
HTML_COMMENT = re.compile(r"<!--(?:(?!\n[ \t]*\n).)*?-->", re.S)
HTML_COMMENT_BLOCK = re.compile(r" {0,3}<!--")
# Only spaces and tabs may follow the marker, so an empty "#" heading never
# swallows the next line.
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)
QUOTE_PREFIX = re.compile(r"(?: {0,3}> ?)+")
# Python-Markdown treats "1)" as text, so only "1." opens an ordered item here.
HEADING_LIST_MARKER = re.compile(r" {0,3}(?:[-*+]|\d{1,9}\.)[ \t]+")
SETEXT_UNDERLINE = re.compile(r" {0,3}(=+|-+)[ \t]*$")
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.M)
BOLD = re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__")
# A paragraph that opens with a bold label: "**결론**: ..." or "**정리:** ...".
BOLD_LABEL = re.compile(r"\s*\*\*[^*\n]+?(?:[:：]\*\*|\*\*\s*[:：])")
LINK_LABEL = re.compile(r"\[[^\]]*\]")
# A link reference definition: "[label]: destination" with an optional title
# in quotes or parentheses on the same line or the next line.
LINK_REFERENCE = re.compile(
    r" {0,3}\[((?:[^\]\\\n]|\\.)+)\]:[ \t]*(?:<[^>\n]*>|\S+)"
    r"(?:[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?[ \t]*$"
)
LINK_REFERENCE_TITLE = re.compile(r"[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\))[ \t]*$")
# A full or collapsed reference link, "[text][ref]", "[text] [ref]" or "[text][]".
# Python-Markdown allows one whitespace character between the brackets.
REFERENCE_LINK = re.compile(r"(!?\[([^\]\n]*)\])\s?\[([^\]\n]*)\]")
# A shortcut reference link "[text]" not followed by a target, label or ":".
SHORTCUT_LINK = re.compile(r"!?\[([^\]\n]*)\](?![\[(:\ue000])")
# The rest of a line that holds only spaces or tabs, i.e. a blank line.
BLANK_LINE_AHEAD = re.compile(r"[ \t]*(?:\n|$)")
# Python-Markdown's RE_LINK form "(<target> \"title\")".
LINK_ANGLE_TARGET = re.compile(r"""\(\s*<[^<>]*>\s*(?:'[^']*'|"[^"]*")?\s*\)""")
# What may remain on a sources line once link labels are removed. A URL with its
# own parentheses leaves a stray ")" after the link target is stripped.
LINK_SEPARATORS = re.compile(r"[\s·,|/)\ue000]*")
EM_DASH = re.compile(r"—|(?<=\S) -- (?=\S)")
DOCUMENT_TYPE = re.compile(r"^document_type:\s*['\"]?([a-z-]+)", re.M)
# Report genres may title sections as "결과 1: 단건 레이턴시" or "부록: 비용 참고".
REPORT_TYPES = {"research", "lab"}


def _syllables(finals: set[int] = frozenset(), vowels: str = "") -> str:
    """Hangul syllables with one of the given final consonants, plus listed syllables."""
    chosen = [chr(code) for code in range(0xAC00, 0xD7A4) if (code - 0xAC00) % 28 in finals]
    return "".join(chosen) + vowels


# A heading reads as a sentence when it ends with a predicate ending. Without a
# morphological analyzer the syllable before "다" or "요" decides: a verb or
# adjective stem ends in a consonant such as ㄴ (한다, 는다), ㅆ (했다, 있다) or ㅄ
# (없다), or in a vowel listed here (하다, 되다, 다르다, 해요, 있어요). Nouns such as
# 개요, 필요, 바다 and 람다 do not match. Loanwords such as 판다 and 아젠다 still do.
_DA_STEM = _syllables(
    finals={1, 4, 6, 7, 8, 9, 11, 17, 18, 19, 20, 22, 25, 26, 27},
    vowels="하되이지리기르쓰키치주내두",
)
_YO_STEM = "어아여해돼봐줘워와져쳐려세에예네까지래게써나"
SENTENCE_HEADING = re.compile(
    rf"(?:니다|[{_YO_STEM}]요|[가-힣]죠|[{_DA_STEM}]다)[.!?]?$"
)
HEADING_ANCHOR = re.compile(r"\s*\{[^}]*\}\s*$")

# A whole word ending in a connective ending and followed by a comma.
CONNECTIVE_COMMA = re.compile(
    r"(?<![가-힣])([가-힣]*[가-힣](?:고|며|지만|면서|아서|어서|여서|는데|니까|므로))\s?,"
)
# Nouns that end in "고" and are often followed by a comma in a list. "보고" is left
# out because it is just as often the connective form of "보다".
NOUNS_ENDING_IN_GO = {
    "사고", "재고", "참고", "광고", "경고", "신고", "원고", "창고", "최고", "잔고",
    "비고", "공고", "투고", "기고", "회고", "숙고", "선고", "노고", "제고", "출고",
    "입고", "금고", "서고", "문고", "퇴고", "탈고", "상고", "로고", "망고", "시카고",
}
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

# Same polite endings as SENTENCE_HEADING: ~니다, ~요 after a verb stem, and ~죠.
FORMAL_END = re.compile(rf"(?:니다|니까|십시오|[{_YO_STEM}]요|[가-힣]죠)[.!?]$")
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
# Put after the "]" of a real link: an inline link whose target was removed, or
# a reference link whose label is defined. Other "[text]" renders with brackets.
LINK_END = "\ue000"
INLINE_LINK = re.compile(r"!?\[([^\]]*)\]" + LINK_END)
INLINE_EMPHASIS = re.compile(
    r"(\*\*|\*|~~)(?=\S)(.+?)(?<=\S)\1"
    r"|(?<![A-Za-z0-9])(__|_)(?=\S)(.+?)(?<=\S)\3(?![A-Za-z0-9])"
)


@dataclass
class Thresholds:
    bold_per_1000_chars: float = 2.0
    # A single conclusion line after a decision table is allowed; a summary box
    # at the end of every section is the pattern to catch.
    bold_label_lines: int = 1
    colon_headings: int = 0
    sentence_headings: int = 0
    connective_comma_per_100_sentences: float = 8.0
    adverb_comma: int = 0
    translationese_per_100_sentences: float = 6.0
    signature_phrases: int = 1
    contrast: int = 2
    em_dash_per_100_sentences: float = 10.0
    minority_ending_ratio: float = 0.15
    bullet_line_ratio: float = 0.35


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


# A container is a block quote (width None) or a block whose content is indented
# by a fixed width: a list item, admonition, details or tab block.
def continue_container(width: int | None, rest: str) -> str | None:
    """Strip one container's prefix from a line, or return None if it ended."""
    if width is None:
        marker = QUOTE_MARKER.match(rest)
        return rest[marker.end():] if marker else None
    if not rest.strip():
        return ""
    if rest[:width] == " " * width:
        return rest[width:]
    return None


def open_containers(rest: str, stack: list[int | None]) -> str:
    """Push containers that start on this line and return the line's content."""
    while rest.strip() and not THEMATIC_BREAK.match(rest):
        quote = QUOTE_MARKER.match(rest)
        if quote:
            stack.append(None)
            rest = rest[quote.end():]
            continue
        item = LIST_ITEM.match(rest)
        if item:
            width = list_content_indent(item)
            stack.append(width)
            rest = rest[width:]
            continue
        block = BLOCK_CONTAINER.match(rest)
        if block:
            stack.append(len(block.group(1)) + 4)
            return ""
        break
    return rest


def remove_fenced_code(text: str) -> str:
    """Drop fenced and indented code blocks and HTML comment blocks.

    Each line is matched against the open block quotes, list items and MkDocs
    admonition, details and tab blocks first. A fence is recognized in what is
    left, indented at most three spaces, so "> ```" and "- ```" open a fence.
    A fence closes on a line of the same character at least as long as the
    opening fence, or when a container it belongs to ends. An unclosed fence
    runs to the end of the document.

    What is left after the container prefixes and indented four or more spaces
    is an indented code block, unless it continues a paragraph. A top-level
    "    ```" line is therefore code, as in CommonMark, and so is the indented
    text under it.

    A line that starts with "<!--" opens an HTML comment block that runs to
    the line containing "-->". Fences inside it are ignored. A comment opened
    inside a block quote also ends when that quote ends, as the site renderer
    does; inside a list item it stays open, as it does on the rendered page.
    """
    kept: list[str] = []
    stack: list[int | None] = []
    fence: str | None = None
    fence_depth = 0
    in_comment = False
    comment_depth = 0
    previous_blank = True
    # True while the previous kept line belongs to a paragraph that an indented
    # line could lazily continue.
    in_paragraph = False
    for raw in text.splitlines():
        rest = raw.expandtabs(4)
        matched = 0
        for width in stack:
            remainder = continue_container(width, rest)
            if remainder is None:
                break
            rest, matched = remainder, matched + 1
        if in_comment:
            if None in stack[matched:comment_depth]:
                # The block quote holding the comment ended; this line is new content.
                in_comment = False
            else:
                # An HTML comment block runs to the line that contains "-->".
                in_comment = "-->" not in raw
                continue
        if fence is not None:
            if matched >= fence_depth:
                closing = rest.strip()
                if (
                    closing
                    and len(rest) - len(rest.lstrip(" ")) <= 3
                    and set(closing) == {fence[0]}
                    and len(closing) >= len(fence)
                ):
                    fence = None
                    previous_blank = False
                    in_paragraph = False
                continue
            fence, previous_blank, in_paragraph = None, True, False
        blank = not rest.strip()
        # An unmatched container ends unless the line lazily continues the
        # previous paragraph.
        if matched < len(stack) and (previous_blank or blank or BLOCK_START.match(rest)):
            del stack[matched:]
            in_paragraph = False
        if blank:
            kept.append(raw)
            previous_blank = True
            in_paragraph = False
            continue
        previous_blank = False
        if matched == len(stack):
            indent = len(rest) - len(rest.lstrip(" "))
            if indent >= 4 and not in_paragraph:
                continue
            rest = open_containers(rest, stack)
            if HTML_COMMENT_BLOCK.match(rest):
                in_comment = "-->" not in rest[rest.index("<!--") + 4:]
                comment_depth = len(stack)
                in_paragraph = False
                continue
            opener = FENCE_OPEN.match(rest)
            if opener:
                fence, fence_depth = opener.group(1), len(stack)
                in_paragraph = False
                continue
            in_paragraph = (
                bool(rest.strip())
                and not BLOCK_START.match(rest)
                and not THEMATIC_BREAK.match(rest)
            )
        kept.append(raw)
    return "\n".join(kept)


@dataclass
class LineBody:
    """A line split into its container prefix and the content inside it."""
    prefix: str
    body: str
    # Quote depth and whether a four-space container block was stripped.
    container: tuple[int, bool]


def container_bodies(lines: list[str]) -> list[LineBody]:
    """Strip block quote markers and the indent of container blocks from each line.

    A line indented four or more spaces belongs to a container block (a list
    item's later block, or an admonition, details or tab body) when its
    indented run starts after a blank line or a "!!!", "???" or "===" opener.
    Otherwise the indent is kept, as for a line that lazily continues a list
    item's first block.
    """
    out: list[LineBody] = []
    starts_block = False
    for index, line in enumerate(lines):
        quoted = _strip_quotes(line)
        if index:
            previous = _strip_quotes(lines[index - 1])
            if not previous.strip() or BLOCK_CONTAINER.match(previous):
                starts_block = True
            elif _indent(previous) < 4:
                starts_block = False
        indented = _indent(quoted) >= 4 and starts_block
        body = quoted.lstrip(" \t") if indented else quoted
        depth = line[: len(line) - len(quoted)].count(">")
        out.append(LineBody(line[: len(line) - len(body)], body, (depth, indented)))
    return out


def convert_setext_headings(text: str) -> str:
    """Rewrite Setext headings ("제목\n===", "제목\n---") as ATX headings.

    Python-Markdown, which the site uses, makes a heading only from the first
    line of a block followed by the underline in the same container. A longer
    paragraph above "---" stays a paragraph and the "---" becomes a thematic
    break; "===" stays text. A block starts after a blank line, an ATX
    heading, or a change of container such as a new block quote. The front
    matter is removed before this runs.
    """
    lines = text.splitlines()
    bodies = container_bodies(lines)
    for index in range(1, len(lines)):
        under, title = bodies[index], bodies[index - 1]
        underline = SETEXT_UNDERLINE.fullmatch(under.body)
        if (
            not underline
            or under.container != title.container
            or not _setext_title(title.body)
            or not _starts_block(bodies, index - 1)
        ):
            continue
        level = "#" if underline.group(1)[0] == "=" else "##"
        lines[index - 1] = f"{title.prefix}{level} {title.body.strip()}"
        lines[index] = under.prefix.rstrip()
    return "\n".join(lines)


def _setext_title(body: str) -> bool:
    return (
        bool(body.strip())
        and _indent(body) <= 3
        and not BLOCK_START.match(body)
        and "|" not in body
    )


def _starts_block(bodies: list[LineBody], index: int) -> bool:
    if index == 0:
        return True
    previous = bodies[index - 1]
    return (
        previous.container != bodies[index].container
        or not previous.body.strip()
        or bool(HEADING.match(previous.body) and previous.body.startswith("#"))
    )


def heading_matches(lines: list[str]) -> dict[int, re.Match[str]]:
    """Return ATX heading matches by line index, including headings in containers.

    The site renderer shows these as headings, so they are matched after the
    container prefix is removed (see container_bodies):
    - "> ## 제목" at any quote depth, including a quote that continues a paragraph
    - "- ## 제목" and "1. ## 제목" on the list marker line ("1)" is not a list)
    - a line in a container block indented by four or more spaces
    A line that lazily continues a list item's first block keeps its indent
    and is not a heading, and neither is any line that starts with a space.
    """
    found: dict[int, re.Match[str]] = {}
    for index, line in enumerate(container_bodies(lines)):
        body = line.body
        item = HEADING_LIST_MARKER.match(body)
        if item:
            body = body[item.end():]
        # Python-Markdown needs "#" at the start of the line, so "   ## 제목" is text.
        match = HEADING.match(body) if body.startswith("#") else None
        if match:
            found[index] = match
    return found


def _strip_quotes(line: str) -> str:
    quotes = QUOTE_PREFIX.match(line)
    return line[quotes.end():] if quotes else line


def _indent(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


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
    number of cells and runs until a blank line or another block starts. Rows
    are matched after container prefixes are removed, so a table inside a
    block quote, list item or admonition counts. As on the site, a line
    without the quote marker lazily continues a quoted table as another row.
    """
    rows: set[int] = set()
    bodies = container_bodies(lines)
    index = 1
    while index < len(lines):
        header, delimiter = bodies[index - 1].body.strip(), bodies[index].body.strip()
        if (
            index - 1 not in rows
            # An unquoted delimiter lazily continues a quoted header; a quoted
            # one under an unquoted header starts a new block.
            and bodies[index].container[0] <= bodies[index - 1].container[0]
            and "|" in header
            and "|" in delimiter
            and TABLE_DELIMITER.fullmatch(delimiter)
            and table_cells(header) == table_cells(delimiter)
        ):
            rows.update((index - 1, index))
            index += 1
            while index < len(lines):
                row = bodies[index].body.strip()
                if not row or TABLE_BREAK.match(row) or BLOCK_CONTAINER.match(row):
                    break
                rows.add(index)
                index += 1
            continue
        index += 1
    return rows


def paragraph_lines(lines: list[str], tables: set[int]) -> list[int]:
    """Return indexes of explanation-paragraph lines.

    Headings, table rows, list items with their continuation lines, block
    quotes and HTML lines are left out. Those are where the scan format of
    result and comparison sections keeps its bold labels, rating symbols and
    dash-joined fragments.
    """
    kept: list[int] = []
    headings = heading_matches(lines)
    in_list = False
    previous_blank = True
    for index, line in enumerate(lines):
        body = line.strip()
        if not body:
            previous_blank = True
            continue
        indented = len(line) - len(line.lstrip(" ")) >= 2
        if index in tables or index in headings:
            in_list = False
        elif re.match(r" {0,3}>", line) or body.startswith("<"):
            in_list = False
        elif LIST_ITEM.match(line) and line[LIST_ITEM.match(line).end() - 1 :].strip() != "":
            in_list = True
        elif in_list and (indented or not previous_blank):
            pass
        else:
            in_list = False
            kept.append(index)
        previous_blank = False
    return kept


def is_exempt_label(lines: list[str], index: int, tables: set[int]) -> bool:
    """A label alone on its line that opens a list or table, or a sources line."""
    line = lines[index]
    label = BOLD_LABEL.match(line)
    rest = line[label.end():] if label else ""
    if LINK_LABEL.search(rest) and LINK_SEPARATORS.fullmatch(LINK_LABEL.sub("", rest)):
        return True
    if rest.strip():
        return False
    for following in range(index + 1, len(lines)):
        if lines[following].strip():
            return following in tables or bool(LIST_ITEM.match(lines[following]))
    return False


def strip_link_targets(text: str) -> str:
    """Remove inline link destinations, keeping "]" and marking it with LINK_END.

    A destination is "<...>" or a run that may contain balanced parentheses
    and backslash escapes, as in CommonMark: "[설명](https://x/a_(b)/c)".
    Only a "](" that closes an unescaped "[" in the same paragraph starts a
    destination, so plain text such as "조건](작업을 수행한다.)" is kept. An
    unbalanced destination is left as it is.
    """
    out: list[str] = []
    open_brackets = 0
    index, length = 0, len(text)
    while index < length:
        char = text[index]
        if char == "\\" and index + 1 < length:
            out.append(text[index : index + 2])
            index += 2
            continue
        if char == "\n" and BLANK_LINE_AHEAD.match(text, index + 1):
            open_brackets = 0
        elif char == "[":
            open_brackets += 1
        elif char == "]" and open_brackets:
            open_brackets -= 1
            if text.startswith("(", index + 1):
                end = _link_target_end(text, index + 2)
                if end is not None:
                    out.append("]" + LINK_END)
                    index = end
                    continue
        out.append(char)
        index += 1
    return "".join(out)


def _link_target_end(text: str, start: int) -> int | None:
    """Return the index after the ")" closing a link target that starts at start.

    This follows Python-Markdown's LinkInlineProcessor.getLink, which the site
    uses: a quoted title may hold "(" or ")", and spaces are allowed in the
    destination. Backslash escapes are already placeholders there, so "\\)"
    never closes the target. The target cannot cross a blank line.
    """
    limit = _paragraph_end(text, start)
    angle = LINK_ANGLE_TARGET.match(text, start - 1, limit)
    if angle:
        return angle.end()
    index = start
    while index < limit and text[index].isspace():
        index += 1
    bracket_count = backtrack_count = 1
    last_bracket = -1
    quote = alt_quote = None
    exit_quote = exit_alt_quote = -1
    in_title = False
    last = ""
    while index < limit:
        char = text[index]
        if char == "\\":
            last = char
            index += 2
            continue
        if char == "(":
            if not in_title:
                bracket_count += 1
            elif backtrack_count > 0:
                backtrack_count -= 1
        elif char == ")":
            if (exit_quote != -1 and quote == last) or (exit_alt_quote != -1 and alt_quote == last):
                bracket_count = 0
            elif not in_title:
                bracket_count -= 1
            elif backtrack_count > 0:
                backtrack_count -= 1
                if backtrack_count == 0:
                    last_bracket = index + 1
        elif char in "'\"":
            if not quote:
                in_title = True
                backtrack_count = bracket_count
                bracket_count = 1
                quote = char
            elif char != quote and not alt_quote:
                alt_quote = char
            elif char == quote:
                exit_quote = index + 1
            elif char == alt_quote:
                exit_alt_quote = index + 1
        index += 1
        if bracket_count == 0:
            return index
        if char != " ":
            last = char
    if backtrack_count == 0:
        # Python-Markdown keeps index -1 here, so the link runs to the
        # paragraph's last character.
        return last_bracket if last_bracket != -1 else max(limit - 1, start)
    return None


def _paragraph_end(text: str, start: int) -> int:
    """Return the index of the newline that starts the next blank line."""
    index = text.find("\n", start)
    while index != -1:
        if BLANK_LINE_AHEAD.match(text, index + 1):
            return index
        index = text.find("\n", index + 1)
    return len(text)


def mask_quotes(prose: str) -> str:
    """Join each paragraph onto one line and replace quoted spans with a token."""
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", prose):
        joined = " ".join(part.strip() for part in paragraph.splitlines() if part.strip())
        if joined:
            paragraphs.append(QUOTED.sub("QUOTE", joined))
    return "\n\n".join(paragraphs)


def remove_link_references(text: str, labels: set[str] | None = None) -> str:
    """Blank out link reference definitions, which are not rendered.

    A definition starts a paragraph and may carry its title on the next line.
    It cannot interrupt a paragraph, so "[a]: b" in the middle of prose stays.
    The normalized label of each definition is added to labels when given.
    """
    lines = text.splitlines()
    previous_blank = True
    index = 0
    while index < len(lines):
        line = lines[index]
        definition = LINK_REFERENCE.fullmatch(line) if previous_blank else None
        if definition:
            if labels is not None:
                labels.add(_reference_label(definition.group(1)))
            lines[index] = ""
            following = index + 1
            if following < len(lines) and LINK_REFERENCE_TITLE.fullmatch(lines[following]):
                lines[following] = ""
                index = following
            # Consecutive definitions may follow without a blank line.
            index += 1
            continue
        previous_blank = not line.strip()
        index += 1
    return "\n".join(lines)


def _reference_label(label: str) -> str:
    return " ".join(label.split()).lower()


def resolve_reference_links(text: str, labels: set[str]) -> str:
    """Mark reference links whose label is defined, keeping only "[text]".

    The site shows "[설정합니다.][guide]", "[설정합니다.][]" and
    "[설정합니다.]" as "설정합니다." when the label is defined. An undefined
    reference stays as the literal text it renders as, brackets included.
    """
    def full(match: re.Match[str]) -> str:
        label = match.group(3) or match.group(2)
        if _reference_label(label) in labels:
            return match.group(1) + LINK_END
        return match.group(0)

    def shortcut(match: re.Match[str]) -> str:
        if _reference_label(match.group(1)) in labels:
            return match.group(0) + LINK_END
        return match.group(0)

    return SHORTCUT_LINK.sub(shortcut, REFERENCE_LINK.sub(full, text))


def strip_markup(text: str) -> tuple[str, str]:
    """Return (markdown without code, prose-only text)."""
    text = FRONT_MATTER.sub("", text, count=1)
    # Code is removed before comments so "<!--" inside code never starts one.
    text = remove_fenced_code(text)
    text = convert_setext_headings(text)
    text = INLINE_CODE.sub("CODE", text)
    text = HTML_COMMENT.sub("", text)
    labels: set[str] = set()
    text = remove_link_references(text, labels)
    text = resolve_reference_links(text, labels)
    markdown = strip_link_targets(text)
    lines = markdown.splitlines()
    tables = table_rows(lines)
    headings = heading_matches(lines)
    prose_lines = []
    for index, line in enumerate(lines):
        if index in headings or index in tables or THEMATIC_BREAK.match(line):
            prose_lines.append("")
            continue
        prose_lines.append(BULLET.sub("", line))
    prose = "\n".join(prose_lines)
    prose = re.sub(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__", lambda m: m.group(1) or m.group(2), prose)
    return markdown, prose.replace(LINK_END, "")


def normalize_inline(text: str) -> str:
    """Reduce real link labels and emphasis to plain text.

    Brackets that are not a link stay, as the site shows them.
    """
    text = INLINE_LINK.sub(r"\1", text).replace(LINK_END, "")
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


def collect_connective_commas(text: str, limit: int = 3) -> tuple[int, list[str]]:
    matches = [m for m in CONNECTIVE_COMMA.finditer(text) if m.group(1) not in NOUNS_ENDING_IN_GO]
    examples = []
    for match in matches[:limit]:
        start, end = max(match.start() - 18, 0), min(match.end() + 18, len(text))
        examples.append(text[start:end].replace("\n", " ").strip())
    return len(matches), examples


def analyze(path: Path, limits: Thresholds) -> Report:
    source = path.read_text(encoding="utf-8")
    front = FRONT_MATTER.match(source)
    kind = DOCUMENT_TYPE.search(front.group(0)) if front else None
    document_type = kind.group(1) if kind else ""
    markdown, prose = strip_markup(source)
    text = mask_quotes(prose)
    sentences = split_sentences(text)
    report = Report(
        path=str(path),
        prose_chars=len(re.sub(r"\s", "", prose)),
        sentences=len(sentences),
        lines=sum(1 for line in markdown.splitlines() if line.strip()),
    )
    metrics, examples = report.metrics, report.examples
    # Unrounded values for threshold checks; metrics hold rounded values for display.
    raw: dict[str, float] = {}

    def ratio(key: str, value: float, digits: int) -> None:
        raw[key] = value
        metrics[key] = round(value, digits)
    per100 = 100 / max(len(sentences), 1)

    headings = [
        normalize_inline(HEADING_ANCHOR.sub("", m.group(2)))
        for m in heading_matches(markdown.splitlines()).values()
    ]
    colon_headings = [h for h in headings if re.search(r"\S\s?[:：]\s+\S", h)]
    if document_type in REPORT_TYPES:
        metrics["report_colon_headings"] = len(colon_headings)
        colon_headings = []
    metrics["colon_headings"] = len(colon_headings)
    if colon_headings:
        examples["colon_headings"] = colon_headings[:3]
    sentence_headings = [h for h in headings if SENTENCE_HEADING.search(h)]
    metrics["sentence_headings"] = len(sentence_headings)
    if sentence_headings:
        examples["sentence_headings"] = sentence_headings[:3]

    lines = markdown.splitlines()
    tables = table_rows(lines)
    paragraphs = paragraph_lines(lines, tables)
    labels = [i for i in paragraphs if BOLD_LABEL.match(lines[i])]
    exempt = {i for i in labels if is_exempt_label(lines, i, tables)}
    bold = sum(len(BOLD.findall(lines[i])) for i in paragraphs if i not in exempt)
    metrics["bold"] = len(BOLD.findall(markdown))
    metrics["paragraph_bold"] = bold
    ratio("bold_per_1000_chars", bold * 1000 / max(report.prose_chars, 1), 2)
    flagged_labels = [lines[i].strip() for i in labels if i not in exempt]
    metrics["bold_label_lines"] = len(flagged_labels)
    if flagged_labels:
        examples["bold_label_lines"] = [label[:40] for label in flagged_labels[:3]]
    # "* * *" and "- - -" are thematic breaks, not list items.
    bullets = sum(1 for line in lines if BULLET.match(line) and not THEMATIC_BREAK.match(line))
    ratio("bullet_line_ratio", bullets / max(report.lines, 1), 2)
    ratio("table_line_ratio", len(tables) / max(report.lines, 1), 2)

    count, found = collect_connective_commas(text)
    metrics["connective_comma"] = count
    ratio("connective_comma_per_100_sentences", count * per100, 1)
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
    ratio("translationese_per_100_sentences", total * per100, 1)

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

    # Join each run of consecutive paragraph lines before masking quotes, so a
    # quotation that wraps across lines is masked as a whole.
    blocks: list[list[str]] = []
    for position, line_index in enumerate(paragraphs):
        if position and line_index == paragraphs[position - 1] + 1:
            blocks[-1].append(lines[line_index].strip())
        else:
            blocks.append([lines[line_index].strip()])
    dashes = sum(len(EM_DASH.findall(QUOTED.sub("QUOTE", " ".join(block)))) for block in blocks)
    metrics["em_dash"] = dashes
    ratio("em_dash_per_100_sentences", dashes * per100, 1)

    formal = sum(1 for s in sentences if FORMAL_END.search(s))
    plain = sum(1 for s in sentences if not FORMAL_END.search(s) and PLAIN_END.search(s))
    ended = formal + plain
    metrics["formal_endings"] = formal
    metrics["plain_endings"] = plain
    ratio("minority_ending_ratio", min(formal, plain) / ended if ended else 0.0, 2)

    lengths = [len(re.sub(r"\s", "", s)) for s in sentences]
    if len(lengths) >= 2:
        mean = statistics.mean(lengths)
        metrics["sentence_chars_mean"] = round(mean, 1)
        metrics["sentence_chars_cv"] = round(statistics.pstdev(lengths) / mean, 2)

    checks = [
        ("bold_per_1000_chars", limits.bold_per_1000_chars,
         "설명 문단에 굵은 글씨가 많다. 처음 정의하는 용어나 놓치면 안 되는 한 곳에만 쓴다."),
        ("bold_label_lines", limits.bold_label_lines,
         "'**꼬리표**:'로 시작하는 결론 문단이 반복된다. 결론은 한 번만 두고 나머지는 문장으로 풀어 쓴다."),
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
        ("em_dash_per_100_sentences", limits.em_dash_per_100_sentences,
         "설명 문단에서 대시(—)로 문장을 자주 잇는다. 쉼표·괄호·새 문장으로 바꾼다."),
        ("minority_ending_ratio", limits.minority_ending_ratio,
         "'~다'와 '~니다' 종결이 섞여 있다. 문서 하나에서 한 가지로 통일한다."),
        ("bullet_line_ratio", limits.bullet_line_ratio,
         "글머리표 줄 비율이 높다. 결과·비교가 아닌 설명은 문단으로 쓴다."),
    ]
    for key, limit, message in checks:
        value = raw.get(key, metrics.get(key, 0))
        if value > limit:
            shown = round(value, 3) if isinstance(value, float) else value
            report.findings.append(f"{key}={shown} (기준 {limit}) {message}")
    return report


def iter_markdown(paths: list[str]) -> list[Path]:
    """Return Markdown files under the given paths once each, in input order."""
    files: list[Path] = []
    seen: set[Path] = set()
    for item in paths:
        path = Path(item)
        if path.is_dir():
            found = sorted(p for p in path.rglob("*.md") if p.is_file())
        elif path.is_file():
            found = [path]
        else:
            raise FileNotFoundError(item)
        for file in found:
            key = file.resolve()
            if key not in seen:
                seen.add(key)
                files.append(file)
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
