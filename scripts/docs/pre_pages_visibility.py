"""Inherited HTML visibility and authored content, without navigation copies."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import unicodedata

from scripts.docs.pre_pages import AuditFormatError
from scripts.docs.pre_pages_css import inline_visibility, presentation_visibility
from scripts.docs.pre_pages_html import (
    AuditHTMLParser, implied_end_on_end, implied_end_on_start, open_p_in_scope, validate_table_text,
)

_VOID = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
))
_NONCONTENT = frozenset(("head", "script", "style", "template", "noscript", "title", "iframe", "noembed", "noframes"))
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
        visibility_hidden = self.visibility_hidden
        if visibility in {"hidden", "collapse"}:
            visibility_hidden = True
        elif visibility in {"visible", "initial"}:
            visibility_hidden = False
        return Visibility(
            self.display_hidden or "hidden" in attributes or style.get("display") == "none",
            visibility_hidden,
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
    evidence_visible: bool = False
    evidence_text_visible: bool = False
    evidence_interactive: bool = False


@dataclass(frozen=True)
class SemanticEvidence:
    links: tuple[tuple[str, str], ...]
    images: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _SemanticEvent:
    kind: str
    element: _Element | None
    text: str = ""


class AuthoredContent(AuditHTMLParser):
    """Resolve the complete tree before collecting authored blocks or reachable links."""

    def __init__(self, *, material_article: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.material_article = material_article
        self.root = _Element("", {})
        self.stack = [self.root]
        self.semantic_events: list[_SemanticEvent] = []
        self.articles = 0
        self.blocks: Counter[tuple[str, str]] = Counter()
        self.links: list[str] = []
        self.hidden: str | None = None

    @staticmethod
    def normalize(text: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", text).split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        parent = self.stack[-1]
        if not parent.svg or parent.tag == "foreignobject":
            index = implied_end_on_start([element.tag for element in self.stack], tag)
            if index is not None:
                del self.stack[index:]
        attributes = {}
        for name, value in attrs:
            attributes.setdefault(name, value)
        element = _Element(tag, attributes)
        parent = self.stack[-1]
        element.svg = tag == "svg" or parent.svg and parent.tag != "foreignobject"
        self.stack[-1].children.append(element)
        self.semantic_events.append(_SemanticEvent("start", element))
        if tag not in _VOID:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        # HTML ignores a non-void element's slash; foreign elements can self-close.
        if tag not in _VOID and (
            self.stack[-1].svg or any(parent.tag == "math" for parent in self.stack)
        ):
            self.handle_endtag(tag)
        else:
            self.enter_raw_content(tag)

    def handle_data(self, data: str) -> None:
        if self.cdata_elem is None:
            validate_table_text([element.tag for element in self.stack], data)
        self.stack[-1].children.append(data)
        self.semantic_events.append(_SemanticEvent("data", self.stack[-1], data))

    def handle_endtag(self, tag: str) -> None:
        names = [element.tag for element in self.stack]
        if tag == "p" and not open_p_in_scope(names):
            self.semantic_events.append(_SemanticEvent("end", None, tag))
            return
        implied = implied_end_on_end(names, tag)
        if implied is not None:
            del self.stack[implied:]
        index = next((i for i in range(len(self.stack) - 1, 0, -1) if self.stack[i].tag == tag), None)
        self.semantic_events.append(_SemanticEvent("end", self.stack[index] if index is not None else None, tag))
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
        element.evidence_visible = authored and visible
        element.evidence_text_visible = readable_text and visible
        evidence_hit = authored and not blocked and state.interactive and tag in {"img", "svg"}
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
            self._summary_hit(summary) if summary else False
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
                if readable_text and not child_blocked and state.interactive and child.strip():
                    evidence_hit = True
            else:
                text, child_hit = self._collect(
                    child, active=active, authored_excluded=authored_excluded,
                    link_excluded=link_excluded, in_body=in_body, in_main=in_main,
                    svg_text=svg_text, svg_excluded=svg_excluded, icon=icon,
                    blocked=child_blocked,
                )
                parts.append(text)
                hit |= child_hit
                evidence_hit |= child.evidence_interactive
        text = "".join(parts)
        if authored and (value := self.normalize(text)):
            if tag in _BLOCKS:
                self.blocks[(tag, value)] += 1
            elif element.svg and tag == "text":
                self.blocks[("svg-text", value)] += 1
        if tag == "a" and "href" in attributes and in_body and not link_excluded and hit:
            self.links.append(attributes["href"] or "")
        element.evidence_interactive = evidence_hit
        return text, hit

    def close(self) -> None:
        super().close()
        self._resolve(self.root, Visibility())
        self.articles = 0
        self.blocks.clear()
        self.links.clear()
        self.hidden = None
        self._collect(self.root, active=not self.material_article)

    def semantic_evidence(self, raw_tags: frozenset[str], hidden_tags: frozenset[str]) -> SemanticEvidence:
        """Keep raw destinations and labels; use the already-finalized inclusion state."""
        links: list[tuple[str, str]] = []
        images: list[tuple[str, str]] = []
        raw: list[str] = []
        anchor: tuple[_Element, str, list[str]] | None = None

        def finish_anchor() -> None:
            nonlocal anchor
            if anchor is not None:
                links.append(("".join(anchor[2]), anchor[1]))
                anchor = None

        # Raw/code boundaries remain lexical even when the renderer splits paragraphs.
        for event in self.semantic_events:
            element = event.element
            if event.kind == "start":
                assert element is not None
                if not raw:
                    if element.tag == "a" and "href" in element.attributes and element.evidence_interactive:
                        finish_anchor()
                        anchor = (element, element.attributes["href"] or "", [])
                    elif element.tag == "img" and "src" in element.attributes and element.evidence_visible:
                        alt = element.attributes.get("alt") or ""
                        images.append((alt, element.attributes["src"] or ""))
                        if anchor is not None:
                            anchor[2].append(alt)
                if element.tag in raw_tags:
                    raw.append(element.tag)
            elif event.kind == "data":
                if anchor is not None and element is not None and element.evidence_text_visible and not set(raw) & hidden_tags:
                    anchor[2].append(event.text)
            else:
                tag = event.text
                if tag == "a" and not raw and anchor is not None and (element is None or element is anchor[0]):
                    finish_anchor()
                if tag in raw:
                    index = len(raw) - 1 - raw[::-1].index(tag)
                    del raw[index:]
        finish_anchor()
        return SemanticEvidence(tuple(links), tuple(images))
