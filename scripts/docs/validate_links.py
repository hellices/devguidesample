"""Validate rendered local links, image targets, image alt text and pinned external sample links."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse

from markdown import Markdown
from mkdocs.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.docs.content import (
    DocumentFormatError,
    ValidationResult,
    iter_public_document_paths,
    load_taxonomy,
)
from scripts.docs.topics import build_topic_catalog


_GITHUB_REF_KINDS = frozenset(("blob", "tree", "raw", "commit"))


def _github_ref(target: str) -> tuple[str, str] | None:
    """(owner/repo in lower case, ref) of a GitHub link that names a ref, or None. Accepts http, https and
    protocol-relative URLs with any host case, github.com/<owner>/<repo>/(blob|tree|raw|commit)/<ref> and
    raw.githubusercontent.com/<owner>/<repo>/<ref>, where a tag may be spelled refs/tags/<tag>."""
    parsed = urlparse(target.removeprefix("<").removesuffix(">"))
    if parsed.scheme not in {"", "http", "https"} or not parsed.netloc:
        return None
    host = (parsed.hostname or "").lower().removeprefix("www.")
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if host == "github.com" and len(parts) >= 4 and parts[2] in _GITHUB_REF_KINDS:
        repository, rest = parts[:2], parts[3:]
    elif host == "raw.githubusercontent.com" and len(parts) >= 3:
        repository, rest = parts[:2], parts[2:]
    else:
        return None
    if len(rest) >= 3 and rest[0] == "refs" and rest[1] == "tags":
        return "/".join(repository).lower(), rest[2]
    if len(rest) >= 3 and rest[0] == "refs":
        # refs/heads/<name> is a branch even when it is named like the pinned tag, so it never matches a pin.
        return "/".join(repository).lower(), "/".join(rest[:3])
    return "/".join(repository).lower(), rest[0]


def _pins(samples) -> dict[str, list[str]]:
    """Repository (owner/name, lower case) -> pinned release tags and commits of the given external samples."""
    pins: dict[str, list[str]] = {}
    for sample in samples:
        if sample.repository and sample.ref:
            refs = pins.setdefault(sample.repository.removeprefix("https://github.com/").lower(), [])
            refs.extend(ref for ref in (sample.ref, sample.commit) if ref and ref not in refs)
    return pins


def _external_ref_errors(
    relative: str, target: str, topic_pins: dict[str, list[str]], all_pins: dict[str, list[str]]
) -> list[str]:
    """A link into an external sample repository must use a release tag or commit that a sample.yml pins. The
    document's own topic decides when it has a sample of that repository, so each topic keeps its own version."""
    link = _github_ref(target)
    if link is None:
        return []
    repository, ref = link
    expected = topic_pins.get(repository) or all_pins.get(repository)
    if expected is None or ref in expected:
        return []
    return [f"{relative}: link must use a pinned ref ({', '.join(expected)}) of {repository}: {target}"]


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


def _resolve_target(
    page: Path, docs_dir: Path, raw_target: str, *, directory_shorthand: bool = True
) -> Path | None:
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
    if not directory_shorthand:
        return None if path_text.endswith("/") else resolved
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
    try:
        catalog = build_topic_catalog(docs_dir, taxonomy)
    except DocumentFormatError as error:
        count = sum(1 for _ in iter_public_document_paths(docs_dir, taxonomy))
        return ValidationResult(count, [str(error)])
    published_targets = {(docs_dir / target).resolve() for target in catalog.published_assets}
    all_pins = _pins(sample for topic in catalog.topics.values() for sample in topic.samples)
    for document in catalog.documents:
        count += 1
        page = document.path
        relative = page.relative_to(root).as_posix()
        parser = _LinkParser()
        parser.feed(renderer.reset().convert(document.body))
        parser.close()
        # Rendered HTML positions do not correspond to Markdown source lines.
        for link in parser.links:
            if link.alt_text is not None and not link.alt_text:
                errors.append(f"{relative}: image alt text is required")
            topic = catalog.by_document.get(document.relative_path)
            topic_pins = _pins(topic.samples) if topic is not None else {}
            errors.extend(_external_ref_errors(relative, link.target, topic_pins, all_pins))
            target = _resolve_target(page, docs_dir, link.target)
            if target is not None and not target.exists():
                asset_target = _resolve_target(
                    page, docs_dir, link.target, directory_shorthand=False
                )
                if asset_target not in published_targets:
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
