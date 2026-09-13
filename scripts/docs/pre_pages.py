"""Fixed pre-Pages inventory and Git lineage (not a content-preservation audit)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess
from types import MappingProxyType
from typing import Mapping

import yaml

from scripts.docs.content import Document, DocumentFormatError, load_taxonomy
from scripts.docs.topics import build_topic_catalog


class AuditFormatError(ValueError):
    """Raised when the inventory or its Git lineage cannot be validated."""


@dataclass(frozen=True)
class BaselineDocument:
    baseline_path: PurePosixPath
    pages_path: PurePosixPath
    reviewed_changes: Mapping[str, Mapping[str, str]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reviewed_changes",
            MappingProxyType({
                category: MappingProxyType(dict(reasons))
                for category, reasons in self.reviewed_changes.items()
            }),
        )


@dataclass(frozen=True)
class ReviewedDisposition:
    status: str
    current_paths: tuple[PurePosixPath, ...]
    reason: str


@dataclass(frozen=True)
class PrePagesInventory:
    baseline_commit: str
    pages_commit: str
    rename_similarity: int
    documents: tuple[BaselineDocument, ...]
    dispositions: Mapping[PurePosixPath, ReviewedDisposition]

    def __post_init__(self) -> None:
        object.__setattr__(self, "dispositions", MappingProxyType(dict(self.dispositions)))


@dataclass(frozen=True)
class GitFileDisposition:
    baseline_path: PurePosixPath
    status: str
    current_paths: tuple[PurePosixPath, ...]


def _fields(value: object, required: set[str], label: str, optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise AuditFormatError(f"{label} must be a mapping")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        raise AuditFormatError(
            f"{label}: missing fields {sorted(missing)}; unexpected fields {sorted(extra, key=str)}"
        )
    return value


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuditFormatError(f"{label} must be a non-empty string")
    return value


def _commit_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise AuditFormatError(f"{label} must be a full lowercase 40-character commit hash: {value!r}")
    return value


def _relative_path(value: object, label: str) -> PurePosixPath:
    raw = _nonempty_string(value, label)
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or PureWindowsPath(raw).drive
        or "\\" in raw
        or "\0" in raw
        or ".." in path.parts
        or raw != path.as_posix()
        or not path.parts
    ):
        raise AuditFormatError(f"{label} must be a normalized repository-relative POSIX path: {raw!r}")
    return path


def _reviewed_changes(value: object, label: str) -> Mapping[str, Mapping[str, str]]:
    if not isinstance(value, dict):
        raise AuditFormatError(f"{label} must be a mapping")
    for category, reasons in value.items():
        _nonempty_string(category, label)
        if not isinstance(reasons, dict):
            raise AuditFormatError(f"{label}.{category} must be a mapping")
        for fingerprint, reason in reasons.items():
            _nonempty_string(fingerprint, label)
            _nonempty_string(reason, label)
    return value


def load_inventory(path: Path) -> PrePagesInventory:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise AuditFormatError(f"{path}: cannot read inventory: {error}") from error
    data = _fields(
        data,
        {"version", "baseline_commit", "pages_commit", "rename_similarity", "documents", "dispositions"},
        str(path),
    )
    if type(data["version"]) is not int or data["version"] != 1:
        raise AuditFormatError("version must be 1")
    baseline = _commit_hash(data["baseline_commit"], "baseline_commit")
    pages = _commit_hash(data["pages_commit"], "pages_commit")
    similarity = data["rename_similarity"]
    if type(similarity) is not int or not 1 <= similarity <= 100:
        raise AuditFormatError("rename_similarity must be an integer between 1 and 100")
    if not isinstance(data["documents"], list):
        raise AuditFormatError("documents must be a list")

    documents: list[BaselineDocument] = []
    seen: dict[str, set[PurePosixPath]] = {"baseline_path": set(), "pages_path": set()}
    for index, raw in enumerate(data["documents"]):
        label = f"documents[{index}]"
        raw = _fields(raw, {"baseline_path", "pages_path"}, label, {"reviewed_changes"})
        paths = {}
        for field in seen:
            value = _relative_path(raw[field], f"{label}.{field}")
            if value in seen[field]:
                raise AuditFormatError(f"{label}: duplicate {field}: {value}")
            seen[field].add(value)
            paths[field] = value
        documents.append(BaselineDocument(
            **paths,
            reviewed_changes=_reviewed_changes(raw.get("reviewed_changes", {}), f"{label}.reviewed_changes"),
        ))

    if not isinstance(data["dispositions"], dict):
        raise AuditFormatError("dispositions must be a mapping")
    dispositions = {}
    for raw_path, raw in data["dispositions"].items():
        baseline_path = _relative_path(raw_path, "dispositions path")
        label = f"dispositions.{raw_path}"
        raw = _fields(raw, {"status", "current_paths", "reason"}, label)
        status = raw["status"]
        if not isinstance(status, str) or status not in {
            "excluded-local-state", "replaced-summary", "replaced-test",
        }:
            raise AuditFormatError(f"{label}.status is not a reviewed disposition status")
        reason = _nonempty_string(raw["reason"], f"{label}.reason")
        current = raw["current_paths"]
        if not isinstance(current, list):
            raise AuditFormatError(f"{label}.current_paths must be a list")
        if (status == "excluded-local-state") != (not current):
            raise AuditFormatError(
                f"{label}.current_paths must be empty only for excluded-local-state"
            )
        paths = tuple(_relative_path(item, f"{label}.current_paths") for item in current)
        dispositions[baseline_path] = ReviewedDisposition(status, paths, reason)
    return PrePagesInventory(baseline, pages, similarity, tuple(documents), dispositions)


def _git(repo_root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise AuditFormatError(
            f"Git {' '.join(arguments)} failed: {detail}. "
            "Ensure the exact commit is available with full history (fetch-depth: 0)."
        )
    return result.stdout


def _require_commit(repo_root: Path, commit: str) -> None:
    _commit_hash(commit, "commit")
    if _git(repo_root, "cat-file", "-t", commit).strip() != b"commit":
        raise AuditFormatError(f"{commit}: expected a Git commit object")


def git_bytes(repo_root: Path, commit: str, path: PurePosixPath) -> bytes:
    _require_commit(repo_root, commit)
    path = _relative_path(path.as_posix(), "Git path")
    return _git(repo_root, "cat-file", "blob", f"{commit}:{path.as_posix()}")


def git_text(repo_root: Path, commit: str, path: PurePosixPath) -> str:
    return git_bytes(repo_root, commit, path).decode("utf-8")


def baseline_paths(repo_root: Path, inventory: PrePagesInventory) -> tuple[PurePosixPath, ...]:
    _require_commit(repo_root, inventory.baseline_commit)
    output = _git(repo_root, "ls-tree", "-r", "--name-only", "-z", inventory.baseline_commit)
    return tuple(PurePosixPath(path) for path in output.decode("utf-8").split("\0") if path)


def resolve_current_documents(
    repo_root: Path, inventory: PrePagesInventory
) -> Mapping[PurePosixPath, Document]:
    if len(inventory.documents) != 62:
        raise AuditFormatError(f"Expected 62 inventory documents, found {len(inventory.documents)}")
    try:
        taxonomy = load_taxonomy(repo_root / "docs-taxonomy.yml")
        catalog = build_topic_catalog(repo_root / "docs", taxonomy)
    except (DocumentFormatError, OSError, yaml.YAMLError) as error:
        raise AuditFormatError(f"Cannot resolve current documents: {error}") from error
    if len(catalog.documents) != 62:
        raise AuditFormatError(
            f"Expected 62 current public documents, found {len(catalog.documents)}"
        )
    by_path = {document.relative_path: document for document in catalog.documents}
    resolved: dict[PurePosixPath, Document] = {}
    used: set[PurePosixPath] = set()
    for document in inventory.documents:
        git_bytes(repo_root, inventory.baseline_commit, document.baseline_path)
        git_bytes(repo_root, inventory.pages_commit, PurePosixPath("docs") / document.pages_path)
        canonical = catalog.redirects.get(document.pages_path)
        if canonical is None:
            raise AuditFormatError(f"{document.pages_path}: missing initial Pages redirect_from")
        if canonical in used:
            raise AuditFormatError(f"{canonical}: current public document used more than once")
        if document.baseline_path in resolved:
            raise AuditFormatError(f"duplicate baseline_path: {document.baseline_path}")
        resolved[document.baseline_path] = by_path[canonical]
        used.add(canonical)
    if used != set(by_path):
        raise AuditFormatError("Every current public document must be used once")
    return MappingProxyType(resolved)


def classify_baseline_files(
    repo_root: Path, inventory: PrePagesInventory
) -> tuple[GitFileDisposition, ...]:
    paths = baseline_paths(repo_root, inventory)
    classified = {
        path: GitFileDisposition(path, "unchanged", (path,))
        for path in paths
    }
    output = _git(
        repo_root, "diff", f"--find-renames={inventory.rename_similarity}%",
        "--name-status", "-z", inventory.baseline_commit, "HEAD", "--",
    )
    fields = iter(output.decode("utf-8").split("\0")[:-1])
    deleted = set()
    for status in fields:
        try:
            source = PurePosixPath(next(fields))
            target = PurePosixPath(next(fields)) if status.startswith("R") else source
        except StopIteration as error:
            raise AuditFormatError("Truncated Git name-status output") from error
        if status == "A":
            continue
        if source not in classified:
            raise AuditFormatError(f"Git diff path is not in baseline: {source}")
        if status == "D":
            deleted.add(source)
        elif status in {"M", "T"}:
            classified[source] = GitFileDisposition(source, "modified", (source,))
        elif status.startswith("R"):
            classified[source] = GitFileDisposition(source, "renamed", (target,))
        else:
            raise AuditFormatError(f"{source}: unsupported Git status {status}")

    for path, disposition in inventory.dispositions.items():
        if path not in classified:
            raise AuditFormatError(f"Reviewed disposition is not in baseline: {path}")
        for current in disposition.current_paths:
            if not (repo_root / current).is_file():
                raise AuditFormatError(f"{path}: reviewed current path does not exist: {current}")
        classified[path] = GitFileDisposition(path, "reviewed", disposition.current_paths)
    unreviewed = deleted - inventory.dispositions.keys()
    if unreviewed:
        raise AuditFormatError(
            "unreviewed deleted baseline paths: " + ", ".join(str(path) for path in sorted(unreviewed))
        )
    return tuple(classified[path] for path in paths)
