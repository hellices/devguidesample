"""Fail-closed inspection of rendered pre-Pages destinations and local assets."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from ipaddress import IPv4Address, IPv6Address
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Mapping
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from mkdocs.structure.files import File
import yaml

from scripts.docs.pre_pages import AuditFormatError, PrePagesInventory
from scripts.docs.pre_pages_content import create_semantic_renderer
from scripts.docs.pre_pages_visibility import AuthoredContent
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
_HTML_WHITESPACE = " \t\n\f\r"
_URL_C0_SPACE = "".join(chr(codepoint) for codepoint in range(0x21))
_URL_REMOVED_CONTROLS = str.maketrans("", "", "\t\n\r")


def _valid_srcset_descriptor(value: str) -> bool:
    width = re.fullmatch(r"([0-9]+)w", value)
    if width:
        return any(digit != "0" for digit in width[1])
    if re.fullmatch(r"-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?x", value):
        density = float(value[:-1])
        return math.isfinite(density) and density >= 0
    # HTML treats even the future-compatible h descriptor as a parse error.
    return False


def _srcset(value: str) -> list[str]:
    """Read URL tokens without splitting embedded commas in data URLs."""
    urls = []
    remaining = value.strip(_HTML_WHITESPACE)
    if not remaining:
        raise AuditFormatError("empty srcset")
    while remaining:
        if remaining.startswith(","):
            raise AuditFormatError("empty srcset candidate")
        match = re.match(r"([^ \t\n\f\r]+)(.*)", remaining, re.DOTALL)
        assert match is not None
        token, remaining = match.groups()
        if token.endswith(","):
            if token.endswith(",,"):
                raise AuditFormatError("empty srcset candidate")
            token = token[:-1]
        else:
            descriptors, _, remaining = remaining.partition(",")
            descriptors = re.findall(r"[^ \t\n\f\r]+", descriptors)
            if len(descriptors) > 1 or any(not _valid_srcset_descriptor(item) for item in descriptors):
                raise AuditFormatError(f"malformed srcset descriptors: {descriptors}")
        if not token:
            raise AuditFormatError("empty srcset URL")
        urls.append(token)
        remaining = remaining.strip(_HTML_WHITESPACE)
    return urls


def _refresh_url(value: str) -> str | None:
    space = r"[ \t\n\f\r]*"
    match = re.fullmatch(
        rf"""{space}0{space};{space}url{space}={space}(?:"([^"']+)"|'([^"']+)'|([^"']+?)){space}""",
        value, re.IGNORECASE,
    )
    return next(group for group in match.groups() if group is not None) if match else None


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.seen: Counter[str] = Counter()
        self.links: list[str] = []
        self.targets: list[tuple[str, str]] = []
        self.canonicals: list[str] = []
        self.refreshes: list[str] = []
        self.errors: list[str] = []
        self.source_lines: list[str] = []
        self.authored = AuthoredContent(material_article=True)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if len(attributes) != len(attrs):
            self.errors.append(f"duplicate attributes on <{tag}>")
        parents = set(self.stack)
        inert = bool(parents & _INERT)
        if "aria-hidden" in attributes and attributes["aria-hidden"] not in {"true", "false"}:
            self.errors.append(f"invalid aria-hidden attribute on <{tag}>")
        if tag in {"html", "head", "body"}:
            if (
                tag == "html" and self.stack
                or tag in {"head", "body"} and self.stack != ["html"]
                or tag == "body" and self.seen["head"] != 1
            ):
                self.errors.append(f"misplaced <{tag}> element")
            self.seen[tag] += 1
        if tag == "base":
            self.errors.append("<base> would change local URL resolution")
        if not inert:
            resource = None
            if tag == "script" and "src" in attributes:
                resource = ("script src", attributes["src"] or "")
            elif tag == "link":
                relations = set((attributes.get("rel") or "").casefold().split())
                destination = (attributes.get("as") or "").casefold()
                if "stylesheet" in relations:
                    resource = ("link stylesheet href", attributes.get("href") or "")
                elif "preload" in relations and destination in {"style", "script"}:
                    resource = ("link preload href", attributes.get("href") or "")
                elif "modulepreload" in relations and destination in {"", "script", "worker", "sharedworker", "serviceworker"}:
                    resource = ("link modulepreload href", attributes.get("href") or "")
            if resource is not None:
                if resource[1]:
                    self.targets.append(resource)
                else:
                    self.errors.append(f"empty {resource[0]} URL")
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
            if tag == "link" and "canonical" in (attributes.get("rel") or "").casefold().split():
                if "head" not in parents:
                    self.errors.append("canonical link is outside <head>")
                self.canonicals.append(attributes.get("href") or "")
            if tag == "meta" and (attributes.get("http-equiv") or "").casefold() == "refresh":
                if "head" not in parents:
                    self.errors.append("refresh metadata is outside <head>")
                self.refreshes.append(attributes.get("content") or "")
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _VOID | {"svg", "math"} and not set(self.stack) & {"svg", "math"}:
            self.errors.append(f"self-closing non-void HTML element <{tag}/>")
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unmatched closing </{tag}>")
        else:
            self.stack.pop()

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
            self.errors.append("unclosed HTML elements: " + ", ".join(self.stack))
        if any(self.seen[tag] != 1 for tag in ("html", "head", "body")):
            self.errors.append("expected exactly one html, head, and body element")
        self.authored.feed(text)
        self.authored.close()
        self.links = self.authored.links


def _contained(root: Path, path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise AuditFormatError(f"{label}: unsafe path outside {root.name}: {path}")
    return resolved


class _Site:
    def __init__(self, root: Path, site_url: str) -> None:
        self.root = root.resolve()
        self.site_url = urlsplit(site_url or "https://pre-pages.invalid/")
        if (
            self.site_url.scheme not in {"http", "https"} or not self.site_url.hostname
            or self.site_url.query or self.site_url.fragment
        ):
            raise AuditFormatError("site_url must be an absolute HTTP(S) deployment URL")
        self.origin = self._origin(self.site_url)
        self.prefix = self.site_url.path.rstrip("/") + "/"
        self.base = urlunsplit((*self.site_url[:2], self.prefix, "", ""))

    @staticmethod
    def _origin(url) -> tuple[str, str | None, int | None]:
        host = None
        if url.netloc:
            if not url.netloc.isascii() or "%" in url.netloc or "@" in url.netloc:
                raise ValueError("encoded, Unicode, or userinfo authorities are unsupported")
            if url.netloc.startswith("["):
                authority = re.fullmatch(r"\[([^\]]+)\](?::([0-9]+))?", url.netloc)
                if authority is None:
                    raise ValueError("malformed IPv6 authority or port")
                host = str(IPv6Address(authority[1]))
            else:
                authority = re.fullmatch(r"([A-Za-z0-9.-]+)(?::([0-9]+))?", url.netloc)
                if authority is None:
                    raise ValueError("malformed authority or port")
                host = authority[1].lower()
                if len(host) > 253 or any(
                    not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in host.split(".")
                ):
                    raise ValueError("unsupported hostname spelling")
                last_label = host.rsplit(".", 1)[-1]
                if last_label.isdigit() or re.fullmatch(r"0x[0-9a-f]+", last_label):
                    host = str(IPv4Address(host))
        port = url.port if url.port is not None else {"http": 80, "https": 443}.get(url.scheme)
        return url.scheme, host, port

    def resolve(self, html_path: Path, raw: str, *, same_document: bool = False) -> Path | None:
        try:
            if re.match(r"^[\x00-\x20]*(?:/|%2[fF]){3}", raw):
                raise ValueError("ambiguous leading slashes must be rejected before URL parsing")
            if "\\" in raw or re.match(r"^[\x00-\x20]*[A-Za-z][:|]", raw):
                raise ValueError("Windows drive or backslash syntax is not a web URL")
            # HTML attributes are already entity-decoded; do not decode them again.
            scheme_spelling = raw.strip(_URL_C0_SPACE).translate(_URL_REMOVED_CONTROLS)
            scheme = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", scheme_spelling)
            if scheme is not None and scheme[1].lower() in {"javascript", "vbscript", "file"}:
                raise ValueError(f"unsafe URL scheme {scheme[1].lower()!r}")
            url = urlsplit(raw)
            if url.scheme in {"http", "https"} and not url.netloc:
                raise ValueError("absolute HTTP(S) URLs require an explicit authority")
            if (url.netloc or url.scheme in {"http", "https"}) and re.search(r"[\x00-\x1f\x7f]", raw):
                raise ValueError("control characters in web URLs are unsupported")
            if not url.path and not url.scheme and not url.netloc:
                return _contained(self.root, html_path, "same-document URL") if same_document else None
            if not (url.scheme or url.netloc) or self._origin(
                url._replace(scheme=url.scheme or self.site_url.scheme),
            ) == self.origin:
                if re.search(r"%(?![0-9a-fA-F]{2})", url.path):
                    raise ValueError("malformed percent encoding")
                if "//" in unquote(url.path, errors="strict"):
                    raise ValueError("repeated path slashes are ambiguous before URL normalization")
                for segment in url.path.split("/"):
                    if segment not in {".", ".."} and any(
                        decoded in {".", ".."} for decoded in unquote(segment, errors="strict").split("/")
                    ):
                        raise ValueError("encoded dot segments are not published paths")
            document_url = urljoin(self.base, quote(html_path.relative_to(self.root).as_posix()))
            resolved_url = urlsplit(urljoin(document_url, raw))
            if self._origin(resolved_url) != self.origin:
                return None
            if re.search(r"[\x00-\x20\x7f\\]", raw):
                raise ValueError("local URLs must encode spaces and reject controls/backslashes")
            if re.search(r"%(?![0-9a-fA-F]{2})", resolved_url.path):
                raise ValueError("malformed percent encoding")
            if re.match(r"^/?[A-Za-z][:|]", unquote(url.path, errors="strict")):
                raise ValueError("decoded Windows drive syntax is not a web path")
            decoded = unquote(resolved_url.path, errors="strict")
            if re.search(r"[\x00-\x1f\x7f\\]", decoded):
                raise ValueError("control character or backslash in decoded path")
            if any(segment in {".", ".."} for segment in decoded.split("/")):
                raise ValueError("encoded/decoded dot segments are not published paths")
            prefix = unquote(self.prefix, errors="strict")
            if not decoded.startswith(prefix):
                raise ValueError(f"URL is outside the configured deployment prefix {self.prefix!r}")
            path = self.root / decoded[len(prefix):]
            path = _contained(self.root, path, f"unsafe URL {raw!r}")
            if decoded.endswith("/") or path.is_dir():
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
    counts["current_document_count"] = len(catalog.documents)
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
    markdown_aliases: dict[Path, PurePosixPath] = {}
    for published in sorted(published_targets):
        files = (
            File(published.as_posix(), str(docs_root), str(site.root), directory_urls)
            for directory_urls in (True, False)
        )
        aliases = {
            PurePosixPath(file.dest_uri) for file in files if file.is_documentation_page()
        }
        for alias in sorted(aliases):
            path = site.root / alias
            markdown_aliases[path] = published
            try:
                if _contained(site.root, path, "published Markdown alias").exists():
                    errors.append(f"{published}: published Markdown built HTML alias exists: {alias}")
            except (OSError, ValueError, RuntimeError) as error:
                errors.append(f"{published}: built HTML alias {alias}: {error}")
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
            resolved = site.resolve(site.root / "index.html", raw, same_document=True)
            url = urlsplit(raw)
            if url.scheme or url.netloc or url.query:
                raise AuditFormatError(f"entry {i}: invalid search location {raw!r}")
            if raw in seen:
                raise AuditFormatError(f"duplicate search location {raw!r}")
            seen.add(raw)
            if resolved in markdown_aliases:
                raise AuditFormatError(
                    f"entry {i}: published Markdown search alias for {markdown_aliases[resolved]}: {raw!r}"
                )
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
    mapped = set()
    for entry in inventory.documents:
        canonical = catalog.redirects.get(entry.pages_path)
        document = by_path.get(canonical)
        if document is None:
            errors.append(f"{entry.pages_path}: missing canonical source redirect_from mapping")
            continue
        declarations = document.metadata.get("redirect_from")
        if not isinstance(declarations, list) or declarations.count(str(entry.pages_path)) != 1:
            errors.append(f"{canonical}: {entry.pages_path} must occur exactly once in redirect_from")
        if canonical in mapped:
            errors.append(f"{canonical}: baseline mapping uses a current document more than once")
        mapped.add(canonical)

    for document in catalog.documents:
        canonical = document.relative_path
        declarations = document.metadata.get("redirect_from", [])
        if not isinstance(declarations, list):
            errors.append(f"{canonical}: redirect_from must be a list")
        else:
            for raw in declarations:
                if (
                    not isinstance(raw, str) or raw != PurePosixPath(raw).as_posix()
                    or catalog.redirects.get(PurePosixPath(raw)) != canonical
                ):
                    errors.append(f"{canonical}: invalid or unmapped redirect_from declaration {raw!r}")
        source_path = docs_root / canonical
        try:
            if not _contained(docs_root, source_path, "canonical source").is_file():
                errors.append(f"{canonical}: missing canonical source")
        except (OSError, ValueError, RuntimeError) as error:
            errors.append(f"{canonical}: canonical source: {error}")
        canonical_html = site.root / canonical.with_suffix(".html")
        page = read_page(canonical_html, f"{canonical}: canonical")
        if page is not None and not page.errors:
            try:
                authored = AuthoredContent()
                authored.feed(create_semantic_renderer().convert(document.body))
                authored.close()
            except (ValueError, RuntimeError, AssertionError) as error:
                errors.append(f"{canonical}: cannot inspect authored source visibility: {error}")
            else:
                expected_h1 = Counter({key: count for key, count in authored.blocks.items() if key[0] == "h1"})
                label = canonical_html.relative_to(site.root)
                if page.authored.articles != 1:
                    errors.append(f"{label}: expected exactly one Material authored content article")
                elif not expected_h1 or expected_h1 - page.authored.blocks:
                    errors.append(f"{label}: canonical article lacks a visible authored H1")
                elif page.authored.hidden:
                    errors.append(f"{label}: persistently hidden authored content: {page.authored.hidden}")
                elif missing := authored.blocks - page.authored.blocks:
                    tag, text = next(iter(missing))
                    errors.append(f"{label}: canonical article lacks visible authored <{tag}> structure: {text[:160]}")
                else:
                    counts["canonical_html"] += 1
        if bases[canonical_html] != 1:
            errors.append(f"{canonical}: canonical base location must appear once in search")
        else:
            counts["searchable_documents"] += 1
        if canonical_html not in explore_links:
            errors.append(f"explore/index.html: canonical member not linked: {canonical}")
        else:
            counts["explore_documents"] += 1

    for pages_path, canonical in catalog.redirects.items():
        document = by_path.get(canonical)
        declarations = document.metadata.get("redirect_from", []) if document is not None else []
        if not isinstance(declarations, list) or declarations.count(str(pages_path)) != 1:
            errors.append(f"{canonical}: {pages_path} must occur exactly once in redirect_from")
        canonical_html = site.root / canonical.with_suffix(".html")
        redirect_path = site.root / pages_path.with_suffix(".html")
        if redirect_path in search_locations:
            errors.append(f"{pages_path}: redirect location is present in search")
        redirect_page = read_page(redirect_path, f"{pages_path}: redirect")
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
            errors.append(f"{pages_path}: redirect canonical target does not match {canonical}")
        refresh = _refresh_url(redirect_page.refreshes[0]) if len(redirect_page.refreshes) == 1 else None
        if refresh is None or redirect_target(refresh) != canonical_html:
            errors.append(f"{pages_path}: redirect refresh target does not match {canonical}")
        if canonical_html not in links(redirect_path, "redirect fallback"):
            errors.append(f"{pages_path}: redirect fallback link does not match {canonical}")
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
