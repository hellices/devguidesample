"""Detect environment-specific identifiers before public documentation is published."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {
    ".bicep",
    ".bicepparam",
    ".eml",
    ".env",
    ".excalidraw",
    ".html",
    ".java",
    ".js",
    ".json",
    ".md",
    ".mmd",
    ".ps1",
    ".py",
    ".sh",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {"dockerfile"}
TEXT_COMPOUND_SUFFIXES = (".env.example",)
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
KNOWN_ENVIRONMENT_MARKERS = (
    "rg-rubicon",
    "rg-krafton",
    "ais-aiplay",
    "saidxtest",
    "rg-hellices",
    "acrcustomvec",
    "cae-customvec",
    "icycliff",
    "db-neu-prd",
    "onnuri-search",
    "aisearchtest",
    "acrmemray",
)
ENVIRONMENT_SPECIFIC_NAME = re.compile(
    r"(?i)\b(?:"
    + "|".join(re.escape(marker) for marker in KNOWN_ENVIRONMENT_MARKERS)
    + r")(?:[-_a-z0-9]*)\b"
)
AZURE_SERVICE_HOSTNAME = re.compile(
    r"(?i)\b[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\."
    r"(?:search\.windows\.net|azurecr\.io|azurecontainerapps\.io)\b"
)
GENERIC_AZURE_SERVICE_HOSTNAMES = {"myregistry.azurecr.io"}
CHECKS = (
    (
        "Azure subscription ID",
        re.compile(
            rf"(?i)(?:/subscriptions/|\bsubscription_?id\b[^\r\n]{{0,24}}?|구독[^\r\n]{{0,24}}?)({UUID})"
        ),
    ),
    (
        "agent thread ID",
        re.compile(rf"(?i)\bagent\s+thread(?:\s+id)?\b[^\r\n]{{0,24}}?({UUID})"),
    ),
    ("environment-specific name", ENVIRONMENT_SPECIFIC_NAME),
    (
        "IP-based nip.io endpoint",
        re.compile(r"(?i)(?:[0-9]{1,3}\.){3}[0-9]{1,3}\.nip\.io"),
    ),
)


@dataclass(frozen=True)
class PublicSafetyResult:
    file_count: int
    errors: list[str]


def _is_example_azure_service_hostname(hostname: str) -> bool:
    lowered = hostname.casefold()
    return (
        lowered in GENERIC_AZURE_SERVICE_HOSTNAMES
        or any("example" in label for label in lowered.split("."))
    )


def _text_files(root: Path):
    for top_level in ("docs", "samples"):
        directory = root / top_level
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            lowered_name = path.name.casefold()
            if path.is_file() and (
                path.suffix.casefold() in TEXT_SUFFIXES
                or lowered_name in TEXT_FILENAMES
                or lowered_name.endswith(TEXT_COMPOUND_SUFFIXES)
            ):
                yield path


def validate_repository(repo_root: Path | str) -> PublicSafetyResult:
    root = Path(repo_root)
    errors: list[str] = []
    count = 0
    for path in _text_files(root):
        count += 1
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(root).as_posix()
        for line_number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in CHECKS:
                if pattern.search(line):
                    errors.append(f"{relative}:{line_number}: possible {label}")
            for match in AZURE_SERVICE_HOSTNAME.finditer(line):
                if not _is_example_azure_service_hostname(match.group(0)):
                    errors.append(
                        f"{relative}:{line_number}: possible "
                        "non-example Azure service hostname"
                    )
    return PublicSafetyResult(count, errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    result = validate_repository(args.repo_root)
    if result.errors:
        print("\n".join(result.errors))
        return 1
    print(f"Checked {result.file_count} public text files for environment-specific identifiers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
