"""Inherited HTML visibility and authored content, without navigation copies."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
import unicodedata

from scripts.docs.pre_pages import AuditFormatError
from scripts.docs.pre_pages_css import inline_visibility, presentation_visibility

_VOID = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
))
_NONCONTENT = frozenset(("head", "script", "style", "template", "noscript", "title"))
_CHROME = frozenset(("nav", "header", "footer", "aside"))
_CHROME_CLASSES = frozenset((
    "headerlink", "md-nav", "md-sidebar", "md-search", "md-content__button", "linenos",
))
_BLOCKS = frozenset(("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "th", "td", "dt", "dd", "figcaption"))
_SVG_METADATA = frozenset(("defs", "symbol", "title", "desc", "metadata", "clippath", "mask", "pattern", "marker"))
_SVG_ICONS = frozenset(("md-icon", "twemoji", "emojione"))
_SUMMARY_CONTROLS = frozenset(("button", "input", "select", "textarea", "details", "label", "iframe", "object"))


@dataclass(frozen=True)
class Visibility:
    display_hidden: bool = False
    visibility_hidden: bool = False
    aria_hidden: bool = False
    inert: bool = False

    def descend(self, attributes: dict[str, str | None], *, svg: bool = False) -> Visibility:
        style = presentation_visibility(attributes) if svg else {}
        style.update(inline_visibility(attributes.get("style") or ""))
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
    attributes: dict[str, str | None]
    children: list[_Element | str] = field(default_factory=list)
    visibility: Visibility = field(default_factory=Visibility)
    svg: bool = False


class AuthoredContent(HTMLParser):
    """Resolve the complete tree before collecting authored blocks or reachable links."""

    def __init__(self, *, material_article: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.material_article = material_article
        self.root = _Element("", {})
        self.stack = [self.root]
        self.articles = 0
        self.blocks: Counter[tuple[str, str]] = Counter()
        self.links: list[str] = []
        self.hidden: str | None = None

    @staticmethod
    def normalize(text: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", text).split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {}
        for name, value in attrs:
            attributes.setdefault(name, value)
        element = _Element(tag, attributes)
        self.stack[-1].children.append(element)
        if tag not in _VOID:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)

    def handle_endtag(self, tag: str) -> None:
        index = next((i for i in range(len(self.stack) - 1, 0, -1) if self.stack[i].tag == tag), None)
        if index is None:
            return
        del self.stack[index:]

    def _resolve(self, element: _Element, parent: Visibility, svg: bool = False) -> None:
        element.svg = svg or element.tag == "svg"
        try:
            element.visibility = parent.descend(element.attributes, svg=element.svg)
        except AuditFormatError as error:
            raise AuditFormatError(f"<{element.tag}>: {error}") from error
        for child in element.children:
            if isinstance(child, _Element):
                self._resolve(child, element.visibility, element.svg and element.tag != "foreignobject")

    def _summary_hit(self, element: _Element) -> bool:
        state = element.visibility
        if (
            element.tag in _NONCONTENT | _SUMMARY_CONTROLS
            or element.tag == "a" and "href" in element.attributes
            or state.display_hidden or state.aria_hidden or state.inert
        ):
            return False
        if state.interactive and (
            element.tag in {"summary", "img", "svg"}
            or any(isinstance(child, str) and child.strip() for child in element.children)
        ):
            return True
        return any(self._summary_hit(child) for child in element.children if isinstance(child, _Element))

    def _collect(
        self, element: _Element, *, active: bool, authored_excluded: bool = False,
        link_excluded: bool = False, in_body: bool = False, in_main: bool = False,
        svg_text: bool = False, svg_excluded: bool = False, icon: bool = False,
        blocked: bool = False,
    ) -> tuple[str, bool]:
        tag, attributes, state = element.tag, element.attributes, element.visibility
        if tag in _NONCONTENT:
            return "", False
        classes = set((attributes.get("class") or "").split())
        chrome = tag in _CHROME or bool(classes & _CHROME_CLASSES)
        authored_excluded |= self.material_article and chrome
        link_excluded |= chrome
        in_body |= tag == "body"
        in_main |= tag == "main"
        article = (
            tag == "article" and {"md-content__inner", "md-typeset"} <= classes
            and in_main and not authored_excluded
        )
        self.articles += article
        active |= article
        icon |= bool(classes & _SVG_ICONS)
        svg_excluded |= element.svg and (
            tag in _SVG_METADATA or icon
            or (attributes.get("aria-hidden") or "").casefold() == "true"
            or (attributes.get("role") or "").casefold() in {"none", "presentation"}
        )
        svg_text = element.svg and (svg_text or tag == "text")
        authored = active and not authored_excluded and not svg_excluded
        readable_text = authored and (not element.svg or svg_text)
        visible = not blocked and not state.hidden
        interactive = in_body and not link_excluded and not blocked and state.interactive
        parts: list[str] = []
        hit = interactive and tag in {"img", "svg"}
        if tag == "img" and authored:
            label = self.normalize(attributes.get("alt") or "")
            if visible:
                self.blocks[("img", label)] += 1
                parts.append(label)
            else:
                self.hidden = self.hidden or label or "<img>"
        elif tag == "br" and readable_text and visible:
            parts.append(" ")

        summary = next((
            child for child in element.children
            if isinstance(child, _Element) and child.tag == "summary"
        ), None) if tag == "details" else None
        closed_body = tag == "details" and "open" not in attributes and not (
            self._summary_hit(summary) if summary else state.interactive
        )
        for child in element.children:
            child_blocked = blocked or closed_body and child is not summary
            if isinstance(child, str):
                if readable_text:
                    if visible and not child_blocked:
                        parts.append(child)
                    elif value := self.normalize(child):
                        self.hidden = self.hidden or value[:160]
                if interactive and not child_blocked and child.strip():
                    hit = True
            else:
                text, child_hit = self._collect(
                    child, active=active, authored_excluded=authored_excluded,
                    link_excluded=link_excluded, in_body=in_body, in_main=in_main,
                    svg_text=svg_text, svg_excluded=svg_excluded, icon=icon,
                    blocked=child_blocked,
                )
                parts.append(text)
                hit |= child_hit
        text = "".join(parts)
        if authored and (value := self.normalize(text)):
            if tag in _BLOCKS:
                self.blocks[(tag, value)] += 1
            elif element.svg and tag == "text":
                self.blocks[("svg-text", value)] += 1
        if tag == "a" and "href" in attributes and in_body and not link_excluded and hit:
            self.links.append(attributes["href"] or "")
        return text, hit

    def close(self) -> None:
        super().close()
        self._resolve(self.root, Visibility())
        self.articles = 0
        self.blocks.clear()
        self.links.clear()
        self.hidden = None
        self._collect(self.root, active=not self.material_article)
