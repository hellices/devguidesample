"""Validate local Markdown links, image targets, and image alt text."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.docs.content import ValidationResult, load_taxonomy


LINK = re.compile(r"(!?)\[([^\]]*)\]\((<[^>]+>|[^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")


def _candidate_paths(docs_dir: Path, taxonomy: Mapping[str, Any]) -> Iterable[Path]:
    for config in taxonomy.get("collections", {}).values():
        collection = docs_dir / config["path"]
        if collection.is_dir():
            yield from sorted(collection.rglob("index.md"))


def _without_fenced_code(text: str) -> str:
    output: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = "```" if stripped.startswith("```") else "~~~" if stripped.startswith("~~~") else None
        if marker:
            fence = None if fence == marker else marker if fence is None else fence
            output.append("\n")
        elif fence is None:
            output.append(line)
        else:
            output.append("\n")
    return "".join(output)


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
    errors: list[str] = []
    count = 0
    for page in _candidate_paths(docs_dir, taxonomy):
        count += 1
        relative = page.relative_to(root).as_posix()
        text = _without_fenced_code(page.read_text(encoding="utf-8-sig"))
        for match in LINK.finditer(text):
            is_image = bool(match.group(1))
            label = match.group(2).strip()
            raw_target = match.group(3)
            line = text.count("\n", 0, match.start()) + 1
            if is_image and not label:
                errors.append(f"{relative}:{line}: image alt text is required")
            target = _resolve_target(page, docs_dir, raw_target)
            if target is not None and not target.exists():
                errors.append(f"{relative}:{line}: target does not exist: {raw_target}")
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
