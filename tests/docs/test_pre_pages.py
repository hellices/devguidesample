from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError, replace
from pathlib import Path, PurePosixPath
import re
import subprocess

import pytest
import yaml

from scripts.docs import pre_pages
from scripts.docs.pre_pages import (
    AuditFormatError,
    BaselineDocument,
    GitFileDisposition,
    PrePagesInventory,
    ReviewedDisposition,
    git_bytes,
    git_text,
    load_inventory,
)


ROOT = Path(__file__).parents[2]
BASELINE = "a4e680116db1016a698e64baae9efde858a8eafa"
PAGES = "9ace966742ff92a00fc84bcc21529af47b8661af"
MANIFEST = ROOT / "scripts/docs/pre_pages_inventory.yml"


def git(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
    ).stdout


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "--all")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD").decode().strip()


@pytest.fixture
def history(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Inventory Tests")
    git(repo, "config", "user.email", "inventory@example.com")
    (repo / "한글 문서.md").write_bytes("첫 문장\r\n둘째 문장\n".encode())
    (repo / "binary.bin").write_bytes(b"\x00\xff\r\n\x80")
    (repo / "-literal ; $(touch injected)\tfile.md").write_text("literal\n")
    baseline = commit(repo, "Baseline")
    (repo / "added.md").write_text("New file\n")
    pages = commit(repo, "Pages")
    return repo, baseline, pages


@pytest.fixture
def manifest_data() -> dict:
    return {
        "version": 1,
        "baseline_commit": BASELINE,
        "pages_commit": PAGES,
        "rename_similarity": 20,
        "documents": [
            {
                "baseline_path": "old/guide.md",
                "pages_path": "guides/service/topic/index.md",
                "reviewed_changes": {"prose": {"fingerprint": "Preserved in sample README."}},
            }
        ],
        "dispositions": {
            ".azure/state.json": {
                "status": "excluded-local-state",
                "current_paths": [],
                "reason": "Local state is intentionally not public.",
            },
            "old/README.md": {
                "status": "replaced-summary",
                "current_paths": ["docs/services/service/topic/index.md"],
                "reason": "Replaced by the canonical topic overview.",
            },
            "old/test.py": {
                "status": "replaced-test",
                "current_paths": ["tests/docs/test_topics.py"],
                "reason": "Replaced by topic contract assertions.",
            },
        },
    }


def load_data(tmp_path: Path, data: object) -> PrePagesInventory:
    path = tmp_path / "inventory.yml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return load_inventory(path)


def test_inventory_loads_deeply_immutable_models(tmp_path: Path, manifest_data: dict) -> None:
    inventory = load_data(tmp_path, manifest_data)
    assert isinstance(inventory, PrePagesInventory)
    assert inventory.baseline_commit == BASELINE
    assert inventory.pages_commit == PAGES
    assert inventory.rename_similarity == 20
    document = inventory.documents[0]
    assert isinstance(document, BaselineDocument)
    assert document.baseline_path == PurePosixPath("old/guide.md")
    assert document.pages_path == PurePosixPath("guides/service/topic/index.md")
    disposition = inventory.dispositions[PurePosixPath("old/README.md")]
    assert isinstance(disposition, ReviewedDisposition)
    assert disposition.current_paths == (PurePosixPath("docs/services/service/topic/index.md"),)
    file = GitFileDisposition(document.baseline_path, "unchanged", (document.baseline_path,))
    for model, field, value in (
        (inventory, "rename_similarity", 100),
        (document, "baseline_path", PurePosixPath("other.md")),
        (disposition, "reason", "changed"),
        (file, "status", "modified"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(model, field, value)
    with pytest.raises(TypeError):
        inventory.dispositions[PurePosixPath("other.md")] = disposition
    with pytest.raises(TypeError):
        document.reviewed_changes["prose"]["fingerprint"] = "changed"
    with pytest.raises(TypeError):
        document.reviewed_changes["headings"] = {}


@pytest.mark.parametrize("field", ["baseline_commit", "pages_commit"])
@pytest.mark.parametrize("value", [None, "", "a4e6801", "A" * 40, "g" * 40, "a" * 39, 123])
def test_inventory_requires_full_lowercase_commit_hashes(
    tmp_path: Path, manifest_data: dict, field: str, value: object
) -> None:
    manifest_data[field] = value
    with pytest.raises(AuditFormatError, match=field):
        load_data(tmp_path, manifest_data)


@pytest.mark.parametrize(
    "field",
    ["version", "baseline_commit", "pages_commit", "rename_similarity", "documents", "dispositions"],
)
def test_inventory_requires_all_top_level_fields(
    tmp_path: Path, manifest_data: dict, field: str
) -> None:
    del manifest_data[field]
    with pytest.raises(AuditFormatError, match=field):
        load_data(tmp_path, manifest_data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("extra", True), ("version", 2), ("version", True),
        ("rename_similarity", 0), ("rename_similarity", 101),
        ("rename_similarity", "20"), ("rename_similarity", True),
        ("documents", {}), ("dispositions", []),
    ],
)
def test_inventory_rejects_invalid_schema(
    tmp_path: Path, manifest_data: dict, field: str, value: object
) -> None:
    manifest_data[field] = value
    with pytest.raises(AuditFormatError, match=field):
        load_data(tmp_path, manifest_data)


@pytest.mark.parametrize("field", ["baseline_path", "pages_path"])
def test_inventory_rejects_duplicate_document_paths(
    tmp_path: Path, manifest_data: dict, field: str
) -> None:
    duplicate = {
        "baseline_path": "another.md",
        "pages_path": "guides/service/another/index.md",
    }
    duplicate[field] = manifest_data["documents"][0][field]
    manifest_data["documents"].append(duplicate)
    with pytest.raises(AuditFormatError, match=f"duplicate {field}"):
        load_data(tmp_path, manifest_data)


@pytest.mark.parametrize("value", ["", "/root.md", "../secret.md", "a/../b.md", "a\\b.md", "C:/a.md", "a\0b.md"])
@pytest.mark.parametrize("field", ["baseline_path", "pages_path"])
def test_inventory_rejects_unsafe_paths(
    tmp_path: Path, manifest_data: dict, field: str, value: str
) -> None:
    manifest_data["documents"][0][field] = value
    with pytest.raises(AuditFormatError, match=field):
        load_data(tmp_path, manifest_data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "deleted"), ("status", None), ("reason", ""),
        ("reason", None), ("current_paths", []), ("current_paths", "target.md"),
        ("current_paths", ["/outside.md"]),
    ],
)
def test_inventory_rejects_invalid_reviewed_dispositions(
    tmp_path: Path, manifest_data: dict, field: str, value: object
) -> None:
    manifest_data["dispositions"]["old/README.md"][field] = value
    with pytest.raises(AuditFormatError, match=field):
        load_data(tmp_path, manifest_data)


@pytest.mark.parametrize("field", ["status", "current_paths", "reason"])
def test_inventory_requires_disposition_fields(
    tmp_path: Path, manifest_data: dict, field: str
) -> None:
    del manifest_data["dispositions"]["old/README.md"][field]
    with pytest.raises(AuditFormatError, match=field):
        load_data(tmp_path, manifest_data)


def test_excluded_local_state_cannot_have_replacements(tmp_path: Path, manifest_data: dict) -> None:
    manifest_data["dispositions"][".azure/state.json"]["current_paths"] = ["public.md"]
    with pytest.raises(AuditFormatError, match="current_paths"):
        load_data(tmp_path, manifest_data)


@pytest.mark.parametrize("value", [[], {"prose": []}, {"prose": {"fingerprint": ""}}])
def test_reviewed_changes_require_nested_reason_mappings(
    tmp_path: Path, manifest_data: dict, value: object
) -> None:
    manifest_data["documents"][0]["reviewed_changes"] = value
    with pytest.raises(AuditFormatError, match="reviewed_changes"):
        load_data(tmp_path, manifest_data)


def test_reviewed_changes_default_to_empty(tmp_path: Path, manifest_data: dict) -> None:
    del manifest_data["documents"][0]["reviewed_changes"]
    assert load_data(tmp_path, manifest_data).documents[0].reviewed_changes == {}


@pytest.mark.parametrize("text", ["[]", "version: [", "!!python/object/apply:os.system ['false']"])
def test_inventory_reports_invalid_or_unsafe_yaml(tmp_path: Path, text: str) -> None:
    path = tmp_path / "invalid.yml"
    path.write_text(text)
    with pytest.raises(AuditFormatError):
        load_inventory(path)


def test_git_readers_preserve_text_and_binary(history: tuple[Path, str, str]) -> None:
    repo, baseline, _ = history
    assert git_text(repo, baseline, PurePosixPath("한글 문서.md")) == "첫 문장\r\n둘째 문장\n"
    assert git_bytes(repo, baseline, PurePosixPath("binary.bin")) == b"\x00\xff\r\n\x80"


def test_git_reader_treats_shell_metacharacters_literally(
    history: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, baseline, _ = history
    run = subprocess.run
    calls = []

    def checked_run(arguments, **kwargs):
        assert isinstance(arguments, list)
        assert kwargs.get("shell", False) is False
        calls.append(arguments)
        return run(arguments, **kwargs)

    monkeypatch.setattr(subprocess, "run", checked_run)
    path = PurePosixPath("-literal ; $(touch injected)\tfile.md")
    assert git_text(repo, baseline, path) == "literal\n"
    assert any(f"{baseline}:{path.as_posix()}" in arguments for arguments in calls)
    assert not (repo / "injected").exists()


@pytest.mark.parametrize("reader", [git_text, git_bytes])
def test_missing_commit_error_includes_exact_hash(
    history: tuple[Path, str, str], reader
) -> None:
    repo, _, _ = history
    missing = "0" * 40
    with pytest.raises(AuditFormatError, match=missing):
        reader(repo, missing, PurePosixPath("binary.bin"))


def test_shallow_history_error_names_missing_commit(
    history: tuple[Path, str, str], tmp_path: Path
) -> None:
    repo, baseline, _ = history
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth=1", repo.as_uri(), str(shallow))
    with pytest.raises(AuditFormatError, match=baseline) as error:
        git_bytes(shallow, baseline, PurePosixPath("binary.bin"))
    assert "history" in str(error.value).lower()


def test_missing_blob_error_names_commit_and_path(history: tuple[Path, str, str]) -> None:
    repo, baseline, _ = history
    with pytest.raises(AuditFormatError, match=baseline) as error:
        git_bytes(repo, baseline, PurePosixPath("missing.md"))
    assert "missing.md" in str(error.value)


@pytest.mark.parametrize("object_kind", ["tag", "tree", "blob"])
def test_git_readers_require_commit_objects_not_other_full_hashes(
    history: tuple[Path, str, str], object_kind: str
) -> None:
    repo, baseline, _ = history
    if object_kind == "tag":
        git(repo, "-c", "tag.gpgsign=false", "tag", "-a", "snapshot", "-m", "Snapshot", baseline)
        object_hash = git(repo, "rev-parse", "snapshot").decode().strip()
    else:
        revision = f"{baseline}^{{tree}}" if object_kind == "tree" else f"{baseline}:binary.bin"
        object_hash = git(repo, "rev-parse", revision).decode().strip()
    with pytest.raises(AuditFormatError, match=object_hash):
        git_bytes(repo, object_hash, PurePosixPath("binary.bin"))


def test_fixed_manifest_matches_all_62_initial_pages_renames() -> None:
    assert MANIFEST.is_file(), "The fixed pre-Pages manifest must exist"
    inventory = load_inventory(MANIFEST)
    assert inventory.baseline_commit == BASELINE
    assert inventory.pages_commit == PAGES
    assert inventory.rename_similarity == 20
    output = git(
        ROOT, "diff", "--find-renames=30%", "--name-status", "-z", BASELINE, PAGES, "--", "*.md"
    ).decode().split("\0")
    expected = set()
    index = 0
    while index < len(output) - 1:
        status, source = output[index:index + 2]
        index += 2
        if status.startswith("R"):
            target = output[index]
            index += 1
            if re.fullmatch(r"docs/(cases|guides|labs|research)/[^/]+/[^/]+/index\.md", target):
                expected.add((PurePosixPath(source), PurePosixPath(target.removeprefix("docs/"))))
    actual = {(doc.baseline_path, doc.pages_path) for doc in inventory.documents}
    assert len(expected) == len(inventory.documents) == len(actual) == 62
    assert actual == expected


def test_fixed_manifest_has_only_the_six_exact_reviewed_dispositions() -> None:
    assert MANIFEST.is_file(), "The fixed pre-Pages manifest must exist"
    expected = {
        ".azure/deployment-plan.md": (
            "excluded-local-state", (),
            "Local Azure deployment planning state is intentionally not public.",
        ),
        ".azure/validate-status.json": (
            "excluded-local-state", (),
            "Local Azure validation state is intentionally not public.",
        ),
        "memory/README.md": (
            "replaced-summary",
            (
                "docs/services/microsoft-foundry/agent-memory/index.md",
                "docs/services/microsoft-foundry/agent-memory/samples/research-artifacts/README.md",
                "docs/services/microsoft-foundry/gpt-memory-layer/samples/architecture/README.md",
            ),
            "The service-level index was split into the canonical topic overview and owning sample documentation.",
        ),
        "ptu_lb/README.md": (
            "replaced-summary",
            ("docs/services/azure-openai/adaptive-ptu-load-balancing/samples/runbooks/README.md",),
            "The link-only README was replaced by the owning topic sample README.",
        ),
        "monitor/sre-agent-event-lab/scripts/tests/test_lab_guides.py": (
            "replaced-test",
            (
                "docs/services/azure-monitor/azure-sre-agent/samples/event-lab/scripts/tests/test_briefing_docs.py",
                "tests/docs/test_reader_navigation.py",
            ),
            "Guide-layout assertions were replaced by canonical topic, navigation, and briefing-document contracts.",
        ),
        "monitor/sre-agent-event-lab/scripts/tests/test_repo_readme.py": (
            "replaced-test",
            ("docs/services/azure-monitor/azure-sre-agent/samples/event-lab/scripts/tests/test_repo_readme.py",),
            "The repository discovery contract test moved with the sample and now targets canonical topic discovery.",
        ),
    }
    actual = {
        path.as_posix(): (
            value.status, tuple(item.as_posix() for item in value.current_paths), value.reason,
        )
        for path, value in load_inventory(MANIFEST).dispositions.items()
    }
    assert actual == expected


def lineage_api(name: str):
    assert hasattr(pre_pages, name), f"The {name} lineage API must exist"
    return getattr(pre_pages, name)


def small_inventory(baseline: str, pages: str, dispositions: dict | None = None) -> PrePagesInventory:
    return PrePagesInventory(baseline, pages, 20, (), dispositions or {})


def test_baseline_paths_include_every_file_and_preserve_literal_names(
    history: tuple[Path, str, str]
) -> None:
    repo, baseline, pages = history
    paths = lineage_api("baseline_paths")(repo, small_inventory(baseline, pages))
    assert isinstance(paths, tuple)
    assert set(paths) == {
        PurePosixPath("한글 문서.md"), PurePosixPath("binary.bin"),
        PurePosixPath("-literal ; $(touch injected)\tfile.md"),
    }


@pytest.fixture
def file_history(history: tuple[Path, str, str]) -> tuple[Path, PrePagesInventory]:
    repo, _, baseline = history
    (repo / "한글 문서.md").write_text("수정된 문장\n")
    (repo / "-literal ; $(touch injected)\tfile.md").rename(repo / "renamed\t\n한글.md")
    (repo / "added.md").unlink()
    (repo / "replacement.md").write_text("Canonical replacement overview.\n")
    (repo / "new-only.md").write_text("Not a baseline file.\n")
    pages = commit(repo, "Current")
    return repo, small_inventory(
        baseline, pages,
        {
            PurePosixPath("added.md"): ReviewedDisposition(
                "replaced-summary", (PurePosixPath("replacement.md"),), "Canonical replacement overview.",
            )
        },
    )


def test_classification_covers_unchanged_modified_renamed_and_reviewed_files(
    file_history: tuple[Path, PrePagesInventory]
) -> None:
    repo, inventory = file_history
    actual = lineage_api("classify_baseline_files")(repo, inventory)
    assert isinstance(actual, tuple)
    assert {item.baseline_path: (item.status, item.current_paths) for item in actual} == {
        PurePosixPath("binary.bin"): ("unchanged", (PurePosixPath("binary.bin"),)),
        PurePosixPath("한글 문서.md"): ("modified", (PurePosixPath("한글 문서.md"),)),
        PurePosixPath("-literal ; $(touch injected)\tfile.md"): (
            "renamed", (PurePosixPath("renamed\t\n한글.md"),),
        ),
        PurePosixPath("added.md"): ("reviewed", (PurePosixPath("replacement.md"),)),
    }
    assert len(actual) == 4


def test_classification_rejects_unreviewed_deletion(file_history: tuple[Path, PrePagesInventory]) -> None:
    repo, inventory = file_history
    with pytest.raises(AuditFormatError, match="unreviewed.*added.md"):
        lineage_api("classify_baseline_files")(repo, replace(inventory, dispositions={}))


def test_classification_rejects_disposition_outside_baseline(
    file_history: tuple[Path, PrePagesInventory]
) -> None:
    repo, inventory = file_history
    dispositions = dict(inventory.dispositions)
    dispositions[PurePosixPath("not-in-baseline.md")] = ReviewedDisposition(
        "excluded-local-state", (), "Local state.",
    )
    with pytest.raises(AuditFormatError, match="not-in-baseline.md"):
        lineage_api("classify_baseline_files")(repo, replace(inventory, dispositions=dispositions))


def test_classification_rejects_missing_replacement_path(file_history: tuple[Path, PrePagesInventory]) -> None:
    repo, inventory = file_history
    (repo / "replacement.md").unlink()
    with pytest.raises(AuditFormatError, match="replacement.md"):
        lineage_api("classify_baseline_files")(repo, inventory)


def test_classification_accepts_reviewed_local_state_exclusion(
    file_history: tuple[Path, PrePagesInventory]
) -> None:
    repo, inventory = file_history
    inventory = replace(
        inventory,
        dispositions={
            PurePosixPath("added.md"): ReviewedDisposition(
                "excluded-local-state", (), "Local state is intentionally not public.",
            )
        },
    )
    result = lineage_api("classify_baseline_files")(repo, inventory)
    assert next(item for item in result if item.baseline_path == PurePosixPath("added.md")) == (
        GitFileDisposition(PurePosixPath("added.md"), "reviewed", ())
    )


@pytest.fixture
def document_history(history: tuple[Path, str, str]) -> tuple[Path, PrePagesInventory]:
    repo, _, _ = history
    documents = tuple(
        BaselineDocument(
            PurePosixPath(f"old/topic-{index:02}.md"),
            PurePosixPath(f"guides/service/topic-{index:02}/index.md"),
            {},
        )
        for index in range(62)
    )
    for document in documents:
        path = repo / document.baseline_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n")
    baseline = commit(repo, "Historical documents")
    for document in documents:
        target = repo / "docs" / document.pages_path
        target.parent.mkdir(parents=True, exist_ok=True)
        (repo / document.baseline_path).rename(target)
    pages = commit(repo, "Initial Pages documents")
    for document in documents:
        source = repo / "docs" / document.pages_path
        target = repo / "docs/services/service" / document.pages_path.parent.name / "index.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "---\ntitle: Canonical topic\nredirect_from:\n"
            f"  - {document.pages_path}\n---\n{source.read_text()}"
        )
        source.unlink()
    (repo / "docs-taxonomy.yml").write_text("{}\n")
    commit(repo, "Canonical topics")
    return repo, PrePagesInventory(baseline, pages, 20, documents, {})


def test_current_documents_resolve_one_to_one_from_initial_pages_redirects(
    document_history: tuple[Path, PrePagesInventory]
) -> None:
    repo, inventory = document_history
    resolved = lineage_api("resolve_current_documents")(repo, inventory)
    assert len(resolved) == 62
    assert set(resolved) == {item.baseline_path for item in inventory.documents}
    assert len({item.relative_path for item in resolved.values()}) == 62
    for original in inventory.documents:
        assert resolved[original.baseline_path].relative_path == (
            PurePosixPath("services/service") / original.pages_path.parent.name / "index.md"
        )


@pytest.mark.parametrize("count", [61, 63])
def test_resolution_requires_exactly_62_inventory_documents(
    document_history: tuple[Path, PrePagesInventory], count: int
) -> None:
    repo, inventory = document_history
    documents = (
        inventory.documents[:61] if count == 61
        else inventory.documents + (inventory.documents[0],)
    )
    with pytest.raises(AuditFormatError, match="62 inventory documents"):
        lineage_api("resolve_current_documents")(repo, replace(inventory, documents=documents))


@pytest.mark.parametrize("count", [61, 63])
def test_resolution_requires_exactly_62_current_public_documents(
    document_history: tuple[Path, PrePagesInventory], count: int
) -> None:
    repo, inventory = document_history
    path = repo / "docs/services/service/topic-00/index.md"
    if count == 61:
        path.unlink()
    else:
        extra = repo / "docs/services/service/extra/index.md"
        extra.parent.mkdir()
        extra.write_text("---\ntitle: Extra\n---\n# Extra\n")
    with pytest.raises(AuditFormatError, match="62 current public documents"):
        lineage_api("resolve_current_documents")(repo, inventory)


def test_resolution_rejects_missing_initial_pages_redirect(
    document_history: tuple[Path, PrePagesInventory]
) -> None:
    repo, inventory = document_history
    path = repo / "docs/services/service/topic-00/index.md"
    path.write_text("---\ntitle: Missing redirect\n---\n")
    with pytest.raises(AuditFormatError, match="guides/service/topic-00/index.md"):
        lineage_api("resolve_current_documents")(repo, inventory)


def test_resolution_rejects_duplicate_redirect_ownership(
    document_history: tuple[Path, PrePagesInventory]
) -> None:
    repo, inventory = document_history
    path = repo / "docs/services/service/topic-01/index.md"
    path.write_text(path.read_text().replace("guides/service/topic-01/", "guides/service/topic-00/"))
    with pytest.raises(AuditFormatError, match="redirect_from.*already used"):
        lineage_api("resolve_current_documents")(repo, inventory)


def test_resolution_rejects_two_baseline_documents_using_one_current_document(
    document_history: tuple[Path, PrePagesInventory]
) -> None:
    repo, inventory = document_history
    first = repo / "docs/services/service/topic-00/index.md"
    first.write_text(first.read_text().replace(
        "redirect_from:\n", "redirect_from:\n  - guides/service/topic-01/index.md\n",
    ))
    second = repo / "docs/services/service/topic-01/index.md"
    second.write_text("---\ntitle: Unused\n---\n")
    with pytest.raises(AuditFormatError, match="used more than once"):
        lineage_api("resolve_current_documents")(repo, inventory)


def test_resolution_requires_baseline_blobs(document_history: tuple[Path, PrePagesInventory]) -> None:
    repo, inventory = document_history
    documents = (
        replace(inventory.documents[0], baseline_path=PurePosixPath("missing.md")),
        *inventory.documents[1:],
    )
    with pytest.raises(AuditFormatError, match=inventory.baseline_commit) as error:
        lineage_api("resolve_current_documents")(repo, replace(inventory, documents=documents))
    assert "missing.md" in str(error.value)


def test_resolution_requires_initial_pages_blobs(document_history: tuple[Path, PrePagesInventory]) -> None:
    repo, inventory = document_history
    with pytest.raises(AuditFormatError, match=inventory.baseline_commit) as error:
        lineage_api("resolve_current_documents")(repo, replace(inventory, pages_commit=inventory.baseline_commit))
    assert "docs/guides/service/topic-00/index.md" in str(error.value)


def test_real_repository_accounts_for_359_files_73_markdown_and_62_documents() -> None:
    inventory = load_inventory(MANIFEST)
    paths = lineage_api("baseline_paths")(ROOT, inventory)
    classified = lineage_api("classify_baseline_files")(ROOT, inventory)
    resolved = lineage_api("resolve_current_documents")(ROOT, inventory)
    assert len(paths) == len(classified) == 359
    assert sum(path.suffix == ".md" for path in paths) == 73
    assert len(resolved) == len({doc.relative_path for doc in resolved.values()}) == 62
    assert {item.baseline_path for item in classified} == set(paths)
    assert {item.status for item in classified} <= {"unchanged", "modified", "renamed", "reviewed"}
    assert Counter(item.status for item in classified)["reviewed"] == 6
