"""Inherited HTML visibility and authored content, without navigation copies."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from html.parser import HTMLParser
import re
import unicodedata


_VOID = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
))
_NONCONTENT = frozenset(("head", "script", "style", "template", "noscript", "title"))
_CHROME = frozenset(("nav", "header", "footer", "aside", "svg"))
_CHROME_CLASSES = frozenset((
    "headerlink", "md-nav", "md-sidebar", "md-search", "md-content__button", "linenos",
))
_BLOCKS = frozenset(("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "th", "td", "dt", "dd", "figcaption"))


def _inline_visibility(style: str) -> dict[str, str]:
    declarations: dict[str, tuple[bool, str]] = {}
    for declaration in re.sub(r"/\*.*?\*/", "", style, flags=re.DOTALL).split(";"):
        name, _, value = declaration.partition(":")
        name, value = name.strip().casefold(), value.strip().casefold()
        if name not in {"display", "visibility"}:
            continue
        important = bool(re.search(r"!\s*important\s*$", value))
        value = re.sub(r"!\s*important\s*$", "", value).strip()
        allowed = (
            {"none", "block", "inline", "inline-block", "flex", "inline-flex", "grid", "inline-grid",
             "table", "table-row", "table-cell", "list-item", "contents", "flow-root",
             "initial", "inherit", "unset", "revert", "revert-layer"}
            if name == "display" else {"visible", "hidden", "collapse", "initial", "inherit", "unset", "revert", "revert-layer"}
        )
        if value in allowed and (important or not declarations.get(name, (False, ""))[0]):
            declarations[name] = (important, value)
    return {name: value for name, (_, value) in declarations.items()}


@dataclass(frozen=True)
class Visibility:
    display_hidden: bool = False
    visibility_hidden: bool = False
    aria_hidden: bool = False
    inert: bool = False

    def descend(self, attributes: dict[str, str | None]) -> Visibility:
        style = _inline_visibility(attributes.get("style") or "")
        visibility = style.get("visibility")
        return Visibility(
            self.display_hidden or "hidden" in attributes or style.get("display") == "none",
            visibility in {"hidden", "collapse"} if visibility in {"visible", "hidden", "collapse", "initial"} else self.visibility_hidden,
            self.aria_hidden or (attributes.get("aria-hidden") or "").casefold() == "true",
            self.inert or "inert" in attributes,
        )

    @property
    def hidden(self) -> bool:
        return self.display_hidden or self.visibility_hidden or self.aria_hidden

    @property
    def interactive(self) -> bool:
        return not self.hidden and not self.inert


@dataclass
class _Element:
    tag: str
    visibility: Visibility
    active: bool
    excluded: bool
    text: list[str] | None
    closed_details: bool
    summary_interactive: bool | None = None

    @property
    def body_inaccessible(self) -> bool:
        return self.closed_details and (self.visibility.inert or self.summary_interactive is False)


class AuthoredContent(HTMLParser):
    """Collect visible authored blocks; closed details remain user-openable."""

    def __init__(self, *, material_article: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.material_article = material_article
        self.stack: list[_Element] = []
        self.articles = 0
        self.blocks: Counter[tuple[str, str]] = Counter()
        self.hidden: str | None = None

    @staticmethod
    def normalize(text: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", text).split())

    def _text(self, data: str) -> None:
        for parent in self.stack:
            if parent.text is not None:
                parent.text.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {}
        for name, value in attrs:
            attributes.setdefault(name, value)
        parent = self.stack[-1] if self.stack else None
        visibility = (parent.visibility if parent else Visibility()).descend(attributes)
        if parent and parent.tag == "details":
            if tag == "summary" and parent.summary_interactive is None:
                parent.summary_interactive = visibility.interactive
            elif parent.body_inaccessible:
                visibility = replace(visibility, display_hidden=True)
        classes = set((attributes.get("class") or "").split())
        excluded = bool(
            parent and parent.excluded or tag in _NONCONTENT
            or self.material_article and (tag in _CHROME or classes & _CHROME_CLASSES)
        )
        article = (
            tag == "article" and {"md-content__inner", "md-typeset"} <= classes
            and any(element.tag == "main" for element in self.stack) and not excluded
        )
        self.articles += article
        active = not self.material_article or article or bool(parent and parent.active)
        if active and not excluded:
            if tag == "img":
                label = self.normalize(attributes.get("alt") or "")
                if visibility.hidden:
                    self.hidden = self.hidden or label or "<img>"
                else:
                    self.blocks[("img", label)] += 1
                    self._text(label)
            elif tag == "br" and not visibility.hidden:
                self._text(" ")
        if tag not in _VOID:
            self.stack.append(_Element(
                tag, visibility, active, excluded,
                [] if active and not excluded and tag in _BLOCKS else None,
                tag == "details" and "open" not in attributes,
            ))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if not self.stack or not self.stack[-1].active or self.stack[-1].excluded:
            return
        if self.stack[-1].visibility.hidden or self.stack[-1].body_inaccessible:
            if value := self.normalize(data):
                self.hidden = self.hidden or value[:160]
        else:
            self._text(data)

    def handle_endtag(self, tag: str) -> None:
        index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i].tag == tag), None)
        if index is None:
            return
        for element in self.stack[index:]:
            if element.text is not None and (value := self.normalize("".join(element.text))):
                self.blocks[(element.tag, value)] += 1
        del self.stack[index:]
