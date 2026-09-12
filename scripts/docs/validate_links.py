"""Validate rendered local links, image targets, and image alt text."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlparse

from markdown import Markdown
from mkdocs.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.docs.content import DocumentFormatError, ValidationResult, load_document, load_taxonomy


@dataclass(frozen=True)
class _RenderedLink:
    target: str
    alt_text: str | None = None


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[_RenderedLink] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "img":
            target = attributes.get("src")
            alt_text = (attributes.get("alt") or "").strip()
        elif tag == "a":
            target = attributes.get("href")
            alt_text = None
        else:
            return
        if target is not None:
            self.links.append(_RenderedLink(target, alt_text))


def _candidate_paths(docs_dir: Path, taxonomy: Mapping[str, Any]) -> Iterable[Path]:
    for config in taxonomy.get("collections", {}).values():
        collection = docs_dir / config["path"]
        if collection.is_dir():
            yield from sorted(collection.rglob("index.md"))


def _resolve_target(page: Path, docs_dir: Path, raw_target: str) -> Path | None:
    target = raw_target.removeprefix("<").removesuffix(">")
    if target.startswith("#"):
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    path_text = unquote(parsed.path)
    if not path_text:
        return None
    resolved = (docs_dir / path_text.lstrip("/")) if path_text.startswith("/") else (page.parent / path_text)
    resolved = resolved.resolve()
    if resolved.is_dir() or path_text.endswith("/"):
        return resolved / "index.md"
    if not resolved.suffix:
        directory_index = resolved / "index.md"
        if directory_index.exists():
            return directory_index
    return resolved


def validate_repository(repo_root: Path | str) -> ValidationResult:
    root = Path(repo_root)
    docs_dir = root / "docs"
    taxonomy = load_taxonomy(root / "docs-taxonomy.yml")
    config = load_config(config_file=str(root / "mkdocs.yml"))
    renderer = Markdown(
        extensions=config.markdown_extensions, extension_configs=config.mdx_configs
    )
    errors: list[str] = []
    count = 0
    for page in _candidate_paths(docs_dir, taxonomy):
        count += 1
        relative = page.relative_to(root).as_posix()
        try:
            document = load_document(page, docs_dir=docs_dir)
        except DocumentFormatError as error:
            errors.append(str(error))
            continue
        parser = _LinkParser()
        parser.feed(renderer.reset().convert(document.body))
        parser.close()
        # Rendered HTML positions do not correspond to Markdown source lines.
        for link in parser.links:
            if link.alt_text is not None and not link.alt_text:
                errors.append(f"{relative}: image alt text is required")
            target = _resolve_target(page, docs_dir, link.target)
            if target is not None and not target.exists():
                errors.append(f"{relative}: target does not exist: {link.target}")
    return ValidationResult(count, errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    result = validate_repository(args.repo_root)
    if result.errors:
        print("\n".join(result.errors))
        return 1
    print(f"Validated links for {result.document_count} public documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
