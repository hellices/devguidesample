"""Validate public-document paths and front matter."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys
from typing import Iterable, Mapping, Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.docs.content import (
    DocumentFormatError,
    ValidationResult,
    load_document,
    load_taxonomy,
    validate_document,
)


def _candidate_paths(docs_dir: Path, taxonomy: Mapping[str, Any]) -> Iterable[Path]:
    paths = {
        config["path"]
        for config in taxonomy.get("collections", {}).values()
        if isinstance(config, Mapping) and isinstance(config.get("path"), str)
    }
    for collection in sorted(paths):
        root = docs_dir / collection
        if root.is_dir():
            yield from sorted(root.rglob("index.md"))


def validate_repository(repo_root: Path | str, today: date | None = None) -> ValidationResult:
    root = Path(repo_root)
    docs_dir = root / "docs"
    taxonomy = load_taxonomy(root / "docs-taxonomy.yml")
    errors: list[str] = []
    count = 0
    for path in _candidate_paths(docs_dir, taxonomy):
        relative = path.relative_to(root).as_posix()
        count += 1
        try:
            document = load_document(path, docs_dir=docs_dir)
        except DocumentFormatError as error:
            errors.append(str(error))
            continue
        errors.extend(
            f"{relative}: {message}"
            for message in validate_document(document, taxonomy, today=today)
        )
    return ValidationResult(count, errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    result = validate_repository(args.repo_root)
    if result.errors:
        print("\n".join(result.errors))
        return 1
    print(f"Validated metadata for {result.document_count} public documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
