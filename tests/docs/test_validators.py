from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from scripts.docs import validate_links, validate_metadata, validate_sources


VALID_GUIDE = """\
---
title: AKS 네트워크 진단
description: AKS 네트워크 문제를 진단하는 절차
document_type: guide
services: [aks]
technologies: [kubernetes]
tags: [networking]
status: current
verification_status: verified
sources_checked_at: 2026-09-12
official_sources:
  - title: Azure Kubernetes Service documentation
    url: https://learn.microsoft.com/azure/aks/
last_verified: 2026-09-12
review_cycle_days: 180
applies_to: [AKS 1.34+]
---

# AKS 네트워크 진단

![네트워크 흐름](images/network.png)
"""


def make_repository(tmp_path: Path) -> Path:
    taxonomy = {
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
        "services": {"aks": "Azure Kubernetes Service"},
        "technologies": {"kubernetes": "Kubernetes"},
        "tags": {"networking": "Networking"},
        "verification_statuses": ["verified", "needs-review"],
        "required_source_host": "learn.microsoft.com",
        "official_source_hosts": ["learn.microsoft.com", "kubernetes.io"],
    }
    (tmp_path / "docs-taxonomy.yml").write_text(
        yaml.safe_dump(taxonomy, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    site_config = yaml.safe_load(
        (Path(__file__).parents[2] / "mkdocs.yml").read_text(encoding="utf-8")
    )
    (tmp_path / "mkdocs.yml").write_text(
        yaml.safe_dump(
            {
                "site_name": "Validator test",
                "markdown_extensions": site_config["markdown_extensions"],
            }
        ),
        encoding="utf-8",
    )
    page = tmp_path / "docs" / "guides" / "aks" / "network-diagnosis"
    (page / "images").mkdir(parents=True)
    (page / "index.md").write_text(VALID_GUIDE, encoding="utf-8")
    (page / "images" / "network.png").write_bytes(b"png")
    return tmp_path


def test_validation_gates_accept_a_publishable_repository(tmp_path: Path) -> None:
    root = make_repository(tmp_path)

    results = (
        validate_metadata.validate_repository(root, today=date(2026, 9, 12)),
        validate_sources.validate_repository(root, today=date(2026, 9, 12)),
        validate_links.validate_repository(root),
    )

    assert all(result.document_count == 1 for result in results)
    assert all(result.errors == [] for result in results)


def test_metadata_gate_checks_markdown_below_each_collection(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    stray = root / "docs" / "guides" / "aks" / "network-diagnosis" / "topic.md"
    stray.write_text(VALID_GUIDE, encoding="utf-8")

    result = validate_metadata.validate_repository(root, today=date(2026, 9, 12))

    assert result.document_count == 2
    assert any(
        "public documents must use <collection>/<service>/<topic>/index.md" in error
        and "topic.md" in error
        for error in result.errors
    )


def test_source_and_link_gates_reject_an_unpublishable_page(
    tmp_path: Path,
) -> None:
    root = make_repository(tmp_path)
    page = root / "docs" / "guides" / "aks" / "network-diagnosis" / "index.md"
    text = (
        VALID_GUIDE.replace("2026-09-12", "2026-09-13", 1)
        .replace(
            "https://learn.microsoft.com/azure/aks/",
            "http://kubernetes.io/docs/",
        )
        .replace("![네트워크 흐름]", "![]")
    )
    page.write_text(text, encoding="utf-8")
    (page.parent / "images" / "network.png").unlink()

    source_result = validate_sources.validate_repository(
        root,
        today=date(2026, 9, 12),
    )
    link_result = validate_links.validate_repository(root)

    assert any("future" in error for error in source_result.errors)
    assert any("HTTPS" in error for error in source_result.errors)
    assert any("learn.microsoft.com" in error for error in source_result.errors)
    assert any("image alt text is required" in error for error in link_result.errors)
    assert any("target does not exist" in error for error in link_result.errors)


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        ("![][asset]\n\n[asset]: images/network.png", "image alt text is required"),
        ("![diagram][asset]\n\n[asset]: missing.png", "target does not exist: missing.png"),
        ("[guide][page]\n\n[page]: missing.md", "target does not exist: missing.md"),
        ("![missing][]\n\n[missing]: missing.png", "target does not exist: missing.png"),
        ("![missing]\n\n[missing]: missing.png", "target does not exist: missing.png"),
    ],
)
def test_reference_links_and_images_are_validated(
    tmp_path: Path, snippet: str, expected: str
) -> None:
    root = make_repository(tmp_path)
    page = root / "docs" / "guides" / "aks" / "network-diagnosis" / "index.md"
    page.write_text(VALID_GUIDE + "\n" + snippet + "\n", encoding="utf-8")

    result = validate_links.validate_repository(root)

    assert len(result.errors) == 1
    assert expected in result.errors[0]


def test_reference_links_accept_existing_targets(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    page = root / "docs" / "guides" / "aks" / "network-diagnosis" / "index.md"
    page.write_text(
        VALID_GUIDE
        + '\n![diagram][ASSET]\n\n[asset]: <images/network.png> "Diagram"\n'
        + "\n[guide][page]\n\n[page]: index.md\n",
        encoding="utf-8",
    )

    assert validate_links.validate_repository(root).errors == []


@pytest.mark.parametrize(
    "snippet",
    [
        "````markdown\n```text\n[example](missing.md)\n```\n````",
        "~~~~markdown\n~~~text\n[example](missing.md)\n~~~\n~~~~",
        "````markdown\n~~~text\n[example](missing.md)\n~~~\n````",
        "`[example](missing.md)`",
        "    [example](missing.md)",
        "<!-- [example](missing.md) -->",
    ],
)
def test_link_examples_are_ignored_without_hiding_following_links(
    tmp_path: Path, snippet: str
) -> None:
    root = make_repository(tmp_path)
    page = root / "docs" / "guides" / "aks" / "network-diagnosis" / "index.md"
    body = VALID_GUIDE + "\n" + snippet + "\n"
    page.write_text(body, encoding="utf-8")

    assert validate_links.validate_repository(root).errors == []

    page.write_text(body + "\n[real link](outside.md)\n", encoding="utf-8")
    errors = validate_links.validate_repository(root).errors

    assert len(errors) == 1
    assert "target does not exist: outside.md" in errors[0]


def test_link_gate_reports_invalid_front_matter(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    page = root / "docs" / "guides" / "aks" / "network-diagnosis" / "index.md"
    page.write_text("# Missing front matter\n", encoding="utf-8")

    result = validate_links.validate_repository(root)

    assert result.document_count == 1
    assert any("YAML front matter" in error for error in result.errors)
