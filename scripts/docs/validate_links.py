"""Validate rendered local links, image targets, image alt text and pinned external sample links."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from dataclasses import dataclass
import os
from html.parser import HTMLParser
from pathlib import Path
import subprocess
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
    target = target.removeprefix("<").removesuffix(">")
    # For http(s) and protocol-relative URLs a browser treats "\" as "/", including right after the host, so normalize
    # before parsing the authority; it also drops one trailing dot of an absolute DNS name.
    if target.lower().startswith(("http:", "https:")) or target[:2].replace("\\", "/") == "//":
        target = target.replace("\\", "/")
    parsed = urlparse(target)
    if parsed.scheme not in {"", "http", "https"} or not parsed.netloc:
        return None
    host = (parsed.hostname or "").lower().removesuffix(".").removeprefix("www.")
    parts: list[str] = []
    # Browsers remove "." and ".." segments (also when percent-encoded) before requesting the URL, so resolve them
    # the same way; otherwise ".../blob/<pin>/../main/..." would look pinned while opening a branch.
    for part in (unquote(part) for part in parsed.path.split("/") if part):
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    if host == "github.com" and len(parts) >= 4 and parts[2] in _GITHUB_REF_KINDS:
        repository, rest = parts[:2], parts[3:]
    elif host == "raw.githubusercontent.com" and len(parts) >= 3:
        repository, rest = parts[:2], parts[2:]
    else:
        return None
    if len(rest) >= 3 and rest[0] == "refs" and rest[1] == "tags":
        # Pinned release tags are SemVer names without "/", so the tag is the single path segment after refs/tags.
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


RemoteRefs = Callable[[str, str], "dict[str, str] | None"]


def _ls_remote(repository: str, ref: str) -> dict[str, str] | None:
    """Ref name -> commit for the release tag (and its peeled commit), a branch of the same name and any branch or tag
    nested below it (for example refs/heads/<ref>/docs), or None when the remote cannot be queried."""
    command = [
        "git", "ls-remote", f"{repository}.git", f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}", f"refs/heads/{ref}",
        f"refs/heads/{ref}/*", f"refs/tags/{ref}/*",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, timeout=60, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return {name: sha for sha, _, name in (line.partition("\t") for line in result.stdout.splitlines() if line)}


def _release_errors(samples: Iterable, remote_refs: RemoteRefs) -> list[str]:
    """The pinned release tag of each external sample resolves to its pinned commit, and no branch shares the tag
    name: GitHub /blob/<name>/ links cannot tell a tag from a branch of the same name."""
    errors: list[str] = []
    # One remote lookup per repository and tag reports the tag-level problems once; every manifest's commit is still
    # compared with the resolved tag because manifests sharing a tag may pin different commits.
    lookups: dict[tuple[str, str], dict[str, str] | None] = {}
    for sample in samples:
        if sample.kind != "external" or not sample.repository or not sample.ref:
            continue
        key = (sample.repository.lower(), sample.ref)
        label = f"{sample.relative_path.as_posix()}: {sample.repository} {sample.ref}"
        first = key not in lookups
        if first:
            lookups[key] = remote_refs(sample.repository, sample.ref)
        refs = lookups[key]
        if refs is None:
            if first:
                errors.append(f"{label}: cannot query the repository to verify the release tag")
            continue
        tagged = refs.get(f"refs/tags/{sample.ref}^{{}}") or refs.get(f"refs/tags/{sample.ref}")
        if tagged is None:
            if first:
                errors.append(f"{label}: release tag does not exist")
        elif tagged != sample.commit:
            errors.append(f"{label}: release tag points at {tagged} but sample.yml commit is {sample.commit}")
        if first and f"refs/heads/{sample.ref}" in refs:
            errors.append(f"{label}: a branch has the same name as the release tag; delete it so links stay pinned")
        # GitHub /blob/<ref>/<path> links do not mark where the ref ends, so a branch or tag named <ref>/<segment>
        # could take over a link that looks pinned.
        nested = sorted(
            name for name in refs
            if name.startswith((f"refs/heads/{sample.ref}/", f"refs/tags/{sample.ref}/")) and not name.endswith("^{}")
        )
        if first and nested:
            errors.append(
                f"{label}: refs nested under the release tag name make links ambiguous; delete them: " + ", ".join(nested)
            )
    return errors


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


def _parsable(target: str) -> bool:
    """False when urllib cannot parse the target, for example an unclosed "[" in the authority or a non-numeric
    port."""
    try:
        parsed = urlparse(target.removeprefix("<").removesuffix(">").replace("\\", "/"))
        parsed.hostname, parsed.port
    except ValueError:
        return False
    return True


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


def validate_repository(repo_root: Path | str, *, remote_refs: RemoteRefs | None = None) -> ValidationResult:
    """remote_refs, when given, also checks each external sample's release tag against its repository."""
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
    if remote_refs is not None:
        errors.extend(_release_errors((s for topic in catalog.topics.values() for s in topic.samples), remote_refs))
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
            if not _parsable(link.target):
                errors.append(f"{relative}: link target is not a valid URL: {link.target}")
                continue
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
    result = validate_repository(args.repo_root, remote_refs=_ls_remote)
    if result.errors:
        print("\n".join(result.errors))
        return 1
    print(f"Validated links for {result.document_count} public documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
