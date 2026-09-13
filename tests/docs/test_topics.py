from __future__ import annotations

from collections import defaultdict
from dataclasses import FrozenInstanceError
import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess

import pytest
import yaml

from scripts.docs.content import (
    DocumentFormatError,
    load_taxonomy,
    validate_document,
)
from scripts.docs.topics import build_topic_catalog


ROOT = Path(__file__).parents[2]


def test_repository_tracked_topic_assets_have_no_duplicate_hashes() -> None:
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "docs/services"], cwd=ROOT
    ).decode().split("\0")
    by_hash: dict[str, list[str]] = defaultdict(list)
    for relative in filter(None, tracked):
        path = ROOT / relative
        if path.stat().st_size >= 1024:
            by_hash[hashlib.sha256(path.read_bytes()).hexdigest()].append(relative)
    duplicates = [paths for paths in by_hash.values() if len(paths) > 1]
    assert not duplicates, f"{len(duplicates)} duplicate groups >=1KB: {duplicates}"


@pytest.fixture
def taxonomy() -> dict:
    return {
        "collections": {
            "guide": {
                "path": "guides",
                "statuses": ["current", "needs-review", "deprecated"],
                "required_fields": [
                    "last_verified",
                    "review_cycle_days",
                    "applies_to",
                ],
            }
        },
        "services": {"azure-monitor": "Azure Monitor"},
        "technologies": {"kubernetes": "Kubernetes"},
        "tags": {"networking": "Networking"},
        "verification_statuses": ["verified", "needs-review"],
        "official_source_hosts": ["learn.microsoft.com"],
        "required_source_host": "learn.microsoft.com",
    }


def write_document(
    root: Path,
    relative: str,
    title: str,
    *,
    topic_order: int | None = None,
    redirect_from: list[str] | None = None,
    services: list[str] | None = None,
) -> Path:
    metadata: dict[str, object] = {
        "title": title,
        "description": f"{title} description",
        "document_type": "guide",
        "services": services or ["azure-monitor"],
        "technologies": ["kubernetes"],
        "tags": ["networking"],
        "status": "current",
        "verification_status": "verified",
        "sources_checked_at": "2026-09-12",
        "official_sources": [
            {
                "title": "Azure Monitor documentation",
                "url": "https://learn.microsoft.com/azure/azure-monitor/",
            }
        ],
        "last_verified": "2026-09-12",
        "review_cycle_days": 180,
        "applies_to": ["Azure Monitor"],
    }
    if topic_order is not None:
        metadata["topic_order"] = topic_order
    if redirect_from is not None:
        metadata["redirect_from"] = redirect_from

    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n\n"
        + f"# {title}\n",
        encoding="utf-8",
    )
    return path


def write_sample(
    root: Path,
    relative: str,
    manifest: dict[str, object] | None = None,
    *,
    readme: bool = True,
) -> Path:
    sample_dir = root / relative
    sample_dir.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (sample_dir / "sample.yml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    if readme:
        (sample_dir / "README.md").write_text(
            "# Sample\n",
            encoding="utf-8",
        )
    return sample_dir


def published_sample(docs_dir: Path, publish: object) -> Path:
    write_document(docs_dir, "services/azure-monitor/agent-topic/index.md", "Agent topic")
    sample_dir = write_sample(
        docs_dir,
        "services/azure-monitor/agent-topic/samples/event-lab",
        {
            "title": "Event lab",
            "description": "Published sample assets.",
            "kind": "artifact",
            "used_by": ["index"],
            "publish": publish,
        },
    )
    (sample_dir / "diagram.svg").write_bytes(b"<svg>diagram</svg>\r\n")
    return sample_dir


def test_catalog_exposes_immutable_published_assets_without_changing_used_by(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir = tmp_path / "docs"
    sample_dir = published_sample(
        docs_dir,
        [
            {"source": "diagram.svg", "target": "images/diagram.svg"},
            {"source": "diagram.svg", "target": "setup/images/diagram.svg"},
        ],
    )
    catalog = build_topic_catalog(docs_dir, taxonomy)
    targets = [
        PurePosixPath("services/azure-monitor/agent-topic") / target
        for target in ("images/diagram.svg", "setup/images/diagram.svg")
    ]

    assert hasattr(catalog, "published_assets"), "catalog must expose validated published assets"
    assert set(catalog.published_assets) == set(targets)
    for target in targets:
        asset = catalog.published_assets[target]
        assert asset.source == PurePosixPath(sample_dir.relative_to(docs_dir).as_posix()) / "diagram.svg"
        assert asset.target == target
        assert not (docs_dir / target).exists()
        with pytest.raises(FrozenInstanceError):
            asset.target = PurePosixPath("changed.svg")
    entry = PurePosixPath("services/azure-monitor/agent-topic/index.md")
    assert catalog.samples_by_document[entry][0].used_by == (entry,)
    assert [doc.relative_path for doc in catalog.documents] == [entry]


@pytest.mark.parametrize("publish", [None, {}, "", "diagram.svg", True, 12])
def test_catalog_rejects_non_list_publish(
    tmp_path: Path, taxonomy: dict, publish: object
) -> None:
    published_sample(tmp_path, publish)
    with pytest.raises(DocumentFormatError, match="publish must be a list"):
        build_topic_catalog(tmp_path, taxonomy)


@pytest.mark.parametrize("entry", [None, [], "", "diagram.svg", True, 12])
def test_catalog_rejects_non_mapping_publish_entries(
    tmp_path: Path, taxonomy: dict, entry: object
) -> None:
    published_sample(tmp_path, [entry])
    with pytest.raises(DocumentFormatError, match="publish entries must be mappings"):
        build_topic_catalog(tmp_path, taxonomy)


@pytest.mark.parametrize("field", ["source", "target"])
@pytest.mark.parametrize("value", [None, "", "  ", 12, True, [], {}])
def test_catalog_rejects_missing_or_invalid_publish_paths(
    tmp_path: Path, taxonomy: dict, field: str, value: object
) -> None:
    mapping = {"source": "diagram.svg", "target": "images/diagram.svg"}
    mapping[field] = value
    published_sample(tmp_path, [mapping])
    with pytest.raises(DocumentFormatError, match=f"publish {field} must be a non-empty string"):
        build_topic_catalog(tmp_path, taxonomy)


@pytest.mark.parametrize("field", ["source", "target"])
@pytest.mark.parametrize(
    "value",
    ["/absolute.svg", "../escape.svg", "images/../escape.svg", "C:/absolute.svg", r"C:\absolute.svg", r"..\escape.svg"],
)
def test_catalog_rejects_unsafe_publish_paths(
    tmp_path: Path, taxonomy: dict, field: str, value: str
) -> None:
    mapping = {"source": "diagram.svg", "target": "images/diagram.svg"}
    mapping[field] = value
    published_sample(tmp_path, [mapping])
    with pytest.raises(DocumentFormatError, match=f"publish {field} must be a relative path without"):
        build_topic_catalog(tmp_path, taxonomy)


@pytest.mark.parametrize("source", ["missing.svg", ".", "assets"])
def test_catalog_rejects_missing_or_non_file_publish_sources(
    tmp_path: Path, taxonomy: dict, source: str
) -> None:
    sample_dir = published_sample(tmp_path, [{"source": source, "target": "images/diagram.svg"}])
    (sample_dir / "assets").mkdir()
    with pytest.raises(DocumentFormatError, match="publish source must be an existing file"):
        build_topic_catalog(tmp_path, taxonomy)


@pytest.mark.parametrize(
    "target",
    [
        ".notes.md",
        "downloads/.env.example",
        ".artifacts/diagram.svg",
        "downloads/.private/diagram.svg",
        "./images/diagram.svg",
        "images/./diagram.svg",
    ],
)
def test_catalog_rejects_hidden_publish_target_components(
    tmp_path: Path, taxonomy: dict, target: str
) -> None:
    published_sample(tmp_path, [{"source": "diagram.svg", "target": target}])
    with pytest.raises(
        DocumentFormatError, match="publish target must not contain hidden path components"
    ) as error:
        build_topic_catalog(tmp_path, taxonomy)
    assert target in str(error.value)
    assert "services/azure-monitor/agent-topic/samples/event-lab" in str(error.value)


@pytest.mark.parametrize("source", [".diagram.svg", ".private/diagram.svg"])
def test_catalog_allows_hidden_source_payloads_for_visible_publish_targets(
    tmp_path: Path, taxonomy: dict, source: str
) -> None:
    sample_dir = published_sample(tmp_path, [{"source": source, "target": "images/diagram.svg"}])
    hidden = sample_dir / source
    hidden.parent.mkdir(exist_ok=True)
    hidden.write_bytes(b"<svg>source payload</svg>")
    catalog = build_topic_catalog(tmp_path, taxonomy)
    target = PurePosixPath("services/azure-monitor/agent-topic/images/diagram.svg")
    assert catalog.published_assets[target].source == PurePosixPath(
        hidden.relative_to(tmp_path).as_posix()
    )


@pytest.mark.parametrize("target", ["samples/image.svg", "setup/samples/image.svg"])
def test_catalog_rejects_publish_targets_under_samples(
    tmp_path: Path, taxonomy: dict, target: str
) -> None:
    published_sample(tmp_path, [{"source": "diagram.svg", "target": target}])
    with pytest.raises(DocumentFormatError, match="publish target must not be under samples"):
        build_topic_catalog(tmp_path, taxonomy)


@pytest.mark.parametrize("other_sample", [False, True])
def test_catalog_rejects_duplicate_publish_target_ownership(
    tmp_path: Path, taxonomy: dict, other_sample: bool
) -> None:
    mapping = {"source": "diagram.svg", "target": "images/diagram.svg"}
    sample_dir = published_sample(tmp_path, [mapping] if other_sample else [mapping, mapping])
    if other_sample:
        manifest = yaml.safe_load((sample_dir / "sample.yml").read_text())
        second = write_sample(
            tmp_path, "services/azure-monitor/agent-topic/samples/other-lab", manifest
        )
        (second / "diagram.svg").write_bytes(b"another diagram")
    with pytest.raises(DocumentFormatError, match="publish target is already owned"):
        build_topic_catalog(tmp_path, taxonomy)


@pytest.mark.parametrize("descendant_first", [False, True])
@pytest.mark.parametrize("other_sample", [False, True])
def test_catalog_rejects_overlapping_publish_targets(
    tmp_path: Path, taxonomy: dict, descendant_first: bool, other_sample: bool
) -> None:
    mappings = [
        {"source": "diagram.svg", "target": "downloads/archive"},
        {"source": "diagram.svg", "target": "downloads/archive/diagram.svg"},
    ]
    if descendant_first:
        mappings.reverse()
    sample_dir = published_sample(tmp_path, mappings[:1] if other_sample else mappings)
    if other_sample:
        manifest = yaml.safe_load((sample_dir / "sample.yml").read_text())
        manifest["publish"] = mappings[1:]
        second = write_sample(
            tmp_path, "services/azure-monitor/agent-topic/samples/other-lab", manifest
        )
        (second / "diagram.svg").write_bytes(b"another diagram")

    with pytest.raises(DocumentFormatError, match="publish target.*(owned|overlap|conflict)"):
        build_topic_catalog(tmp_path, taxonomy)


@pytest.mark.parametrize(
    "target",
    ["index.html/diagram.svg", "setup/index.html/diagram.svg", "index.md/diagram.svg", "setup"],
)
def test_catalog_rejects_publish_targets_overlapping_canonical_paths(
    tmp_path: Path, taxonomy: dict, target: str
) -> None:
    published_sample(tmp_path, [{"source": "diagram.svg", "target": target}])
    write_document(
        tmp_path, "services/azure-monitor/agent-topic/setup/index.md", "Setup", topic_order=1
    )
    with pytest.raises(DocumentFormatError, match="publish target.*(collid|exist)"):
        build_topic_catalog(tmp_path, taxonomy)


@pytest.mark.parametrize(
    ("physical_path", "directory", "target"),
    [
        ("downloads/archive", False, "downloads/archive/diagram.svg"),
        ("downloads/archive/diagram.svg", False, "downloads/archive"),
        ("downloads/archive/nested", True, "downloads/archive"),
        ("downloads/archive", True, "downloads/archive"),
    ],
)
def test_catalog_rejects_publish_targets_conflicting_with_physical_paths(
    tmp_path: Path, taxonomy: dict, physical_path: str, directory: bool, target: str
) -> None:
    sample_dir = published_sample(tmp_path, [{"source": "diagram.svg", "target": target}])
    physical = sample_dir.parent.parent / physical_path
    physical.parent.mkdir(parents=True)
    if directory:
        physical.mkdir()
    else:
        physical.write_bytes(b"physical asset")
    with pytest.raises(DocumentFormatError, match="publish target.*(collid|exist|conflict)"):
        build_topic_catalog(tmp_path, taxonomy)


def test_catalog_allows_existing_parent_directories_and_similarly_named_targets(
    tmp_path: Path, taxonomy: dict
) -> None:
    mappings = [
        {"source": "diagram.svg", "target": "downloads/archive.svg"},
        {"source": "diagram.svg", "target": "downloads/archive.svg-backup/diagram.svg"},
    ]
    sample_dir = published_sample(tmp_path, mappings)
    (sample_dir.parent.parent / "downloads").mkdir()
    catalog = build_topic_catalog(tmp_path, taxonomy)
    assert len(catalog.published_assets) == 2


@pytest.mark.parametrize("target", ["index.md", "setup/index.md", "index.html", "setup/index.html"])
def test_catalog_rejects_publish_targets_colliding_with_canonical_documents(
    tmp_path: Path, taxonomy: dict, target: str
) -> None:
    published_sample(tmp_path, [{"source": "diagram.svg", "target": target}])
    if target.startswith("setup/"):
        write_document(
            tmp_path, "services/azure-monitor/agent-topic/setup/index.md", "Setup", topic_order=1
        )
    with pytest.raises(DocumentFormatError, match="publish target collides with a canonical document"):
        build_topic_catalog(tmp_path, taxonomy)


@pytest.mark.parametrize("target", ["downloads/index.md", "downloads/index.html"])
def test_catalog_allows_index_assets_without_a_canonical_document_collision(
    tmp_path: Path, taxonomy: dict, target: str
) -> None:
    published_sample(tmp_path, [{"source": "diagram.svg", "target": target}])
    catalog = build_topic_catalog(tmp_path, taxonomy)
    assert PurePosixPath("services/azure-monitor/agent-topic") / target in catalog.published_assets


@pytest.mark.parametrize("same_bytes", [False, True])
def test_catalog_rejects_physical_publish_targets(
    tmp_path: Path, taxonomy: dict, same_bytes: bool
) -> None:
    sample_dir = published_sample(tmp_path, [{"source": "diagram.svg", "target": "images/diagram.svg"}])
    physical = sample_dir.parent.parent / "images/diagram.svg"
    physical.parent.mkdir()
    physical.write_bytes((sample_dir / "diagram.svg").read_bytes() if same_bytes else b"other bytes")
    with pytest.raises(DocumentFormatError, match="publish target already exists"):
        build_topic_catalog(tmp_path, taxonomy)


@pytest.mark.parametrize("field", ["source", "target"])
def test_catalog_rejects_publish_symlink_escapes(
    tmp_path: Path, taxonomy: dict, field: str
) -> None:
    sample_dir = published_sample(
        tmp_path, [{"source": "diagram.svg", "target": "images/diagram.svg"}]
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    if field == "source":
        (outside / "diagram.svg").write_bytes(b"outside")
        (sample_dir / "diagram.svg").unlink()
        (sample_dir / "diagram.svg").symlink_to(outside / "diagram.svg")
    else:
        (sample_dir.parent.parent / "images").symlink_to(outside, target_is_directory=True)
    with pytest.raises(DocumentFormatError, match=f"publish {field} must stay within"):
        build_topic_catalog(tmp_path, taxonomy)


@pytest.mark.parametrize("publish", [[], None])
def test_catalog_accepts_empty_or_omitted_publish(
    tmp_path: Path, taxonomy: dict, publish: object
) -> None:
    sample_dir = published_sample(tmp_path, publish)
    if publish is None:
        manifest_path = sample_dir / "sample.yml"
        manifest = yaml.safe_load(manifest_path.read_text())
        del manifest["publish"]
        manifest_path.write_text(yaml.safe_dump(manifest))
    catalog = build_topic_catalog(tmp_path, taxonomy)
    assert getattr(catalog, "published_assets", None) == {}


def test_build_topic_catalog_discovers_canonical_topic_documents_and_samples(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir = tmp_path / "docs"
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/index.md",
        "Agent topic",
    )
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/setup/index.md",
        "Setup",
        topic_order=1,
    )
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/results/index.md",
        "Results",
        topic_order=2,
    )
    write_sample(
        docs_dir,
        "services/azure-monitor/agent-topic/samples/event-lab",
        {
            "title": "Event lab",
            "description": "Reproduces the monitored incident.",
            "kind": "runnable",
            "used_by": ["setup", "results"],
        },
    )

    catalog = build_topic_catalog(docs_dir, taxonomy)
    topic = catalog.topics[("azure-monitor", "agent-topic")]

    assert topic.entry.relative_path == PurePosixPath(
        "services/azure-monitor/agent-topic/index.md"
    )
    assert [member.relative_path for member in topic.members] == [
        PurePosixPath("services/azure-monitor/agent-topic/index.md"),
        PurePosixPath("services/azure-monitor/agent-topic/setup/index.md"),
        PurePosixPath("services/azure-monitor/agent-topic/results/index.md"),
    ]
    assert catalog.position_by_document[topic.members[2].relative_path] == 2
    assert [
        sample.slug
        for sample in catalog.samples_by_document[topic.members[1].relative_path]
    ] == ["event-lab"]


def test_build_topic_catalog_discovers_only_canonical_documents(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir = tmp_path / "docs"
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/index.md",
        "Agent topic",
    )
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/setup/index.md",
        "Setup",
        topic_order=1,
    )
    write_document(
        docs_dir,
        "guides/azure-monitor/agent-topic/index.md",
        "Legacy topic",
    )
    write_sample(
        docs_dir,
        "services/azure-monitor/agent-topic/samples/entry-lab",
        {
            "title": "Entry lab",
            "description": "Owned by the canonical entry only.",
            "kind": "runnable",
            "used_by": ["index"],
        },
    )

    catalog = build_topic_catalog(docs_dir, taxonomy)

    assert [sample.slug for sample in catalog.samples_by_document[PurePosixPath("services/azure-monitor/agent-topic/index.md")]] == [
        "entry-lab"
    ]
    assert all(
        document.relative_path.parts[0] == "services"
        for document in catalog.documents
    )
    assert PurePosixPath(
        "guides/azure-monitor/agent-topic/index.md"
    ) not in catalog.by_document


@pytest.mark.parametrize("unrelated_topic", [False, True])
def test_build_topic_catalog_rejects_samples_without_topic_entry(
    tmp_path: Path, taxonomy: dict, unrelated_topic: bool
) -> None:
    docs_dir = tmp_path / "docs"
    if unrelated_topic:
        write_document(
            docs_dir,
            "services/azure-monitor/other-topic/index.md",
            "Other topic",
        )
    write_sample(
        docs_dir,
        "services/azure-monitor/orphan-topic/samples/event-lab",
        {
            "title": "Event lab",
            "description": "No topic owns this sample.",
            "kind": "runnable",
            "used_by": ["index"],
        },
    )

    with pytest.raises(
        DocumentFormatError,
        match=re.escape("services/azure-monitor/orphan-topic/index.md: topic entry document is missing"),
    ):
        build_topic_catalog(docs_dir, taxonomy)


@pytest.mark.parametrize("child_document", [False, True])
def test_build_topic_catalog_rejects_samples_beneath_child(
    tmp_path: Path, taxonomy: dict, child_document: bool
) -> None:
    docs_dir = tmp_path / "docs"
    write_document(docs_dir, "services/azure-monitor/agent-topic/index.md", "Agent topic")
    if child_document:
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/setup/index.md",
            "Setup",
            topic_order=1,
        )
    write_sample(
        docs_dir,
        "services/azure-monitor/agent-topic/setup/samples/event-lab",
        {
            "title": "Event lab",
            "description": "Misplaced sample.",
            "kind": "runnable",
            "used_by": ["index"],
        },
    )

    with pytest.raises(
        DocumentFormatError,
        match=re.escape("services/azure-monitor/agent-topic/setup/samples: samples must be directly below the topic"),
    ):
        build_topic_catalog(docs_dir, taxonomy)


def test_build_topic_catalog_rejects_loose_files_in_topic_samples(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir = tmp_path / "docs"
    write_document(docs_dir, "services/azure-monitor/agent-topic/index.md", "Agent topic")
    samples_root = docs_dir / "services/azure-monitor/agent-topic/samples"
    samples_root.mkdir()
    (samples_root / "loose.py").write_text("print('unowned')\n", encoding="utf-8")

    with pytest.raises(
        DocumentFormatError,
        match=re.escape("services/azure-monitor/agent-topic/samples/loose.py: sample files must belong to a sample package"),
    ):
        build_topic_catalog(docs_dir, taxonomy)


@pytest.mark.parametrize("sample_slug", ["event-lab", "samples"])
def test_build_topic_catalog_allows_samples_directories_inside_sample_payload(
    tmp_path: Path, taxonomy: dict, sample_slug: str
) -> None:
    docs_dir = tmp_path / "docs"
    entry_path = "services/azure-monitor/agent-topic/index.md"
    write_document(docs_dir, entry_path, "Agent topic")
    sample_dir = write_sample(
        docs_dir,
        f"services/azure-monitor/agent-topic/samples/{sample_slug}",
        {
            "title": "Event lab",
            "description": "Contains nested example payloads.",
            "kind": "runnable",
            "used_by": ["index"],
        },
    )
    for relative in ("samples/demo", "src/samples/demo", "samples/demo/samples/inner"):
        payload = sample_dir / relative
        payload.mkdir(parents=True, exist_ok=True)
        (payload / "index.md").write_text("# Payload, not a public document\n", encoding="utf-8")
        (payload / "sample.yml").write_text("not a sample manifest\n", encoding="utf-8")
    (sample_dir / "samples/loose.py").write_text("print('owned payload')\n", encoding="utf-8")

    catalog = build_topic_catalog(docs_dir, taxonomy)

    assert len(catalog.documents) == 1
    assert [sample.slug for sample in catalog.samples_by_document[PurePosixPath(entry_path)]] == [
        sample_slug
    ]


@pytest.mark.parametrize(
    ("invalid_field", "invalid_value", "expected"),
    [
        ("sample.yml", None, "sample.yml is required"),
        ("README.md", None, "README.md is required"),
        ("kind", "unsupported", "kind must be runnable or artifact"),
        ("used_by", ["missing"], "unknown document slug: missing"),
        ("used_by", [], "used_by must be a non-empty list"),
        ("used_by", ["index", "index"], "used_by values must be unique"),
    ],
)
def test_build_topic_catalog_validates_every_immediate_sample_package(
    tmp_path: Path, taxonomy: dict, invalid_field: str, invalid_value: object, expected: str
) -> None:
    docs_dir = tmp_path / "docs"
    write_document(docs_dir, "services/azure-monitor/agent-topic/index.md", "Agent topic")
    manifest = {
        "title": "Event lab",
        "description": "Owned by the topic.",
        "kind": "artifact",
        "used_by": ["index"],
    }
    write_sample(docs_dir, "services/azure-monitor/agent-topic/samples/a-valid", manifest)
    invalid_sample = write_sample(
        docs_dir, "services/azure-monitor/agent-topic/samples/z-invalid", manifest
    )
    if invalid_field in {"sample.yml", "README.md"}:
        (invalid_sample / invalid_field).unlink()
    else:
        (invalid_sample / "sample.yml").write_text(
            yaml.safe_dump({**manifest, invalid_field: invalid_value}), encoding="utf-8"
        )

    with pytest.raises(DocumentFormatError, match=re.escape(f"samples/z-invalid: {expected}")):
        build_topic_catalog(docs_dir, taxonomy)


def test_build_topic_catalog_rejects_reserved_index_child_slug(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir = tmp_path / "docs"
    write_document(docs_dir, "services/azure-monitor/agent-topic/index.md", "Agent topic")
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/index/index.md",
        "Reserved child",
        topic_order=1,
    )

    with pytest.raises(
        DocumentFormatError,
        match=re.escape("services/azure-monitor/agent-topic/index/index.md: child slug 'index' is reserved for the topic entry"),
    ):
        build_topic_catalog(docs_dir, taxonomy)


def test_reserved_child_cannot_redirect_entry_sample_ownership(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir = tmp_path / "docs"
    entry_path = PurePosixPath("services/azure-monitor/agent-topic/index.md")
    write_document(docs_dir, entry_path.as_posix(), "Agent topic")
    write_sample(
        docs_dir,
        "services/azure-monitor/agent-topic/samples/entry-lab",
        {
            "title": "Entry lab",
            "description": "Owned only by the topic entry.",
            "kind": "runnable",
            "used_by": ["index"],
        },
    )
    catalog = build_topic_catalog(docs_dir, taxonomy)
    assert catalog.samples_by_document[entry_path][0].used_by == (entry_path,)
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/index/index.md",
        "Cannot take entry ownership",
        topic_order=1,
    )

    with pytest.raises(
        DocumentFormatError, match="child slug 'index' is reserved for the topic entry"
    ):
        build_topic_catalog(docs_dir, taxonomy)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("missing root index", "topic entry document is missing"),
        ("child without topic_order", "topic_order must be a positive integer"),
        ("duplicate child order", "duplicate topic_order 1"),
        ("non-contiguous order", "topic_order values must be contiguous from 1"),
        ("nested grandchild", "child documents must be directly below the topic"),
        ("sample missing manifest", "sample.yml is required"),
        ("sample missing readme", "README.md is required"),
        ("invalid sample kind", "kind must be runnable or artifact"),
        ("empty used_by", "used_by must be a non-empty list"),
        ("unknown used_by", "unknown document slug"),
        ("duplicate redirect", "redirect_from path is already used"),
    ],
)
def test_build_topic_catalog_rejects_invalid_topic_and_sample_layouts(
    tmp_path: Path, taxonomy: dict, case: str, expected: str
) -> None:
    docs_dir = tmp_path / "docs"
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/index.md",
        "Agent topic",
    )
    write_document(
        docs_dir,
        "services/azure-monitor/agent-topic/setup/index.md",
        "Setup",
        topic_order=1,
    )

    if case == "missing root index":
        (docs_dir / "services/azure-monitor/agent-topic/index.md").unlink()
    elif case == "child without topic_order":
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/results/index.md",
            "Results",
        )
    elif case == "duplicate child order":
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/results/index.md",
            "Results",
            topic_order=1,
        )
    elif case == "non-contiguous order":
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/results/index.md",
            "Results",
            topic_order=3,
        )
    elif case == "nested grandchild":
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/setup/deeper/index.md",
            "Deeper",
            topic_order=2,
        )
    elif case == "sample missing manifest":
        write_sample(
            docs_dir,
            "services/azure-monitor/agent-topic/samples/event-lab",
            None,
        )
    elif case == "sample missing readme":
        write_sample(
            docs_dir,
            "services/azure-monitor/agent-topic/samples/event-lab",
            {
                "title": "Event lab",
                "description": "Reproduces the monitored incident.",
                "kind": "runnable",
                "used_by": ["setup"],
            },
            readme=False,
        )
    elif case == "invalid sample kind":
        write_sample(
            docs_dir,
            "services/azure-monitor/agent-topic/samples/event-lab",
            {
                "title": "Event lab",
                "description": "Reproduces the monitored incident.",
                "kind": "broken",
                "used_by": ["setup"],
            },
        )
    elif case == "empty used_by":
        write_sample(
            docs_dir,
            "services/azure-monitor/agent-topic/samples/event-lab",
            {
                "title": "Event lab",
                "description": "Reproduces the monitored incident.",
                "kind": "runnable",
                "used_by": [],
            },
        )
    elif case == "unknown used_by":
        write_sample(
            docs_dir,
            "services/azure-monitor/agent-topic/samples/event-lab",
            {
                "title": "Event lab",
                "description": "Reproduces the monitored incident.",
                "kind": "runnable",
                "used_by": ["unknown"],
            },
        )
    elif case == "duplicate redirect":
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/results/index.md",
            "Results",
            topic_order=2,
            redirect_from=["guides/azure-monitor/shared/index.md"],
        )
        write_document(
            docs_dir,
            "services/azure-monitor/agent-topic/verify/index.md",
            "Verify",
            topic_order=3,
            redirect_from=["guides/azure-monitor/shared/index.md"],
        )
    with pytest.raises(DocumentFormatError, match=re.escape(expected)):
        build_topic_catalog(docs_dir, taxonomy)


def test_validate_document_rejects_canonical_service_paths_absent_from_taxonomy(
    tmp_path: Path, taxonomy: dict
) -> None:
    path = write_document(
        tmp_path / "docs",
        "services/unknown-service/agent-topic/index.md",
        "Agent topic",
        services=["unknown-service"],
    )
    from scripts.docs.content import load_document

    document = load_document(path, docs_dir=tmp_path / "docs")

    errors = validate_document(document, taxonomy)

    assert "unknown service: unknown-service" in errors


def test_build_topic_catalog_ignores_legacy_collection_documents(
    tmp_path: Path, taxonomy: dict
) -> None:
    docs_dir = tmp_path / "docs"
    write_document(
        docs_dir,
        "guides/azure-monitor/agent-topic/index.md",
        "Guide legacy topic",
    )
    write_document(
        docs_dir,
        "labs/azure-monitor/agent-topic/index.md",
        "Lab legacy topic",
    )

    catalog = build_topic_catalog(docs_dir, taxonomy)

    assert catalog.documents == ()
    assert catalog.topics == {}


def test_repository_connected_topics_have_canonical_layout() -> None:
    expected = {
        ("microsoft-foundry", "agent-memory"): {
            "slugs": [
                "index",
                "taxonomy",
                "architecture-patterns",
                "pipeline-retrieval",
                "frameworks",
                "production-evaluation",
                "commerce",
            ],
            "redirects": [
                "research/microsoft-foundry/agent-memory-overview/index.md",
                "research/microsoft-foundry/agent-memory-taxonomy/index.md",
                "research/microsoft-foundry/agent-memory-architecture-patterns/index.md",
                "research/microsoft-foundry/agent-memory-pipeline-retrieval/index.md",
                "research/microsoft-foundry/agent-memory-frameworks/index.md",
                "research/microsoft-foundry/agent-memory-production-evaluation/index.md",
                "research/microsoft-foundry/agent-memory-commerce/index.md",
            ],
        },
        ("azure-monitor", "azure-sre-agent"): {
            "slugs": [
                "index",
                "event-lab",
                "setup",
                "scenario-http-500",
                "scenario-latency",
                "scenario-blob-permission",
                "results",
                "validation-results",
                "incident-runbook",
                "dynamic-thresholds",
            ],
            "redirects": [
                "guides/azure-monitor/azure-sre-agent-overview/index.md",
                "labs/azure-monitor/sre-agent-event-lab/index.md",
                "labs/azure-monitor/sre-agent-event-lab-setup/index.md",
                "labs/azure-monitor/sre-agent-scenario-http-500/index.md",
                "labs/azure-monitor/sre-agent-scenario-latency/index.md",
                "labs/azure-monitor/sre-agent-scenario-blob-permission/index.md",
                "labs/azure-monitor/sre-agent-results/index.md",
                "research/azure-monitor/sre-agent-validation-results/index.md",
                "guides/azure-monitor/sre-agent-incident-runbook/index.md",
                "guides/azure-monitor/sre-agent-dynamic-thresholds/index.md",
            ],
        },
        ("azure-ai-search", "custom-vectorization"): {
            "slugs": [
                "index",
                "rag-chunking",
                "custom-web-api",
                "gpu-vllm",
                "bge-m3-vs-qwen3",
                "a10-vs-t4",
            ],
            "redirects": [
                "guides/azure-ai-search/custom-embedding-ingestion/index.md",
                "research/azure-ai-search/rag-chunking-strategies/index.md",
                "guides/azure-ai-search/custom-web-api-vectorization/index.md",
                "guides/azure-ai-search/gpu-vllm-rag/index.md",
                "research/azure-ai-search/bge-m3-vs-qwen3-embedding/index.md",
                "research/azure-ai-search/a10-vs-t4-embedding-benchmark/index.md",
            ],
        },
        ("azure-monitor", "hdinsight-kafka-monitoring"): {
            "slugs": ["index", "prometheus-grafana", "catch-up-benchmark"],
            "redirects": [
                "research/azure-monitor/hdinsight-kafka-monitoring-options/index.md",
                "guides/azure-monitor/hdinsight-kafka-prometheus-grafana/index.md",
                "research/azure-hdinsight/kafka-catchup-sku-fetch-benchmark/index.md",
            ],
        },
    }
    catalog = build_topic_catalog(
        ROOT / "docs", load_taxonomy(ROOT / "docs-taxonomy.yml")
    )

    for topic_key, topic_expected in expected.items():
        topic = catalog.topics[topic_key]
        slugs = [
            "index" if member == topic.entry else member.relative_path.parts[-2]
            for member in topic.members
        ]

        assert slugs == topic_expected["slugs"]
        assert "topic_order" not in topic.entry.metadata
        assert [
            member.metadata.get("redirect_from") for member in topic.members
        ] == [[redirect] for redirect in topic_expected["redirects"]]


def test_repository_uses_only_canonical_topic_packages() -> None:
    moved_documents = {
        ("application-development", "nodejs-file-io-cpu"):
            "guides/application-development/nodejs-file-io-cpu/index.md",
        ("azure-ai-search", "eventual-consistency-reindex"):
            "cases/azure-ai-search/eventual-consistency-reindex/index.md",
        ("azure-ai-search", "korean-analyzer-comparison"):
            "guides/azure-ai-search/korean-analyzer-comparison/index.md",
        ("azure-application-gateway", "sse-response-buffering"):
            "guides/azure-application-gateway/sse-response-buffering/index.md",
        ("azure-application-gateway", "waf-path-ip-allowlist"):
            "guides/azure-application-gateway/waf-path-ip-allowlist/index.md",
        ("azure-architecture", "response-time-optimization"):
            "guides/azure-architecture/response-time-optimization/index.md",
        ("azure-automation", "portal-cli-limitations"):
            "guides/azure-automation/portal-cli-limitations/index.md",
        ("azure-cosmos-db", "nodejs-client-optimization"):
            "guides/azure-cosmos-db/nodejs-client-optimization/index.md",
        ("azure-cosmos-db", "nodejs-dns-lookup-bottleneck"):
            "guides/azure-cosmos-db/nodejs-dns-lookup-bottleneck/index.md",
        ("azure-cosmos-db", "point-read-optimization"):
            "guides/azure-cosmos-db/point-read-optimization/index.md",
        ("azure-database-for-mysql", "blue-green-upgrade"):
            "guides/azure-database-for-mysql/blue-green-upgrade/index.md",
        ("azure-database-for-mysql", "nodejs-read-write-routing"):
            "guides/azure-database-for-mysql/nodejs-read-write-routing/index.md",
        ("azure-kubernetes-service", "file-io-throttling"):
            "cases/azure-kubernetes-service/file-io-throttling/index.md",
        ("azure-kubernetes-service", "netapp-files-cpu-io-wait"):
            "cases/azure-kubernetes-service/netapp-files-cpu-io-wait/index.md",
        ("azure-kubernetes-service", "pod-database-query-latency"):
            "cases/azure-kubernetes-service/pod-database-query-latency/index.md",
        ("azure-kubernetes-service", "argocd-image-updater-acr"):
            "guides/azure-kubernetes-service/argocd-image-updater-acr/index.md",
        ("azure-kubernetes-service", "authorization-troubleshooting"):
            "guides/azure-kubernetes-service/authorization-troubleshooting/index.md",
        ("azure-kubernetes-service", "cni-overlay-nsg"):
            "guides/azure-kubernetes-service/cni-overlay-nsg/index.md",
        ("azure-kubernetes-service", "kaito-open-source-model"):
            "guides/azure-kubernetes-service/kaito-open-source-model/index.md",
        ("azure-kubernetes-service", "pod-affinity-distribution"):
            "guides/azure-kubernetes-service/pod-affinity-distribution/index.md",
        ("azure-kubernetes-service", "pod-scheduling-agent-pools"):
            "guides/azure-kubernetes-service/pod-scheduling-agent-pools/index.md",
        ("azure-kubernetes-service", "pyroscope-anf-s3"):
            "guides/azure-kubernetes-service/pyroscope-anf-s3/index.md",
        ("azure-kubernetes-service", "python-memory-leak-memray"):
            "guides/azure-kubernetes-service/python-memory-leak-memray/index.md",
        ("azure-kubernetes-service", "remote-cluster-local-development"):
            "guides/azure-kubernetes-service/remote-cluster-local-development/index.md",
        ("azure-kubernetes-service", "spot-h100-kaito"):
            "guides/azure-kubernetes-service/spot-h100-kaito/index.md",
        ("azure-kubernetes-service", "workload-identity-databricks"):
            "guides/azure-kubernetes-service/workload-identity-databricks/index.md",
        ("azure-load-testing", "locust-appgw-aks-private"):
            "guides/azure-load-testing/locust-appgw-aks-private/index.md",
        ("azure-managed-redis", "cluster-failover-recovery"):
            "cases/azure-managed-redis/cluster-failover-recovery/index.md",
        ("azure-monitor", "aks-private-opentelemetry"):
            "guides/azure-monitor/aks-private-opentelemetry/index.md",
        ("azure-monitor", "dynamic-thresholds-brief"):
            "research/azure-monitor/dynamic-thresholds-brief/index.md",
        ("azure-openai", "adaptive-ptu-load-balancing"):
            "guides/azure-openai/adaptive-ptu-load-balancing/index.md",
        ("azure-storage", "mobile-resumable-upload-tus"):
            "guides/azure-storage/mobile-resumable-upload-tus/index.md",
        ("microsoft-foundry", "agent-framework-2026"):
            "research/microsoft-foundry/agent-framework-2026/index.md",
        ("microsoft-foundry", "codex-closed-network"):
            "guides/microsoft-foundry/codex-closed-network/index.md",
        ("microsoft-foundry", "foundry-local-air-gapped"):
            "guides/microsoft-foundry/foundry-local-air-gapped/index.md",
        ("microsoft-foundry", "gpt-memory-layer"):
            "guides/microsoft-foundry/gpt-memory-layer/index.md",
    }
    catalog = build_topic_catalog(
        ROOT / "docs", load_taxonomy(ROOT / "docs-taxonomy.yml")
    )

    assert len(catalog.documents) == 66
    assert len(catalog.topics) == 41
    assert not any(
        (ROOT / "docs" / name).exists()
        for name in ("cases", "guides", "labs", "research")
    )
    assert not (ROOT / "samples").exists()
    assert all(
        document.relative_path.parts[0] == "services"
        for document in catalog.documents
    )
    assert {
        redirect
        for topic_key, redirect in moved_documents.items()
        if catalog.topics[topic_key].entry.metadata.get("redirect_from") == [redirect]
    } == set(moved_documents.values())


def test_mobile_upload_commands_use_the_canonical_sample_path() -> None:
    guide = (
        ROOT
        / "docs"
        / "services"
        / "azure-storage"
        / "mobile-resumable-upload-tus"
        / "index.md"
    ).read_text(encoding="utf-8")
    sample_path = (
        "docs/services/azure-storage/mobile-resumable-upload-tus/"
        "samples/spring-application"
    )

    assert f"cd {sample_path}\n" in guide
    assert f"cd {sample_path}/scripts\n" in guide
    assert "cd azureblob/spring-resumable-upload" not in guide
    assert "cd spring-resumable-upload/scripts" not in guide
