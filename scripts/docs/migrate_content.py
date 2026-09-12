"""Migrate legacy Markdown and executable trees into the public docs layout."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any, Mapping
from urllib.parse import quote, urlparse

import yaml


LINK = re.compile(
    r"(?P<bang>!?)\[(?P<label>[^\]]*)\]\("
    r"(?P<target><[^>]+>|[^)\s]+)"
    r"(?P<title>\s+(?:\"[^\"]*\"|'[^']*'))?\)"
)
DATE_FIELDS = {
    "sources_checked_at",
    "last_verified",
    "occurred_at",
    "resolved_at",
    "published_at",
}


@dataclass(frozen=True)
class MigrationResult:
    changed_count: int
    actions: list[str]


def _safe_path(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise ValueError(f"path escapes repository root: {relative}")
    return candidate


def _body_without_front_matter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text.lstrip("\ufeff")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :]).lstrip("\n") + "\n"
    return text


def _normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(metadata)
    for field in DATE_FIELDS:
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = date.fromisoformat(value)
    return normalized


def _front_matter(metadata: Mapping[str, Any]) -> str:
    rendered = yaml.safe_dump(
        _normalize_metadata(metadata),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    return f"---\n{rendered}\n---\n\n"


def _future_sample_path(
    target: Path, sample_roots: list[tuple[Path, PurePosixPath]]
) -> PurePosixPath | None:
    resolved = target.resolve()
    for source, destination in sorted(
        sample_roots, key=lambda item: len(item[0].parts), reverse=True
    ):
        if resolved.is_relative_to(source):
            return destination / PurePosixPath(resolved.relative_to(source).as_posix())
    return None


def _github_url(repository_url: str, branch: str, path: PurePosixPath, is_dir: bool) -> str:
    kind = "tree" if is_dir else "blob"
    encoded = quote(path.as_posix(), safe="/")
    return f"{repository_url.rstrip('/')}/{kind}/{quote(branch, safe='')}/{encoded}"


def _copy_image(source: Path, page_dir: Path, apply: bool) -> str:
    images_dir = page_dir / "images"
    destination = images_dir / source.name
    if destination.exists() and destination.read_bytes() != source.read_bytes():
        destination = images_dir / f"{source.parent.name}-{source.name}"
    if apply:
        images_dir.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(source, destination)
    return f"images/{destination.name}"


def _rewrite_markdown(
    body: str,
    source_page: Path,
    destination_page: Path,
    document_map: Mapping[Path, Path],
    sample_roots: list[tuple[Path, PurePosixPath]],
    repository_root: Path,
    repository_url: str,
    branch: str,
    link_overrides: Mapping[str, str],
    apply: bool,
) -> str:
    def replace(match: re.Match[str]) -> str:
        raw_target = match.group("target")
        clean_target = raw_target.removeprefix("<").removesuffix(">")
        effective_target = link_overrides.get(clean_target, clean_target)
        parsed = urlparse(effective_target)
        if parsed.scheme or parsed.netloc or effective_target.startswith("#"):
            replacement = effective_target
        else:
            local_text = parsed.path
            resolved = (source_page.parent / local_text).resolve()
            fragment = f"#{parsed.fragment}" if parsed.fragment else ""
            mapped_document = document_map.get(resolved)
            if mapped_document is not None:
                replacement = os.path.relpath(
                    mapped_document, start=destination_page.parent
                ).replace("\\", "/") + fragment
            elif match.group("bang") and resolved.is_file():
                replacement = _copy_image(resolved, destination_page.parent, apply) + fragment
            elif resolved.exists():
                future = _future_sample_path(resolved, sample_roots)
                if future is None and resolved.is_relative_to(repository_root):
                    future = PurePosixPath(resolved.relative_to(repository_root).as_posix())
                if future is None:
                    replacement = effective_target
                else:
                    replacement = _github_url(
                        repository_url, branch, future, resolved.is_dir()
                    ) + fragment
            else:
                replacement = effective_target
        title = match.group("title") or ""
        return f"{match.group('bang')}[{match.group('label')}]({replacement}{title})"

    output: list[str] = []
    fence: str | None = None
    for line in body.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = "```" if stripped.startswith("```") else "~~~" if stripped.startswith("~~~") else None
        if marker:
            fence = None if fence == marker else marker if fence is None else fence
            output.append(line)
        elif fence is None:
            output.append(LINK.sub(replace, line))
        else:
            output.append(line)
    return "".join(output)


def migrate_repository(
    repo_root: Path | str,
    manifest_path: Path | str,
    *,
    apply: bool,
) -> MigrationResult:
    root = Path(repo_root).resolve()
    manifest_file = Path(manifest_path)
    if not manifest_file.is_absolute():
        manifest_file = root / manifest_file
    manifest = yaml.safe_load(manifest_file.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise ValueError("migration manifest must be a mapping")

    documents = manifest.get("documents", [])
    sample_entries = manifest.get("sample_roots", [])
    repository_url = str(manifest["repository_url"])
    branch = str(manifest.get("branch", "main"))
    document_map = {
        _safe_path(root, entry["source"]): _safe_path(root / "docs", entry["destination"])
        for entry in documents
    }
    sample_roots = [
        (
            _safe_path(root, entry["source"]),
            PurePosixPath(entry["destination"]),
        )
        for entry in sample_entries
    ]

    actions: list[str] = []
    migrated_sources: list[Path] = []
    for entry in documents:
        source = _safe_path(root, entry["source"])
        destination = _safe_path(root / "docs", entry["destination"])
        if destination.exists() and not source.exists():
            actions.append(f"already migrated: {entry['source']}")
            continue
        if destination.exists() and source.exists():
            raise FileExistsError(f"both source and destination exist: {source}, {destination}")
        if not source.is_file():
            raise FileNotFoundError(f"migration source does not exist: {source}")

        body = _body_without_front_matter(source.read_text(encoding="utf-8-sig"))
        rewritten = _rewrite_markdown(
            body,
            source,
            destination,
            document_map,
            sample_roots,
            root,
            repository_url,
            branch,
            entry.get("link_overrides", {}),
            apply,
        )
        content = _front_matter(entry["metadata"]) + rewritten.lstrip("\n")
        actions.append(f"migrate: {entry['source']} -> docs/{entry['destination']}")
        if apply:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8", newline="\n")
            migrated_sources.append(source)

    if apply:
        for source in migrated_sources:
            source.unlink()

    for entry in sample_entries:
        source = _safe_path(root, entry["source"])
        destination = _safe_path(root, entry["destination"])
        if destination.exists() and not source.exists():
            actions.append(f"already moved: {entry['source']}")
            continue
        if destination.exists() and source.exists():
            raise FileExistsError(f"both sample source and destination exist: {source}, {destination}")
        if not source.exists():
            raise FileNotFoundError(f"sample source does not exist: {source}")
        actions.append(f"move sample: {entry['source']} -> {entry['destination']}")
        if apply:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))

    changed = sum(
        1 for action in actions if action.startswith(("migrate:", "move sample:"))
    )
    return MigrationResult(changed, actions)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--manifest", type=Path, default=Path("scripts/docs/migration_manifest.yml")
    )
    parser.add_argument("--apply", action="store_true", help="perform the migration")
    args = parser.parse_args()
    result = migrate_repository(args.repo_root, args.manifest, apply=args.apply)
    print("\n".join(result.actions))
    mode = "changes" if args.apply else "planned changes"
    print(f"{result.changed_count} {mode}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
