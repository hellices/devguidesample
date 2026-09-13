"""Topic-package catalog for canonical documentation layouts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping

import yaml

from scripts.docs.content import Document, DocumentFormatError, KEBAB_CASE, load_document


LEGACY_COLLECTIONS = frozenset(("cases", "guides", "labs", "research"))


@dataclass(frozen=True)
class PublishedAsset:
    """Validated docs-relative source and virtual destination paths."""

    source: PurePosixPath
    target: PurePosixPath


@dataclass(frozen=True)
class SampleAsset:
    slug: str
    title: str
    description: str
    kind: str
    relative_path: PurePosixPath
    used_by: tuple[PurePosixPath, ...]
    publish: tuple[PublishedAsset, ...] = ()


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
    published_assets: dict[PurePosixPath, PublishedAsset]


def _is_canonical_document_path(relative_path: PurePosixPath) -> bool:
    parts = relative_path.parts
    return (
        len(parts) in {4, 5}
        and parts[0] == "services"
        and parts[-1] == "index.md"
        and "samples" not in parts
        and all(KEBAB_CASE.fullmatch(part) for part in parts[1:-1])
    )


def iter_topic_documents(
    docs_dir: Path | str, taxonomy: Mapping[str, Any]
) -> Iterable[Document]:
    root = Path(docs_dir)
    candidates: list[Path] = []

    services_root = root / "services"
    if services_root.is_dir():
        for path in services_root.rglob("index.md"):
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if _is_canonical_document_path(relative):
                candidates.append(path)

    for path in sorted(candidates, key=lambda item: item.relative_to(root).as_posix()):
        yield load_document(path, docs_dir=root)


def _topic_key(relative_path: PurePosixPath) -> tuple[str, str]:
    return (relative_path.parts[1], relative_path.parts[2])


def _sample_directory_errors(
    docs_root: Path, document_paths: set[PurePosixPath]
) -> list[str]:
    services_root = docs_root / "services"
    if not services_root.is_dir():
        return []

    errors: list[str] = []
    for samples_root in sorted(services_root.rglob("samples")):
        if not samples_root.is_dir():
            continue
        relative = PurePosixPath(samples_root.relative_to(docs_root).as_posix())
        # Only the first samples boundary defines ownership; later ones are payload.
        if "samples" in relative.parts[:-1]:
            continue
        if len(relative.parts) != 4:
            errors.append(f"{relative.as_posix()}: samples must be directly below the topic")
            continue
        entry_path = relative.parent / "index.md"
        if entry_path not in document_paths:
            errors.append(f"{entry_path.as_posix()}: topic entry document is missing")
        for sample_dir in sorted(samples_root.iterdir()):
            sample_path = PurePosixPath(sample_dir.relative_to(docs_root).as_posix())
            if not sample_dir.is_dir():
                errors.append(
                    f"{sample_path.as_posix()}: sample files must belong to a sample package"
                )
                continue
            if not (sample_dir / "sample.yml").is_file():
                errors.append(f"{sample_path.as_posix()}: sample.yml is required")
            if not (sample_dir / "README.md").is_file():
                errors.append(f"{sample_path.as_posix()}: README.md is required")
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


def _published_assets(
    manifest: Mapping[str, Any],
    sample_dir: Path,
    docs_root: Path,
    document_paths: Iterable[PurePosixPath],
) -> tuple[tuple[PublishedAsset, ...], list[str]]:
    relative = PurePosixPath(sample_dir.relative_to(docs_root).as_posix())
    publish = manifest.get("publish", [])
    if not isinstance(publish, list):
        return (), [f"{relative}: publish must be a list"]

    assets: list[PublishedAsset] = []
    errors: list[str] = []
    canonical_paths = set(document_paths)
    for mapping in publish:
        if not isinstance(mapping, Mapping):
            errors.append(f"{relative}: publish entries must be mappings")
            continue
        paths: dict[str, PurePosixPath] = {}
        for field in ("source", "target"):
            raw = mapping.get(field)
            if not isinstance(raw, str) or not raw.strip():
                errors.append(f"{relative}: publish {field} must be a non-empty string")
                continue
            path = PurePosixPath(raw)
            if path.is_absolute() or PureWindowsPath(raw).drive or "\\" in raw or ".." in path.parts:
                errors.append(
                    f"{relative}: publish {field} must be a relative path without '..' or backslashes: {raw}"
                )
                continue
            paths[field] = path
        if len(paths) != 2:
            continue

        source = sample_dir / paths["source"]
        topic_root = sample_dir.parent.parent
        target = topic_root / paths["target"]
        escaped = False
        for field, path, boundary in (
            ("source", source, sample_dir),
            ("target", target, topic_root),
        ):
            if not path.resolve().is_relative_to(boundary.resolve()):
                errors.append(f"{relative}: publish {field} must stay within {boundary.name}: {paths[field]}")
                escaped = True
        if escaped:
            continue
        if not source.is_file():
            errors.append(f"{relative}: publish source must be an existing file: {paths['source']}")
            continue
        target_relative = relative.parent.parent / paths["target"]
        if "samples" in paths["target"].parts:
            errors.append(f"{relative}: publish target must not be under samples: {paths['target']}")
            continue
        document_target = (
            target_relative.with_suffix(".md")
            if target_relative.suffix == ".html"
            else target_relative
        )
        if document_target in canonical_paths:
            errors.append(f"{relative}: publish target collides with a canonical document: {target_relative}")
            continue
        if target.exists() or target.is_symlink():
            errors.append(f"{relative}: publish target already exists: {target_relative}")
            continue
        assets.append(PublishedAsset(source=relative / paths["source"], target=target_relative))
    return tuple(assets), errors


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

    publish, publish_errors = _published_assets(
        manifest, sample_dir, docs_root, slug_to_document.values()
    )
    errors.extend(publish_errors)
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
            publish=publish,
        ),
        [],
    )


def build_topic_catalog(
    docs_dir: Path | str,
    taxonomy: Mapping[str, Any],
    documents: Iterable[Document] | None = None,
) -> TopicCatalog:
    root = Path(docs_dir)
    if documents is None:
        documents = iter_topic_documents(root, taxonomy)
    ordered_documents = tuple(
        sorted(
            (
                document
                for document in documents
                if _is_canonical_document_path(document.relative_path)
            ),
            key=lambda document: document.relative_path.as_posix(),
        )
    )
    canonical_paths = {document.relative_path for document in ordered_documents}
    errors = _sample_directory_errors(root, canonical_paths)

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

    grouped: dict[tuple[str, str], list[Document]] = {}
    for document in ordered_documents:
        grouped.setdefault(_topic_key(document.relative_path), []).append(document)

    topics: dict[tuple[str, str], Topic] = {}
    by_document: dict[PurePosixPath, Topic] = {}
    position_by_document: dict[PurePosixPath, int] = {}
    samples_by_document: dict[PurePosixPath, tuple[SampleAsset, ...]] = {}
    published_assets: dict[PurePosixPath, PublishedAsset] = {}

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
            if member.relative_path.parts[3] == "index":
                errors.append(
                    f"{member.relative_path.as_posix()}: child slug 'index' is reserved for the topic entry"
                )
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
                    for asset in sample.publish:
                        if asset.target in published_assets:
                            errors.append(
                                f"{sample.relative_path}: publish target is already owned: {asset.target}"
                            )
                        else:
                            published_assets[asset.target] = asset

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
        published_assets=published_assets,
    )
