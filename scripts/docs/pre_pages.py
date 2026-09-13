"""Fixed pre-Pages inventory, reviewed-evidence schema, and Git lineage."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess
from types import MappingProxyType
from typing import Mapping
import unicodedata

import yaml

from scripts.docs.content import Document, DocumentFormatError, load_taxonomy
from scripts.docs.topics import build_topic_catalog


class AuditFormatError(ValueError):
    """Raised when the inventory or its Git lineage cannot be validated."""


class _InventorySafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        self.flatten_mapping(node)
        keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, Hashable):
                raise yaml.constructor.ConstructorError(
                    "while constructing an inventory mapping", node.start_mark,
                    "found unhashable key", key_node.start_mark,
                )
            if key in keys:
                raise yaml.constructor.ConstructorError(
                    "while constructing an inventory mapping", node.start_mark,
                    f"duplicate mapping key: {key!r}", key_node.start_mark,
                )
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


@dataclass(frozen=True)
class StructureEvidence:
    """A normalized current structure with exact (not minimum) multiplicity."""

    path: PurePosixPath
    category: str
    fingerprint: str
    count: int
    kind: str = field(init=False, default="structure")


@dataclass(frozen=True)
class FileEvidence:
    """Exact current file bytes, including binary artifacts."""

    path: PurePosixPath
    sha256: str
    kind: str = field(init=False, default="file")


@dataclass(frozen=True)
class ReviewedChange:
    """A bounded baseline loss justified by immutable current evidence references."""

    missing_count: int
    reason: str
    evidence: tuple[StructureEvidence | FileEvidence, ...]


@dataclass(frozen=True)
class BaselineDocument:
    baseline_path: PurePosixPath
    pages_path: PurePosixPath
    reviewed_changes: Mapping[str, Mapping[str, ReviewedChange]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reviewed_changes",
            MappingProxyType({
                category: MappingProxyType(dict(approvals))
                for category, approvals in validate_reviewed_changes(self.reviewed_changes).items()
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


STRUCTURE_CATEGORIES = (
    "title", "headings", "prose", "code", "tables", "images", "local_link_labels",
)


def _positive_count(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise AuditFormatError(f"{label} must be a positive integer")
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise AuditFormatError(f"{label} must be lowercase SHA-256")
    return value


def _review_reason(value: object, label: str) -> str:
    reason = _nonempty_string(value, label)
    text = unicodedata.normalize("NFKC", reason).casefold()
    text = re.sub(r"(?:https?://|(?:docs|samples)/)\S+", " ", text)
    text = re.sub(
        r"\b(?:safety|reason|review(?:ed)?|approval|approved?|preservation|replacement|migration|updated?|revised?|"
        r"changed?|removed?|deleted?|retained?|preserved?|replaced?|migrated?|"
        r"needed|necessary|unnecessary|longer|anymore|during|before|after|because|content|document|documentation|"
        r"block|material|stuff|latest|current|previous|old|new|"
        r"a|an|the|and|or|as|at|in|on|to|of|for|from|with|by|"
        r"this|that|these|those|it|its|is|was|are|were|be|been|not|no|now)\b",
        " ", text,
    )
    text = re.sub(
        r"\b(?:안전|검토|사유|이유|보존|대체|이관|갱신|업데이트|수정|변경|삭제|제거|"
        r"유지|불필요|필요|내용|문서|콘텐츠|최신|현재|해당|않|없|기존|이전|"
        r"과정|일반적|쓰이지|부분|항목|정리|적절|대한|거쳐)[가-힣]*"
        r"|\b(?:이|그|더|이상|위해|때문에)\b",
        " ", text,
    )
    concrete = re.findall(r"[a-z가-힣][a-z0-9가-힣_.-]*", text)
    if len(reason.strip()) < 40 or len(concrete) < 2 or sum(map(len, concrete)) < 12:
        raise AuditFormatError(
            f"{label} must describe concrete replacement/preservation details, not generic-only approval phrases"
        )
    return reason


def _evidence_reference(value: object, label: str) -> StructureEvidence | FileEvidence:
    if isinstance(value, (StructureEvidence, FileEvidence)):
        value = {**asdict(value), "path": str(value.path)}
    if not isinstance(value, dict):
        raise AuditFormatError(f"{label} must be a mapping")
    kind = value.get("kind")
    if kind not in ("structure", "file"):
        raise AuditFormatError(f"{label}.kind must be structure or file")
    fields = {"kind", "path", "category", "fingerprint", "count"} if kind == "structure" else {
        "kind", "path", "sha256",
    }
    raw = _fields(value, fields, label)
    path = _relative_path(raw["path"], f"{label}.path")
    if kind == "file":
        return FileEvidence(path, _sha256(raw["sha256"], f"{label}.sha256"))
    category = raw["category"]
    if category not in STRUCTURE_CATEGORIES:
        raise AuditFormatError(f"{label}.category is not a known structure category")
    return StructureEvidence(
        path, category, _sha256(raw["fingerprint"], f"{label}.fingerprint"),
        _positive_count(raw["count"], f"{label}.count"),
    )


def validate_reviewed_changes(
    value: object, label: str = "reviewed_changes",
) -> Mapping[str, Mapping[str, ReviewedChange]]:
    """Parse immutable approvals; current file/structure evidence is checked by the content auditor."""
    if not isinstance(value, Mapping):
        raise AuditFormatError(f"{label} must be a mapping")
    parsed = {}
    for category, approvals in value.items():
        if category not in STRUCTURE_CATEGORIES:
            raise AuditFormatError(f"{label}: unknown structure category: {category!r}")
        if not isinstance(approvals, Mapping):
            raise AuditFormatError(f"{label}.{category} must be a mapping")
        parsed[category] = {}
        for fingerprint, approval in approvals.items():
            _sha256(fingerprint, f"{label}.{category}.fingerprint")
            entry_label = f"{label}.{category}.{fingerprint}.approval"
            if isinstance(approval, ReviewedChange):
                approval = {
                    "missing_count": approval.missing_count,
                    "reason": approval.reason,
                    "evidence": approval.evidence,
                }
            raw = _fields(approval, {"missing_count", "reason", "evidence"}, entry_label)
            count = _positive_count(raw["missing_count"], f"{entry_label}.missing_count")
            reason = _review_reason(raw["reason"], f"{entry_label}.reason")
            if not isinstance(raw["evidence"], (list, tuple)) or not raw["evidence"]:
                raise AuditFormatError(f"{entry_label}.evidence must be a non-empty sequence")
            references = []
            seen = set()
            for index, reference in enumerate(raw["evidence"]):
                reference = _evidence_reference(reference, f"{entry_label}.evidence[{index}]")
                key = (reference.kind, reference.path)
                if isinstance(reference, StructureEvidence):
                    key += (reference.category, reference.fingerprint)
                if key in seen:
                    raise AuditFormatError(f"{entry_label}: duplicate evidence reference: {reference.path}")
                seen.add(key)
                references.append(reference)
            parsed[category][fingerprint] = ReviewedChange(count, reason, tuple(references))
    return parsed


def load_inventory(path: Path) -> PrePagesInventory:
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_InventorySafeLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise AuditFormatError(f"{path}: cannot read inventory: {error}") from error
    data = _fields(
        data,
        {"version", "baseline_commit", "pages_commit", "rename_similarity", "documents", "dispositions"},
        str(path),
    )
    if type(data["version"]) is not int or data["version"] != 2:
        raise AuditFormatError("version must be 2 (evidence-bound content approvals)")
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
            reviewed_changes=validate_reviewed_changes(
                raw.get("reviewed_changes", {}), f"{label}.reviewed_changes",
            ),
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
        seen_paths = set()
        for current_path in paths:
            if current_path in seen_paths:
                raise AuditFormatError(f"{label}: duplicate current_paths entry: {current_path}")
            seen_paths.add(current_path)
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
    _require_full_history(repo_root, commit)
    if _git(repo_root, "cat-file", "-t", commit).strip() != b"commit":
        raise AuditFormatError(f"{commit}: expected a Git commit object")


def _require_full_history(repo_root: Path, *commits: str) -> None:
    if _git(repo_root, "rev-parse", "--is-shallow-repository").strip() == b"true":
        raise AuditFormatError(
            f"Shallow Git repository cannot audit required commits: {', '.join(commits)}. "
            "Fetch full history before auditing (git fetch --unshallow; checkout fetch-depth: 0)."
        )


def git_bytes(repo_root: Path, commit: str, path: PurePosixPath) -> bytes:
    _require_commit(repo_root, commit)
    path = _relative_path(path.as_posix(), "Git path")
    return _git(repo_root, "cat-file", "blob", f"{commit}:{path.as_posix()}")


def git_text(repo_root: Path, commit: str, path: PurePosixPath) -> str:
    return git_bytes(repo_root, commit, path).decode("utf-8")


def baseline_paths(repo_root: Path, inventory: PrePagesInventory) -> tuple[PurePosixPath, ...]:
    _require_full_history(repo_root, inventory.baseline_commit, inventory.pages_commit)
    _require_commit(repo_root, inventory.baseline_commit)
    output = _git(repo_root, "ls-tree", "-r", "--name-only", "-z", inventory.baseline_commit)
    return tuple(PurePosixPath(path) for path in output.decode("utf-8").split("\0") if path)


def resolve_current_documents(
    repo_root: Path, inventory: PrePagesInventory
) -> Mapping[PurePosixPath, Document]:
    _require_full_history(repo_root, inventory.baseline_commit, inventory.pages_commit)
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
