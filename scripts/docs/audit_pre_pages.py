"""Audit preservation and visibility of the fixed pre-Pages public corpus."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import json
from pathlib import Path, PurePath
import sys
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.docs.pre_pages import PreservationAuditResult, audit_repository


def _json_value(value: object) -> object:
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, PurePath):
        return value.as_posix()
    return value


def write_audit_json(path: Path, result: PreservationAuditResult) -> None:
    """Replace a report only after the entire new JSON document has been written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with sibling.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(_json_value(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        sibling.replace(path)
    finally:
        sibling.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--site-dir", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--content-only", action="store_true")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    site = args.site_dir if args.site_dir is not None else Path("site")
    inventory = args.inventory if args.inventory is not None else Path("scripts/docs/pre_pages_inventory.yml")
    result = audit_repository(
        root, root / site, root / inventory, content_only=args.content_only,
    )
    if args.json_output:
        try:
            write_audit_json(args.json_output, result)
        except (OSError, ValueError) as error:
            print(f"{args.json_output}: cannot write audit JSON: {error}")
            return 1
    for warning in result.warnings:
        print(f"Warning: {warning}")
    if result.errors:
        for error in result.errors:
            print(error.replace("\r", "\\r").replace("\n", "\\n"))
        return 1
    summary = (
        f"Audited {result.baseline_file_count} baseline files and "
        f"{result.baseline_markdown_count} Markdown files: "
        f"{result.preserved_documents}/{result.document_count} public documents "
    )
    print(summary + (
        "mapped and preserved (content-only; built site not inspected)."
        if args.content_only else
        "mapped, preserved, redirected, searchable, and visible."
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
