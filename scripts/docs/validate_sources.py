"""Validate Microsoft Learn and upstream official-source evidence."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.docs.content import (
    DocumentFormatError,
    ValidationResult,
    iter_public_documents,
    load_taxonomy,
    validate_source_metadata,
)


def validate_repository(repo_root: Path | str, today: date | None = None) -> ValidationResult:
    root = Path(repo_root)
    docs_dir = root / "docs"
    taxonomy = load_taxonomy(root / "docs-taxonomy.yml")
    errors: list[str] = []
    count = 0
    try:
        documents = list(iter_public_documents(docs_dir, taxonomy))
    except DocumentFormatError as error:
        return ValidationResult(0, [str(error)])
    for document in documents:
        count += 1
        relative = document.path.relative_to(root).as_posix()
        errors.extend(
            f"{relative}: {message}"
            for message in validate_source_metadata(document.metadata, taxonomy, today=today)
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
    print(f"Validated official sources for {result.document_count} public documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
