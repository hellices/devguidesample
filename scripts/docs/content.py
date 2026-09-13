"""Shared content model for public documentation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import yaml


KEBAB_CASE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMMON_REQUIRED_FIELDS = (
    "title",
    "description",
    "document_type",
    "services",
    "technologies",
    "tags",
    "status",
    "verification_status",
    "sources_checked_at",
    "official_sources",
)


class DocumentFormatError(ValueError):
    """Raised when a Markdown file cannot be parsed as a public document."""


@dataclass(frozen=True)
class ValidationResult:
    document_count: int
    errors: list[str]


@dataclass(frozen=True)
class Document:
    path: Path
    relative_path: PurePosixPath
    metadata: dict[str, Any]
    body: str

    def with_metadata(self, metadata: Mapping[str, Any]) -> "Document":
        return replace(self, metadata=dict(metadata))


SERIES_ROLES = frozenset(("overview", "chapter"))


@dataclass(frozen=True)
class DocumentSeries:
    slug: str
    title: str
    description: str
    overview: Document
    members: tuple[Document, ...]


@dataclass(frozen=True)
class SeriesCatalog:
    by_slug: dict[str, DocumentSeries]
    by_document: dict[PurePosixPath, DocumentSeries]
    positions: dict[PurePosixPath, int]


def load_taxonomy(path: Path | str) -> dict[str, Any]:
    """Load the declarative documentation taxonomy."""
    source = Path(path)
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DocumentFormatError(f"{source}: taxonomy must be a YAML mapping")
    return data


def _infer_docs_dir(path: Path) -> Path:
    for parent in (path.parent, *path.parents):
        if parent.name == "docs":
            return parent
    raise DocumentFormatError(f"{path}: cannot infer docs directory")


def load_document(path: Path | str, docs_dir: Path | str | None = None) -> Document:
    """Parse YAML front matter and Markdown body from a public page."""
    source = Path(path)
    text = source.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise DocumentFormatError(f"{source}: missing YAML front matter")

    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as error:
        raise DocumentFormatError(f"{source}: unterminated YAML front matter") from error

    raw_metadata = "\n".join(lines[1:end])
    try:
        metadata = yaml.safe_load(raw_metadata)
    except yaml.YAMLError as error:
        raise DocumentFormatError(f"{source}: invalid YAML front matter: {error}") from error
    if not isinstance(metadata, dict):
        raise DocumentFormatError(f"{source}: YAML front matter must be a mapping")

    base = Path(docs_dir) if docs_dir is not None else _infer_docs_dir(source)
    try:
        relative = source.resolve().relative_to(base.resolve())
    except ValueError as error:
        raise DocumentFormatError(f"{source}: document is outside {base}") from error

    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return Document(source, PurePosixPath(relative.as_posix()), metadata, body)


def iter_public_documents(
    docs_dir: Path | str, taxonomy: Mapping[str, Any]
) -> Iterable[Document]:
    """Yield page-bundle documents from configured public collections."""
    root = Path(docs_dir)
    collection_paths = sorted(
        {
            config["path"]
            for config in taxonomy.get("collections", {}).values()
            if isinstance(config, Mapping) and isinstance(config.get("path"), str)
        }
    )
    for collection_path in collection_paths:
        collection_root = root / collection_path
        if not collection_root.is_dir():
            continue
        for path in sorted(collection_root.rglob("index.md")):
            relative = path.relative_to(root)
            if len(relative.parts) == 4:
                yield load_document(path, docs_dir=root)


def _is_date(value: Any) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)


def _validate_string_list(
    metadata: Mapping[str, Any],
    field: str,
    vocabulary: Mapping[str, Any],
    noun: str,
    errors: list[str],
) -> None:
    values = metadata.get(field)
    if not isinstance(values, list) or not values or not all(isinstance(item, str) for item in values):
        errors.append(f"{field} must be a non-empty list of strings")
        return
    for value in values:
        if not KEBAB_CASE.fullmatch(value):
            errors.append(f"{noun} must be kebab-case: {value}")
        if value not in vocabulary:
            errors.append(f"unknown {noun}: {value}")


def _append_source_errors(
    metadata: Mapping[str, Any], taxonomy: Mapping[str, Any], errors: list[str]
) -> None:
    sources = metadata.get("official_sources")
    if not isinstance(sources, list) or not sources:
        errors.append("official_sources must be a non-empty list")
        return

    allowed_hosts = set(taxonomy.get("official_source_hosts", []))
    required_host = taxonomy.get("required_source_host")
    seen_hosts: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, Mapping):
            errors.append(f"official_sources[{index}] must be a mapping")
            continue
        title = source.get("title")
        url = source.get("url")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"official_sources[{index}].title must be a non-empty string")
        if not isinstance(url, str) or not url.strip():
            errors.append(f"official_sources[{index}].url must be a non-empty string")
            continue
        try:
            parsed = urlparse(url)
        except ValueError as error:
            errors.append(f"official_sources[{index}].url is invalid: {error}")
            continue
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            errors.append(f"official source URL must use HTTPS: {url}")
        if not host:
            errors.append(f"official source URL must have a host: {url}")
            continue
        seen_hosts.add(host)
        if allowed_hosts and host not in allowed_hosts:
            errors.append(f"official source host is not allowed: {host}")

    if required_host and required_host not in seen_hosts:
        errors.append(f"at least one official source must use {required_host}")


def _series_metadata_errors(
    metadata: Mapping[str, Any], taxonomy: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    slug = metadata.get("series")
    has_order = "series_order" in metadata
    has_role = "series_role" in metadata
    if slug is None:
        if has_order:
            errors.append("series_order requires series")
        if has_role:
            errors.append("series_role requires series")
        return errors
    if not isinstance(slug, str) or not KEBAB_CASE.fullmatch(slug):
        errors.append("series must be a kebab-case string")
    elif slug not in taxonomy.get("series", {}):
        errors.append(f"unknown series: {slug}")
    order = metadata.get("series_order")
    if isinstance(order, bool) or not isinstance(order, int) or order < 0:
        errors.append("series_order must be a non-negative integer")
    role = metadata.get("series_role")
    if role not in SERIES_ROLES:
        errors.append("series_role must be overview or chapter")
    return errors


def series_validation_errors(
    documents: Iterable[Document], taxonomy: Mapping[str, Any]
) -> list[str]:
    definitions = taxonomy.get("series", {})
    grouped: dict[str, list[Document]] = {}
    for document in documents:
        if _series_metadata_errors(document.metadata, taxonomy):
            continue
        slug = document.metadata.get("series")
        if isinstance(slug, str):
            grouped.setdefault(slug, []).append(document)

    errors: list[str] = []
    for slug, members in grouped.items():
        ordered = tuple(sorted(members, key=lambda item: item.metadata["series_order"]))
        anchor = ordered[0].relative_path.as_posix()
        definition = definitions.get(slug)
        if not isinstance(definition, Mapping):
            errors.append(f"{anchor}: series definition {slug} must be a mapping")
        else:
            for field in ("title", "description"):
                value = definition.get(field)
                if not isinstance(value, str) or not value.strip():
                    errors.append(
                        f"{anchor}: series definition {slug}.{field} must be a non-empty string"
                    )

        orders: dict[int, list[Document]] = {}
        for member in members:
            orders.setdefault(member.metadata["series_order"], []).append(member)
        for order, duplicates in sorted(orders.items()):
            if len(duplicates) > 1:
                paths = sorted(
                    item.relative_path.as_posix()
                    for item in duplicates
                )
                errors.append(
                    f"{paths[0]}: duplicate series_order {order} for series {slug}: {', '.join(paths)}"
                )

        actual_orders = [member.metadata["series_order"] for member in ordered]
        expected_orders = list(range(len(ordered)))
        if actual_orders != expected_orders:
            errors.append(
                f"{anchor}: series {slug} orders must be contiguous from 0: {actual_orders}"
            )

        overviews = [
            member
            for member in ordered
            if member.metadata.get("series_role") == "overview"
        ]
        if len(overviews) != 1:
            errors.append(f"{anchor}: series {slug} must contain exactly one overview")
        if ordered and ordered[0].metadata.get("series_role") != "overview":
            errors.append(f"{anchor}: series {slug} overview must use series_order 0")
        for member in ordered[1:]:
            if member.metadata.get("series_role") != "chapter":
                errors.append(
                    f"{member.relative_path.as_posix()}: series {slug} members after order 0 must use chapter role"
                )

    return errors


def validate_source_metadata(
    metadata: Mapping[str, Any],
    taxonomy: Mapping[str, Any],
    today: date | None = None,
) -> list[str]:
    """Validate official-source evidence without validating other page fields."""
    current_date = today or date.today()
    errors: list[str] = []
    if "sources_checked_at" not in metadata:
        errors.append("missing required field: sources_checked_at")
    if "official_sources" not in metadata:
        errors.append("missing required field: official_sources")

    checked_at = metadata.get("sources_checked_at")
    if "sources_checked_at" in metadata:
        if not _is_date(checked_at):
            errors.append("sources_checked_at must be a date")
        elif checked_at > current_date:
            errors.append("sources_checked_at cannot be in the future")

    _append_source_errors(metadata, taxonomy, errors)
    return errors


def validate_document(
    document: Document,
    taxonomy: Mapping[str, Any],
    today: date | None = None,
) -> list[str]:
    """Return every content-contract violation for one public document."""
    current_date = today or date.today()
    metadata = document.metadata
    errors: list[str] = []

    for field in COMMON_REQUIRED_FIELDS:
        if field not in metadata:
            errors.append(f"missing required field: {field}")

    for field in ("title", "description", "document_type", "status", "verification_status"):
        if field in metadata and (
            not isinstance(metadata[field], str) or not metadata[field].strip()
        ):
            errors.append(f"{field} must be a non-empty string")

    collections = taxonomy.get("collections", {})
    document_type = metadata.get("document_type")
    collection = (
        collections.get(document_type)
        if isinstance(collections, Mapping) and isinstance(document_type, str)
        else None
    )
    parts = document.relative_path.parts
    if len(parts) != 4 or parts[-1] != "index.md" or not KEBAB_CASE.fullmatch(parts[2]):
        errors.append("public documents must use <collection>/<service>/<topic>/index.md")

    if not isinstance(collection, Mapping):
        if isinstance(document_type, str):
            errors.append(f"unknown document_type: {document_type}")
    else:
        expected_folder = collection.get("path")
        if parts and parts[0] != expected_folder:
            errors.append(
                f"folder '{parts[0]}' does not match {document_type} collection '{expected_folder}'"
            )
        status = metadata.get("status")
        if isinstance(status, str) and status not in collection.get("statuses", []):
            errors.append(f"invalid {document_type} status: {status}")
        for field in collection.get("required_fields", []):
            if field not in metadata:
                errors.append(f"missing required field for {document_type}: {field}")
            elif field != "last_verified":
                value = metadata[field]
                if (
                    value is None
                    or value == []
                    or (isinstance(value, str) and not value.strip())
                ):
                    errors.append(
                        f"required field for {document_type} must not be empty: {field}"
                    )

    services = taxonomy.get("services", {})
    technologies = taxonomy.get("technologies", {})
    tags = taxonomy.get("tags", {})
    _validate_string_list(metadata, "services", services, "service", errors)
    _validate_string_list(metadata, "technologies", technologies, "technology", errors)
    _validate_string_list(metadata, "tags", tags, "tag", errors)

    if len(parts) >= 2 and isinstance(metadata.get("services"), list):
        service_folder = parts[1]
        if not KEBAB_CASE.fullmatch(service_folder):
            errors.append(f"service folder must be kebab-case: {service_folder}")
        if service_folder not in metadata["services"]:
            errors.append(f"service folder must appear in services: {service_folder}")

    verification_status = metadata.get("verification_status")
    if isinstance(verification_status, str) and verification_status not in taxonomy.get(
        "verification_statuses", []
    ):
        errors.append(f"invalid verification_status: {verification_status}")

    errors.extend(validate_source_metadata(metadata, taxonomy, today=current_date))

    last_verified = metadata.get("last_verified")
    if last_verified is not None and not _is_date(last_verified):
        errors.append("last_verified must be a date or null")
    if verification_status == "verified" and document_type in ("guide", "lab"):
        if not _is_date(last_verified):
            errors.append("last_verified must be a date when verification_status is verified")
    if _is_date(last_verified) and last_verified > current_date:
        errors.append("last_verified cannot be in the future")

    review_cycle = metadata.get("review_cycle_days")
    if review_cycle is not None and (
        isinstance(review_cycle, bool)
        or not isinstance(review_cycle, int)
        or review_cycle <= 0
    ):
        errors.append("review_cycle_days must be a positive integer")

    for date_field in ("occurred_at", "resolved_at", "published_at"):
        value = metadata.get(date_field)
        if date_field in metadata and not _is_date(value):
            errors.append(f"{date_field} must be a date")

    for list_field in ("applies_to", "related_cases", "related_guides"):
        value = metadata.get(list_field)
        if value is not None and (
            not isinstance(value, list) or not all(isinstance(item, str) for item in value)
        ):
            errors.append(f"{list_field} must be a list of strings")

    cleanup_required = metadata.get("cleanup_required")
    if cleanup_required is not None and not isinstance(cleanup_required, bool):
        errors.append("cleanup_required must be a boolean")

    if "featured" in metadata and not isinstance(metadata["featured"], bool):
        errors.append("featured must be a boolean")

    errors.extend(_series_metadata_errors(metadata, taxonomy))

    return errors


def build_series_catalog(
    documents: Iterable[Document], taxonomy: Mapping[str, Any]
) -> SeriesCatalog:
    docs = tuple(documents)
    errors = [
        f"{document.relative_path}: {message}"
        for document in docs
        for message in _series_metadata_errors(document.metadata, taxonomy)
    ]
    errors.extend(series_validation_errors(docs, taxonomy))
    if errors:
        raise DocumentFormatError(
            "invalid series metadata:\n" + "\n".join(errors)
        )

    grouped: dict[str, list[Document]] = {}
    for document in docs:
        slug = document.metadata.get("series")
        if isinstance(slug, str):
            grouped.setdefault(slug, []).append(document)

    by_slug: dict[str, DocumentSeries] = {}
    by_document: dict[PurePosixPath, DocumentSeries] = {}
    positions: dict[PurePosixPath, int] = {}
    definitions = taxonomy.get("series", {})
    for slug, members in grouped.items():
        ordered = tuple(
            sorted(members, key=lambda item: item.metadata["series_order"])
        )
        definition = definitions[slug]
        series = DocumentSeries(
            slug=slug,
            title=definition["title"],
            description=definition["description"],
            overview=ordered[0],
            members=ordered,
        )
        by_slug[slug] = series
        for position, member in enumerate(ordered):
            by_document[member.relative_path] = series
            positions[member.relative_path] = position
    return SeriesCatalog(by_slug, by_document, positions)
