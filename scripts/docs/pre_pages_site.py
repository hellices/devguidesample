"""Fail-closed inspection of rendered pre-Pages destinations and local assets."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
from typing import Mapping
from urllib.parse import unquote, urlsplit

import yaml

from scripts.docs.pre_pages import AuditFormatError, PrePagesInventory
from scripts.docs.topics import TopicCatalog


@dataclass(frozen=True)
class SiteInspection:
    errors: tuple[str, ...]
    details: Mapping[str, object]


_VOID = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
))
_INERT = frozenset(("script", "style", "template", "noscript"))
_CHROME = frozenset(("nav", "header", "footer", "aside"))


def _srcset(value: str) -> list[str]:
    """Read URL tokens without splitting embedded commas in data URLs."""
    urls = []
    remaining = value.strip()
    if not remaining:
        raise AuditFormatError("empty srcset")
    while remaining:
        match = re.match(r"(\S+)(.*)", remaining, re.DOTALL)
        assert match is not None
        token, remaining = match.groups()
        if token.endswith(","):
            token = token.rstrip(",")
        else:
            descriptors, _, remaining = remaining.partition(",")
            descriptors = descriptors.split()
            if len(descriptors) > 1 or any(
                not re.fullmatch(r"(?:[1-9]\d*w|(?:\d+(?:\.\d+)?|\.\d+)x)", item)
                or float(item[:-1]) <= 0
                for item in descriptors
            ):
                raise AuditFormatError(f"malformed srcset descriptors: {descriptors}")
        if not token:
            raise AuditFormatError("empty srcset URL")
        urls.append(token)
        remaining = remaining.strip()
    return urls


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.seen: Counter[str] = Counter()
        self.links: list[str] = []
        self.targets: list[tuple[str, str]] = []
        self.canonicals: list[str] = []
        self.refreshes: list[str] = []
        self.errors: list[str] = []
        self.anchor: tuple[str, bool] | None = None
        self.source_lines: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if len(attributes) != len(attrs):
            self.errors.append(f"duplicate attributes on <{tag}>")
        parents = {name for name, _ in self.stack}
        inert = bool(parents & _INERT)
        if "aria-hidden" in attributes and attributes["aria-hidden"] not in {"true", "false"}:
            self.errors.append(f"invalid aria-hidden attribute on <{tag}>")
        hidden = (
            any(hidden for _, hidden in self.stack)
            or "hidden" in attributes
            or (attributes.get("aria-hidden") or "").casefold() == "true"
            or bool(re.search(
                r"(?:display\s*:\s*none|visibility\s*:\s*hidden)",
                attributes.get("style") or "", re.IGNORECASE,
            ))
        )
        if tag in {"html", "head", "body"}:
            if (
                tag == "html" and self.stack
                or tag in {"head", "body"} and [name for name, _ in self.stack] != ["html"]
                or tag == "body" and self.seen["head"] != 1
            ):
                self.errors.append(f"misplaced <{tag}> element")
            self.seen[tag] += 1
        if tag == "base":
            self.errors.append("<base> would change local URL resolution")
        if not inert:
            if tag in {"img", "source"}:
                for attr in ("src", "srcset"):
                    if attr not in attributes:
                        continue
                    value = attributes[attr] or ""
                    try:
                        targets = _srcset(value) if attr == "srcset" else [value]
                        for target in targets:
                            if not target:
                                raise AuditFormatError(f"empty {tag} {attr}")
                            self.targets.append((f"{tag} {attr}", target))
                    except AuditFormatError as error:
                        self.errors.append(str(error))
                if tag == "img" and not {"src", "srcset"} & attributes.keys():
                    self.errors.append("<img> has neither src nor srcset")
            if tag == "a" and "href" in attributes:
                if "a" in parents:
                    self.errors.append("nested anchor elements")
                target = attributes["href"] or ""
                self.targets.append(("a href", target))
                if not hidden and not parents & _CHROME and "body" in parents:
                    self.anchor = (target, False)
            if tag in {"img", "svg"} and self.anchor is not None and not hidden:
                self.anchor = (self.anchor[0], True)
            if tag == "link" and "canonical" in (attributes.get("rel") or "").casefold().split():
                if "head" not in parents:
                    self.errors.append("canonical link is outside <head>")
                self.canonicals.append(attributes.get("href") or "")
            if tag == "meta" and (attributes.get("http-equiv") or "").casefold() == "refresh":
                if "head" not in parents:
                    self.errors.append("refresh metadata is outside <head>")
                self.refreshes.append(attributes.get("content") or "")
        if tag not in _VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _VOID | {"svg", "math"} and not {name for name, _ in self.stack} & {"svg", "math"}:
            self.errors.append(f"self-closing non-void HTML element <{tag}/>")
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.anchor is not None:
            target, visible = self.anchor
            if visible:
                self.links.append(target)
            self.anchor = None
        if not self.stack or self.stack[-1][0] != tag:
            self.errors.append(f"unmatched closing </{tag}>")
        else:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if (
            self.anchor is not None and data.strip()
            and not any(hidden or tag in _INERT for tag, hidden in self.stack)
        ):
            self.anchor = (self.anchor[0], True)

    def unknown_decl(self, data: str) -> None:
        self.errors.append(f"unknown HTML declaration: {data}")

    def handle_comment(self, data: str) -> None:
        line, column = self.getpos()
        if not self.source_lines[line - 1][column:].startswith("<!--"):
            self.errors.append(f"bogus HTML comment/declaration: {data}")

    def finish(self, text: str) -> None:
        self.source_lines = text.split("\n")
        self.feed(text)
        if self.rawdata:
            self.errors.append("truncated HTML token")
        self.close()
        if self.stack:
            self.errors.append("unclosed HTML elements: " + ", ".join(tag for tag, _ in self.stack))
        if any(self.seen[tag] != 1 for tag in ("html", "head", "body")):
            self.errors.append("expected exactly one html, head, and body element")


def _contained(root: Path, path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise AuditFormatError(f"{label}: unsafe path outside {root.name}: {path}")
    return resolved


class _Site:
    def __init__(self, root: Path, site_url: str) -> None:
        self.root = root.resolve()
        self.site_url = urlsplit(site_url)
        self.prefix = self.site_url.path.rstrip("/") + "/" if site_url else "/"

    def resolve(self, html_path: Path, raw: str) -> Path | None:
        try:
            url = urlsplit(raw)
            if url.scheme or url.netloc:
                if not (
                    self.site_url.netloc and url.scheme in {"http", "https"}
                    and url.netloc == self.site_url.netloc
                    and url.path.startswith(self.prefix)
                ):
                    return None
            if not url.path:
                return None
            if re.search(r"[\x00-\x20\x7f\\]", raw):
                raise ValueError("local URLs must encode spaces and reject controls/backslashes")
            if re.search(r"%(?![0-9a-fA-F]{2})", url.path):
                raise ValueError("malformed percent encoding")
            decoded = unquote(url.path, errors="strict")
            if re.search(r"[\x00-\x1f\x7f\\]", decoded):
                raise ValueError("control character or backslash in decoded path")
            if decoded.startswith("/"):
                if decoded.startswith(self.prefix):
                    decoded = decoded[len(self.prefix):]
                else:
                    decoded = decoded[1:]
                path = self.root / decoded
            else:
                path = html_path.parent / decoded
            path = _contained(self.root, path, f"unsafe URL {raw!r}")
            if url.path.endswith("/") or path.is_dir():
                path = _contained(self.root, path / "index.html", f"unsafe URL {raw!r}")
            return path
        except (ValueError, OSError, RuntimeError) as error:
            raise AuditFormatError(f"unsafe URL {raw!r}: {error}") from error


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuditFormatError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _invalid_json_constant(value: str) -> None:
    raise AuditFormatError(f"invalid JSON constant {value}")


def inspect_built_site(
    repo_root: Path, site_dir: Path, inventory: PrePagesInventory, catalog: TopicCatalog,
) -> SiteInspection:
    errors: list[str] = []
    counts = dict.fromkeys((
        "canonical_html", "redirects", "searchable_documents", "service_topics",
        "explore_documents", "published_assets", "rendered_local_targets", "html_pages",
    ), 0)
    try:
        config_path = repo_root / "mkdocs.yml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
        if not isinstance(config, dict) or not isinstance(config.get("site_url", ""), str):
            raise AuditFormatError("mkdocs.yml: site_url must be a string")
        site = _Site(site_dir, config.get("site_url", ""))
    except (OSError, ValueError, yaml.YAMLError) as error:
        return SiteInspection((f"site configuration: {error}",), counts)
    docs_root = (repo_root / "docs").resolve()
    pages: dict[Path, _Page | None] = {}
    resolved_links: dict[Path, set[Path]] = {}

    def read_page(path: Path, label: str) -> _Page | None:
        if path in pages:
            return pages[path]
        page = None
        try:
            safe = _contained(site.root, path, label)
            if not safe.is_file():
                raise AuditFormatError(f"{label}: missing HTML {path.relative_to(site.root)}")
            page = _Page()
            page.finish(safe.read_text(encoding="utf-8"))
            for error in page.errors:
                errors.append(f"{path.relative_to(site.root)}: malformed HTML: {error}")
            counts["html_pages"] += 1
        except (OSError, ValueError, RuntimeError, AssertionError) as error:
            errors.append(f"{path.relative_to(site.root)}: {label}: missing or malformed HTML: {error}")
            page = None
        pages[path] = page
        return page

    def target(path: Path, raw: str) -> Path | None:
        try:
            return site.resolve(path, raw)
        except AuditFormatError as error:
            errors.append(f"{path.relative_to(site.root)}: {error}")
            return None

    def links(path: Path, label: str) -> set[Path]:
        if path not in resolved_links:
            page = read_page(path, label)
            resolved_links[path] = {
                resolved for raw in page.links if (resolved := target(path, raw)) is not None
            } if page else set()
        return resolved_links[path]

    search_path = site.root / "search/search_index.json"
    published_targets = set(catalog.published_assets)
    published_paths = {site.root / path for path in published_targets}
    bases: Counter[Path] = Counter()
    search_locations: set[Path] = set()
    try:
        safe = _contained(site.root, search_path, "search index")
        data = json.loads(
            safe.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object, parse_constant=_invalid_json_constant,
        )
        if not isinstance(data, dict) or not isinstance(data.get("docs"), list):
            raise AuditFormatError("docs must be a list")
        seen = set()
        for i, entry in enumerate(data["docs"]):
            if not isinstance(entry, dict) or any(
                not isinstance(entry.get(key), str) for key in ("location", "title", "text")
            ):
                raise AuditFormatError(f"entry {i}: location, title, and text must be strings")
            raw = entry["location"]
            if re.search(r"[\x00-\x20\x7f\\]", raw):
                raise AuditFormatError(f"entry {i}: unsafe search location {raw!r}")
            url = urlsplit(raw)
            if url.scheme or url.netloc or url.query:
                raise AuditFormatError(f"entry {i}: invalid search location {raw!r}")
            if raw in seen:
                raise AuditFormatError(f"duplicate search location {raw!r}")
            seen.add(raw)
            resolved = site.resolve(site.root / "index.html", url.path or "./")
            if resolved in published_paths:
                raise AuditFormatError(f"entry {i}: published sample asset leaked into search: {raw!r}")
            if resolved is None or resolved.suffix != ".html" or not resolved.is_file():
                raise AuditFormatError(f"entry {i}: search location is not a built HTML page: {raw!r}")
            search_locations.add(resolved)
            if not url.fragment:
                bases[resolved] += 1
    except (OSError, ValueError, RuntimeError) as error:
        errors.append(f"search/search_index.json: malformed or missing search index: {error}")

    explore_path = site.root / "explore/index.html"
    explore_links = links(explore_path, "Explore index")
    by_path = {document.relative_path: document for document in catalog.documents}
    for entry in inventory.documents:
        canonical = catalog.redirects.get(entry.pages_path)
        document = by_path.get(canonical)
        if document is None:
            errors.append(f"{entry.pages_path}: missing canonical source redirect_from mapping")
            continue
        declarations = document.metadata.get("redirect_from")
        if not isinstance(declarations, list) or declarations.count(str(entry.pages_path)) != 1:
            errors.append(f"{canonical}: {entry.pages_path} must occur exactly once in redirect_from")
        source_path = docs_root / canonical
        try:
            if not _contained(docs_root, source_path, "canonical source").is_file():
                errors.append(f"{canonical}: missing canonical source")
        except (OSError, ValueError, RuntimeError) as error:
            errors.append(f"{canonical}: canonical source: {error}")
        canonical_html = site.root / canonical.with_suffix(".html")
        page = read_page(canonical_html, f"{canonical}: canonical")
        if page is not None and not page.errors:
            counts["canonical_html"] += 1
        if bases[canonical_html] != 1:
            errors.append(f"{canonical}: canonical base location must appear once in search")
        else:
            counts["searchable_documents"] += 1
        if canonical_html not in explore_links:
            errors.append(f"explore/index.html: canonical member not linked: {canonical}")
        else:
            counts["explore_documents"] += 1

        redirect_path = site.root / entry.pages_path.with_suffix(".html")
        if redirect_path in search_locations:
            errors.append(f"{entry.pages_path}: redirect location is present in search")
        redirect_page = read_page(redirect_path, f"{entry.pages_path}: redirect")
        if redirect_page is None:
            continue
        before = len(errors)

        def redirect_target(raw: str) -> Path | None:
            resolved = target(redirect_path, raw)
            if resolved is None:
                return None
            url = urlsplit(raw)
            return None if url.query or url.fragment else resolved

        if len(redirect_page.canonicals) != 1 or redirect_target(
            redirect_page.canonicals[0],
        ) != canonical_html:
            errors.append(f"{entry.pages_path}: redirect canonical target does not match {canonical}")
        refresh = (
            re.fullmatch(r"\s*0\s*;\s*url\s*=\s*(.*?)\s*", redirect_page.refreshes[0], re.IGNORECASE)
            if len(redirect_page.refreshes) == 1 else None
        )
        if refresh is None or redirect_target(refresh[1].strip("\"'")) != canonical_html:
            errors.append(f"{entry.pages_path}: redirect refresh target does not match {canonical}")
        if canonical_html not in links(redirect_path, "redirect fallback"):
            errors.append(f"{entry.pages_path}: redirect fallback link does not match {canonical}")
        if before == len(errors) and not redirect_page.errors:
            counts["redirects"] += 1

    for topic in catalog.topics.values():
        service_path = site.root / "services" / topic.primary_service / "index.html"
        expected = site.root / topic.entry.relative_path.with_suffix(".html")
        if expected not in links(service_path, "primary service index"):
            errors.append(
                f"{service_path.relative_to(site.root)}: topic entry not linked: {topic.entry.relative_path}"
            )
        else:
            counts["service_topics"] += 1

    for asset in catalog.published_assets.values():
        try:
            source = _contained(docs_root, docs_root / asset.source, "publish source")
            published = _contained(site.root, site.root / asset.target, "publish target")
            if source.read_bytes() != published.read_bytes():
                raise AuditFormatError("published bytes differ from sample source")
            counts["published_assets"] += 1
        except (OSError, ValueError, RuntimeError) as error:
            errors.append(f"{asset.target}: publish {asset.source}: {error}")

    for path in sorted(site.root.rglob("*")):
        relative = PurePosixPath(path.relative_to(site.root).as_posix())
        try:
            _contained(site.root, path, "built site")
        except (OSError, ValueError, RuntimeError) as error:
            errors.append(f"{relative}: {error}")
            continue
        if relative.parts[0] == "services" and "samples" in relative.parts:
            errors.append(f"{relative}: sample source leaked into built site")
        if path.suffix == ".html" and relative not in published_targets:
            read_page(path, str(relative))

    for path, page in pages.items():
        if page is None:
            continue
        for kind, raw in page.targets:
            resolved = target(path, raw)
            if resolved is not None:
                counts["rendered_local_targets"] += 1
                if not resolved.is_file():
                    errors.append(f"{path.relative_to(site.root)}: missing rendered {kind} target {raw!r}")
    return SiteInspection(tuple(dict.fromkeys(errors)), counts)
