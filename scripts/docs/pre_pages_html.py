"""Bounded HTML implied-end rules shared by source and built-page readers."""

from collections.abc import Sequence
from html.parser import HTMLParser

from scripts.docs.pre_pages import AuditFormatError


_P_CLOSERS = frozenset((
    "address", "article", "aside", "blockquote", "center", "details", "dialog", "dir",
    "div", "dl", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "li", "dt", "dd", "listing",
    "main", "menu", "nav", "ol", "p", "pre", "search", "section", "summary", "table", "ul",
))
_P_SCOPE = frozenset(("applet", "caption", "html", "table", "td", "th", "marquee", "object", "template", "button", "select", "svg", "math", "foreignobject"))
_LIST_SCOPE = (_P_CLOSERS | _P_SCOPE | {"body", "select", "option", "optgroup"}) - {"address", "div", "p"}
_TABLE_GROUPS = frozenset(("thead", "tbody", "tfoot"))
_TABLE_CONTENT = _TABLE_GROUPS | {"tr", "td", "th", "p"}
_FORMATTING = frozenset(("a", "b", "big", "code", "em", "font", "i", "nobr", "s", "small", "strike", "strong", "tt", "u"))
_END_CHILDREN = {
    **{tag: {"p"} for tag in _P_CLOSERS | {"body", "foreignobject"}},
    **{tag: {"li", "p"} for tag in ("ul", "ol", "menu")},
    "dl": {"dt", "dd", "p"},
    "tr": {"td", "th", "p"},
    **{tag: {"tr", "td", "th", "p"} for tag in _TABLE_GROUPS},
    "table": _TABLE_CONTENT | {"colgroup"},
    "select": {"option", "optgroup"},
    "optgroup": {"option"},
}
_TABLE_ALLOWED = _TABLE_CONTENT - {"p"} | {"caption", "colgroup", "col", "script", "style", "template"}


class AuditHTMLParser(HTMLParser):
    """Pin parent-page raw/RCDATA rules, including ignored non-void slashes."""

    CDATA_CONTENT_ELEMENTS = ("script", "style", "xmp", "iframe", "noembed", "noframes")
    RCDATA_CONTENT_ELEMENTS = ("textarea", "title")

    def __init__(self, *, convert_charrefs: bool = True) -> None:
        super().__init__(convert_charrefs=convert_charrefs)
        self.scripting = True

    def enter_raw_content(self, tag: str) -> bool:
        if tag in self.CDATA_CONTENT_ELEMENTS or tag in {"plaintext", "noscript"}:
            self.set_cdata_mode(tag, escapable=False)
            return True
        if tag in self.RCDATA_CONTENT_ELEMENTS:
            self.set_cdata_mode(tag, escapable=True)
            return True
        return False


def table_foster_context(stack: Sequence[str]) -> bool:
    for tag in reversed(stack):
        if tag in {"td", "th", "caption", "template", "script", "style", "svg", "math", "foreignobject"}:
            return False
        if tag in {"table", "tr"} | _TABLE_GROUPS:
            return True
    return False


def validate_table_text(stack: Sequence[str], text: str) -> None:
    if text.strip(" \t\n\r\f") and table_foster_context(stack):
        raise AuditFormatError("unsupported table foster-parenting text")


def _in_scope(stack: Sequence[str], targets: set[str] | frozenset[str], boundaries: set[str] | frozenset[str]) -> int | None:
    for index in range(len(stack) - 1, -1, -1):
        if stack[index] in targets:
            return index
        if stack[index] in boundaries:
            break
    return None


def open_p_in_scope(stack: Sequence[str]) -> bool:
    return _in_scope(stack, {"p"}, _P_SCOPE) is not None


def implied_end_on_start(stack: Sequence[str], tag: str) -> int | None:
    if table_foster_context(stack) and tag not in _TABLE_ALLOWED:
        raise AuditFormatError(f"unsupported table foster-parenting flow content: <{tag}>")
    index = None
    if tag in _TABLE_CONTENT - {"p"}:
        table = _in_scope(stack, {"table"}, {"template", "svg", "math"})
        if table is None or any(name not in _TABLE_CONTENT for name in stack[table + 1:]):
            raise AuditFormatError(f"unsupported ambiguous table context for <{tag}>")
        if tag in {"td", "th"} and "tr" not in stack[table + 1:]:
            raise AuditFormatError(f"unsupported table cell without a row: <{tag}>")
    if tag == "li":
        index = _in_scope(stack, {"li"}, _LIST_SCOPE)
    elif tag in {"dt", "dd"}:
        index = _in_scope(stack, {"dt", "dd"}, _LIST_SCOPE)
    elif tag in {"td", "th"}:
        index = _in_scope(stack, {"td", "th"}, {"tr", "table"} | _TABLE_GROUPS)
    elif tag == "tr":
        index = _in_scope(stack, {"tr"}, {"table"} | _TABLE_GROUPS)
    elif tag in _TABLE_GROUPS:
        index = _in_scope(stack, _TABLE_GROUPS, {"table"})
        if index is None:
            index = _in_scope(stack, {"tr"}, {"table"})
    elif tag == "option":
        index = _in_scope(stack, {"option"}, {"select", "optgroup"})
    elif tag == "optgroup":
        index = _in_scope(stack, {"optgroup"}, {"select"})
        if index is None:
            index = _in_scope(stack, {"option"}, {"select"})
    remaining = stack[:index] if index is not None else stack
    if tag in _P_CLOSERS:
        paragraph = _in_scope(remaining, {"p"}, _P_SCOPE)
        if paragraph is not None:
            index = paragraph
    if index is not None and any(name in _FORMATTING for name in stack[index + 1:]):
        raise AuditFormatError(f"unsupported ambiguous formatting adoption before <{tag}>")
    return index


def implied_end_on_end(stack: Sequence[str], tag: str) -> int | None:
    index = next((i for i in range(len(stack) - 1, -1, -1) if stack[i] == tag), None)
    if index is None:
        return None
    children = stack[index + 1:]
    if children and all(child in _END_CHILDREN.get(tag, ()) for child in children):
        return index + 1
    return None
