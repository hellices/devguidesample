"""Validate that the built Pages search index covers pages, body text, and tags."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.docs.content import iter_public_documents, load_taxonomy


KOREAN_WORD = re.compile(r"[가-힣]{2,}")
ENGLISH_PRODUCT_PHRASE = re.compile(
    r"\b[A-Z][A-Za-z0-9.+/-]*(?:\s+[A-Z][A-Za-z0-9.+/-]*)+\b"
)


@dataclass(frozen=True)
class SearchIndexResult:
    document_count: int
    tag_count: int
    errors: list[str]


def _page_location(relative_path) -> str:
    parent = relative_path.parent.as_posix()
    return "" if parent in {"", "."} else parent.rstrip("/") + "/"


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _representative_match(pattern: re.Pattern[str], body: str, title: str) -> str | None:
    for match in pattern.finditer(body):
        candidate = _normalized(match.group(0))
        if candidate and candidate not in title:
            return candidate
    return None


def validate_repository(repo_root: Path | str) -> SearchIndexResult:
    root = Path(repo_root)
    taxonomy = load_taxonomy(root / "docs-taxonomy.yml")
    documents = list(iter_public_documents(root / "docs", taxonomy))
    index_path = root / "site" / "search" / "search_index.json"
    if not index_path.is_file():
        return SearchIndexResult(
            len(documents),
            0,
            [f"{index_path.relative_to(root).as_posix()}: search index is missing"],
        )

    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return SearchIndexResult(len(documents), 0, [f"{index_path}: invalid JSON: {error}"])
    entries = data.get("docs", []) if isinstance(data, dict) else []
    if not isinstance(entries, list):
        return SearchIndexResult(len(documents), 0, [f"{index_path}: docs must be a list"])

    errors: list[str] = []
    used_tags: set[str] = set()
    for document in documents:
        title = str(document.metadata.get("title", ""))
        location = _page_location(document.relative_path)
        page_entries = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and (
                entry.get("location") == location
                or str(entry.get("location", "")).startswith(location + "#")
            )
        ]
        relative = document.path.relative_to(root).as_posix()
        if not page_entries:
            errors.append(f"{relative}: page is missing from the search index")
            page_text = ""
        else:
            page_text = _normalized(
                " ".join(
                    f"{entry.get('title', '')} {entry.get('text', '')}" for entry in page_entries
                )
            )

        korean = _representative_match(KOREAN_WORD, document.body, title)
        if korean and korean not in page_text:
            errors.append(f"{relative}: Korean body text is missing from the search index")
        english = _representative_match(ENGLISH_PRODUCT_PHRASE, document.body, title)
        if english and english not in page_text:
            errors.append(
                f"{relative}: English product phrase is missing from the search index: {english}"
            )
        tags = document.metadata.get("tags", [])
        if isinstance(tags, list):
            used_tags.update(str(tag) for tag in tags)

    locations = {
        str(entry.get("location", "")) for entry in entries if isinstance(entry, dict)
    }
    for tag in sorted(used_tags):
        if f"tags/#tag:{tag}" not in locations:
            errors.append(f"search index tag is missing: {tag}")

    return SearchIndexResult(len(documents), len(used_tags), errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    result = validate_repository(args.repo_root)
    if result.errors:
        print("\n".join(result.errors))
        return 1
    print(
        f"Validated search coverage for {result.document_count} public documents "
        f"and {result.tag_count} tags."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
