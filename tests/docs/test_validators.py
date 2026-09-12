from __future__ import annotations

from datetime import date
from pathlib import Path

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
