"""Extract readable search text while preserving HTML block boundaries."""

from html.parser import HTMLParser


class _VisibleTextParser(HTMLParser):
    BLOCK_TAGS = {
        "blockquote", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6",
        "hr", "li", "p", "pre", "td", "th",
    }

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_tag = tag
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == self.hidden_tag:
            self.hidden_tag = None
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.hidden_tag is None:
            self.parts.append(data.replace("\n", " "))


def visible_text(html: str) -> str:
    """Keep block boundaries so product phrases cannot span unrelated paragraphs."""
    parser = _VisibleTextParser()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)
