from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import subprocess
import sys

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
    tmp_path.mkdir(parents=True, exist_ok=True)
    taxonomy = {
        "collections": {
            "guide": {
                "path": "guides",
                "statuses": ["current", "needs-review", "deprecated"],
                "required_fields": ["last_verified", "review_cycle_days", "applies_to"],
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
        yaml.safe_dump(taxonomy, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    page = tmp_path / "docs" / "guides" / "aks" / "network-diagnosis"
    (page / "images").mkdir(parents=True)
    (page / "index.md").write_text(VALID_GUIDE, encoding="utf-8")
    (page / "images" / "network.png").write_bytes(b"png")
    return tmp_path


def test_metadata_validator_accepts_valid_repository(tmp_path: Path) -> None:
    root = make_repository(tmp_path)

    result = validate_metadata.validate_repository(root, today=date(2026, 9, 12))

    assert result.document_count == 1
    assert result.errors == []


def test_metadata_validator_reports_front_matter_and_schema_errors(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    page = root / "docs" / "guides" / "aks" / "network-diagnosis" / "index.md"
    page.write_text("# Missing front matter\n", encoding="utf-8")

    result = validate_metadata.validate_repository(root, today=date(2026, 9, 12))

    assert result.document_count == 1
    assert any("missing YAML front matter" in error for error in result.errors)


def test_source_validator_requires_dated_learn_source(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    page = root / "docs" / "guides" / "aks" / "network-diagnosis" / "index.md"
    page.write_text(
        VALID_GUIDE.replace(
            "https://learn.microsoft.com/azure/aks/", "https://kubernetes.io/docs/"
        ),
        encoding="utf-8",
    )

    result = validate_sources.validate_repository(root, today=date(2026, 9, 12))

    assert any("learn.microsoft.com" in error for error in result.errors)


def test_source_validator_rejects_future_date_and_http(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    page = root / "docs" / "guides" / "aks" / "network-diagnosis" / "index.md"
    text = VALID_GUIDE.replace("2026-09-12", "2026-09-13", 1).replace(
        "https://learn.microsoft.com", "http://learn.microsoft.com"
    )
    page.write_text(text, encoding="utf-8")

    result = validate_sources.validate_repository(root, today=date(2026, 9, 12))

    assert any("future" in error for error in result.errors)
    assert any("HTTPS" in error for error in result.errors)


def test_link_validator_accepts_existing_image_with_alt_text(tmp_path: Path) -> None:
    root = make_repository(tmp_path)

    result = validate_links.validate_repository(root)

    assert result.document_count == 1
    assert result.errors == []


def test_link_validator_reports_missing_target(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    (root / "docs" / "guides" / "aks" / "network-diagnosis" / "images" / "network.png").unlink()

    result = validate_links.validate_repository(root)

    assert any("target does not exist: images/network.png" in error for error in result.errors)


def test_link_validator_requires_image_alt_text(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    page = root / "docs" / "guides" / "aks" / "network-diagnosis" / "index.md"
    page.write_text(VALID_GUIDE.replace("![네트워크 흐름]", "![]"), encoding="utf-8")

    result = validate_links.validate_repository(root)

    assert any("image alt text is required" in error for error in result.errors)


def test_link_validator_resolves_markdown_page_links(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    other = root / "docs" / "guides" / "aks" / "other" / "index.md"
    other.parent.mkdir(parents=True)
    other.write_text(VALID_GUIDE.replace("network-diagnosis", "other"), encoding="utf-8")
    (other.parent / "images").mkdir()
    (other.parent / "images" / "network.png").write_bytes(b"png")
    page = root / "docs" / "guides" / "aks" / "network-diagnosis" / "index.md"
    page.write_text(VALID_GUIDE + "\n[다른 문서](../other/index.md)\n", encoding="utf-8")

    result = validate_links.validate_repository(root)

    assert result.errors == []


def test_validator_scripts_run_directly_outside_repository_cwd(tmp_path: Path) -> None:
    root = make_repository(tmp_path / "repository")
    scripts_root = Path(__file__).parents[2] / "scripts" / "docs"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    for name in ("validate_metadata.py", "validate_sources.py", "validate_links.py"):
        completed = subprocess.run(
            [sys.executable, str(scripts_root / name), "--repo-root", str(root)],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, f"{name}: {completed.stderr}\n{completed.stdout}"
