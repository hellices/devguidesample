"""Topic-package catalog for transitional and canonical documentation layouts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import yaml

from scripts.docs.content import Document, DocumentFormatError, load_document


LEGACY_COLLECTIONS = frozenset(("cases", "guides", "labs", "research"))


@dataclass(frozen=True)
class SampleAsset:
    slug: str
    title: str
    description: str
    kind: str
    relative_path: PurePosixPath
    used_by: tuple[PurePosixPath, ...]


@dataclass(frozen=True)
class Topic:
    primary_service: str
    slug: str
    entry: Document
    members: tuple[Document, ...]
    samples: tuple[SampleAsset, ...]


@dataclass(frozen=True)
class TopicCatalog:
    documents: tuple[Document, ...]
    topics: dict[tuple[str, str], Topic]
    by_document: dict[PurePosixPath, Topic]
    position_by_document: dict[PurePosixPath, int]
    samples_by_document: dict[PurePosixPath, tuple[SampleAsset, ...]]
    redirects: dict[PurePosixPath, PurePosixPath]


def _legacy_collection_paths(taxonomy: Mapping[str, Any]) -> tuple[str, ...]:
    paths = {
        config["path"]
        for config in taxonomy.get("collections", {}).values()
        if isinstance(config, Mapping) and isinstance(config.get("path"), str)
    }
    return tuple(sorted(paths))


def _is_canonical_document_path(relative_path: PurePosixPath) -> bool:
    parts = relative_path.parts
    return (
        len(parts) in {4, 5}
        and parts[0] == "services"
        and parts[-1] == "index.md"
        and "samples" not in parts
    )


def _is_legacy_document_path(
    relative_path: PurePosixPath, collection_paths: Iterable[str]
) -> bool:
    parts = relative_path.parts
    return (
        len(parts) == 4
        and parts[-1] == "index.md"
        and parts[0] in set(collection_paths)
    )


def iter_topic_documents(
    docs_dir: Path | str, taxonomy: Mapping[str, Any], include_legacy: bool = True
) -> Iterable[Document]:
    root = Path(docs_dir)
    collection_paths = _legacy_collection_paths(taxonomy)
    candidates: list[Path] = []

    services_root = root / "services"
    if services_root.is_dir():
        for path in services_root.rglob("index.md"):
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if _is_canonical_document_path(relative):
                candidates.append(path)

    if include_legacy:
        for collection_path in collection_paths:
            collection_root = root / collection_path
            if not collection_root.is_dir():
                continue
            for path in collection_root.rglob("index.md"):
                relative = PurePosixPath(path.relative_to(root).as_posix())
                if _is_legacy_document_path(relative, collection_paths):
                    candidates.append(path)

    for path in sorted(candidates, key=lambda item: item.relative_to(root).as_posix()):
        yield load_document(path, docs_dir=root)


def _topic_key(relative_path: PurePosixPath) -> tuple[str, str]:
    return (relative_path.parts[1], relative_path.parts[2])


def _sample_directory_errors(topic_root: Path, docs_root: Path) -> list[str]:
    samples_root = topic_root / "samples"
    if not samples_root.is_dir():
        return []

    errors: list[str] = []
    for sample_dir in sorted(path for path in samples_root.iterdir() if path.is_dir()):
        relative = PurePosixPath(sample_dir.relative_to(docs_root).as_posix())
        if not (sample_dir / "sample.yml").is_file():
            errors.append(f"{relative.as_posix()}: sample.yml is required")
        if not (sample_dir / "README.md").is_file():
            errors.append(f"{relative.as_posix()}: README.md is required")
    return errors


def _normalize_redirects(document: Document) -> tuple[list[PurePosixPath], list[str]]:
    value = document.metadata.get("redirect_from")
    if value is None:
        return [], []

    errors: list[str] = []
    if not isinstance(value, list) or not value:
        return [], [f"{document.relative_path.as_posix()}: redirect_from must be a non-empty list"]

    paths: list[PurePosixPath] = []
    for raw in value:
        if not isinstance(raw, str) or not raw.strip():
            errors.append(
                f"{document.relative_path.as_posix()}: redirect_from entries must be non-empty strings"
            )
            continue
        path = PurePosixPath(raw.strip())
        if (
            path.is_absolute()
            or ".." in path.parts
            or len(path.parts) != 4
            or path.parts[-1] != "index.md"
            or path.parts[0] not in LEGACY_COLLECTIONS
        ):
            errors.append(
                f"{document.relative_path.as_posix()}: redirect_from must use <collection>/<service>/<topic>/index.md"
            )
            continue
        paths.append(path)
    return paths, errors


def _build_sample_asset(
    sample_dir: Path,
    docs_root: Path,
    slug_to_document: Mapping[str, PurePosixPath],
) -> tuple[SampleAsset | None, list[str]]:
    relative = PurePosixPath(sample_dir.relative_to(docs_root).as_posix())
    manifest_path = sample_dir / "sample.yml"
    if not manifest_path.is_file() or not (sample_dir / "README.md").is_file():
        return None, []

    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return None, [f"{relative.as_posix()}: invalid sample.yml: {error}"]
    if not isinstance(manifest, Mapping):
        return None, [f"{relative.as_posix()}: sample.yml must be a mapping"]

    errors: list[str] = []
    values: dict[str, str] = {}
    for field in ("title", "description", "kind"):
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{relative.as_posix()}: {field} must be a non-empty string")
        else:
            values[field] = value.strip()

    kind = values.get("kind")
    if kind is not None and kind not in {"runnable", "artifact"}:
        errors.append(f"{relative.as_posix()}: kind must be runnable or artifact")

    used_by = manifest.get("used_by")
    if (
        not isinstance(used_by, list)
        or not used_by
        or not all(isinstance(item, str) and item.strip() for item in used_by)
    ):
        errors.append(f"{relative.as_posix()}: used_by must be a non-empty list")
        return None, errors

    if len({item.strip() for item in used_by}) != len(used_by):
        errors.append(f"{relative.as_posix()}: used_by values must be unique")

    linked_documents: list[PurePosixPath] = []
    for item in used_by:
        document_path = slug_to_document.get(item.strip())
        if document_path is None:
            errors.append(f"{relative.as_posix()}: unknown document slug: {item}")
        else:
            linked_documents.append(document_path)

    if errors:
        return None, errors

    return (
        SampleAsset(
            slug=sample_dir.name,
            title=values["title"],
            description=values["description"],
            kind=values["kind"],
            relative_path=relative,
            used_by=tuple(linked_documents),
        ),
        [],
    )


def build_topic_catalog(
    docs_dir: Path | str, taxonomy: Mapping[str, Any], include_legacy: bool = True
) -> TopicCatalog:
    root = Path(docs_dir)
    documents = tuple(iter_topic_documents(root, taxonomy, include_legacy=include_legacy))
    ordered_documents = tuple(
        sorted(documents, key=lambda document: document.relative_path.as_posix())
    )
    collection_paths = _legacy_collection_paths(taxonomy)
    errors: list[str] = []

    services_root = root / "services"
    if services_root.is_dir():
        for path in sorted(services_root.rglob("index.md")):
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if "samples" in relative.parts:
                continue
            if len(relative.parts) > 5:
                errors.append(
                    f"{relative.as_posix()}: child documents must be directly below the topic"
                )

    canonical_documents = [
        document for document in ordered_documents if document.relative_path.parts[0] == "services"
    ]
    legacy_documents = [
        document
        for document in ordered_documents
        if document.relative_path.parts[0] in set(collection_paths)
    ]
    grouped: dict[tuple[str, str], list[Document]] = {}
    for document in canonical_documents:
        grouped.setdefault(_topic_key(document.relative_path), []).append(document)

    topics: dict[tuple[str, str], Topic] = {}
    by_document: dict[PurePosixPath, Topic] = {}
    position_by_document: dict[PurePosixPath, int] = {}
    samples_by_document: dict[PurePosixPath, tuple[SampleAsset, ...]] = {}

    legacy_by_key = {
        (document.relative_path.parts[1], document.relative_path.parts[2]): document
        for document in legacy_documents
        if _is_legacy_document_path(document.relative_path, collection_paths)
    }

    for key in sorted(grouped):
        service, slug = key
        members = grouped[key]
        member_by_path = {member.relative_path: member for member in members}
        entry_path = PurePosixPath("services", service, slug, "index.md")
        entry = member_by_path.get(entry_path)
        if entry is None:
            errors.append(f"{entry_path.as_posix()}: topic entry document is missing")
            continue

        children: list[tuple[int, Document]] = []
        orders: dict[int, list[Document]] = {}
        for member in members:
            if member.relative_path == entry_path:
                continue
            order = member.metadata.get("topic_order")
            if isinstance(order, bool) or not isinstance(order, int) or order <= 0:
                errors.append(
                    f"{member.relative_path.as_posix()}: topic_order must be a positive integer"
                )
                continue
            orders.setdefault(order, []).append(member)
            children.append((order, member))

        for order, duplicates in sorted(orders.items()):
            if len(duplicates) > 1:
                joined = ", ".join(
                    item.relative_path.as_posix()
                    for item in sorted(duplicates, key=lambda document: document.relative_path.as_posix())
                )
                errors.append(
                    f"{duplicates[0].relative_path.as_posix()}: duplicate topic_order {order}: {joined}"
                )

        ordered_children = [member for _, member in sorted(children, key=lambda item: item[0])]
        actual_orders = [order for order, _ in sorted(children, key=lambda item: item[0])]
        if actual_orders != list(range(1, len(ordered_children) + 1)):
            errors.append(
                f"{entry.relative_path.as_posix()}: topic_order values must be contiguous from 1"
            )

        topic_root = root / "services" / service / slug
        errors.extend(_sample_directory_errors(topic_root, root))

        member_paths = [entry.relative_path, *[child.relative_path for child in ordered_children]]
        slug_to_document = {
            "index": entry.relative_path,
            **{
                child.relative_path.parts[3]: child.relative_path
                for child in ordered_children
            },
        }
        samples: list[SampleAsset] = []
        samples_root = topic_root / "samples"
        if samples_root.is_dir():
            for sample_dir in sorted(path for path in samples_root.iterdir() if path.is_dir()):
                sample, sample_errors = _build_sample_asset(sample_dir, root, slug_to_document)
                errors.extend(sample_errors)
                if sample is not None:
                    samples.append(sample)

        if errors:
            continue

        ordered_samples = tuple(sorted(samples, key=lambda item: item.title.casefold()))
        members_tuple = (entry, *ordered_children)
        topic = Topic(
            primary_service=service,
            slug=slug,
            entry=entry,
            members=members_tuple,
            samples=ordered_samples,
        )
        topics[key] = topic
        for position, member in enumerate(members_tuple):
            by_document[member.relative_path] = topic
            position_by_document[member.relative_path] = position
            samples_by_document[member.relative_path] = tuple(
                sample for sample in ordered_samples if member.relative_path in sample.used_by
            )

    canonical_paths = {document.relative_path for document in ordered_documents}
    redirects: dict[PurePosixPath, PurePosixPath] = {}
    for document in ordered_documents:
        redirect_paths, redirect_errors = _normalize_redirects(document)
        errors.extend(redirect_errors)
        for redirect_path in redirect_paths:
            if redirect_path in canonical_paths:
                errors.append(
                    f"{document.relative_path.as_posix()}: redirect_from collides with a canonical document"
                )
                continue
            if redirect_path in redirects:
                errors.append(
                    f"{document.relative_path.as_posix()}: redirect_from path is already used"
                )
                continue
            redirects[redirect_path] = document.relative_path

    if errors:
        raise DocumentFormatError("invalid topic catalog:\n" + "\n".join(errors))

    for key in sorted(legacy_by_key):
        if key in topics:
            legacy_document = legacy_by_key[key]
            by_document[legacy_document.relative_path] = topics[key]
            continue
        legacy_document = legacy_by_key[key]
        topic = Topic(
            primary_service=key[0],
            slug=key[1],
            entry=legacy_document,
            members=(legacy_document,),
            samples=(),
        )
        topics[key] = topic
        by_document[legacy_document.relative_path] = topic
        position_by_document[legacy_document.relative_path] = 0
        samples_by_document[legacy_document.relative_path] = ()

    for redirect_path, canonical_path in redirects.items():
        topic = by_document.get(canonical_path)
        if topic is not None:
            by_document[redirect_path] = topic

    return TopicCatalog(
        documents=ordered_documents,
        topics=topics,
        by_document=by_document,
        position_by_document=position_by_document,
        samples_by_document=samples_by_document,
        redirects=redirects,
    )
