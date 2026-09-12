from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

from scripts.docs import validate_search_index


DOCUMENT = """\
---
title: AKS 네트워크 진단
description: AKS 네트워크 문제를 진단하는 절차
document_type: guide
services: [aks]
technologies: [kubernetes]
tags: [networking, troubleshooting]
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

네트워크 연결 문제를 확인합니다. Azure Kubernetes Service diagnostic workflow를 설명합니다.
"""


def make_repository(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    taxonomy = {
        "collections": {"guide": {"path": "guides"}},
        "services": {"aks": "Azure Kubernetes Service"},
        "technologies": {"kubernetes": "Kubernetes"},
        "tags": {
            "networking": "Networking",
            "troubleshooting": "Troubleshooting",
        },
    }
    (tmp_path / "docs-taxonomy.yml").write_text(
        yaml.safe_dump(taxonomy, allow_unicode=True), encoding="utf-8"
    )
    page = tmp_path / "docs" / "guides" / "aks" / "network-diagnosis"
    page.mkdir(parents=True)
    (page / "index.md").write_text(DOCUMENT, encoding="utf-8")
    (tmp_path / "site" / "search").mkdir(parents=True)
    return tmp_path


def write_index(root: Path, docs: list[dict[str, str]]) -> None:
    (root / "site" / "search" / "search_index.json").write_text(
        json.dumps({"config": {}, "docs": docs}, ensure_ascii=False), encoding="utf-8"
    )


def valid_index_docs() -> list[dict[str, str]]:
    return [
        {
            "location": "guides/aks/network-diagnosis/",
            "title": "AKS 네트워크 진단",
            "text": (
                "<p>네트워크 연결 문제를 확인합니다. "
                "Azure Kubernetes Service diagnostic workflow를 설명합니다.</p>"
            ),
        },
        {
            "location": "tags/#tag:networking",
            "title": "networking",
            "text": "AKS 네트워크 진단",
        },
        {
            "location": "tags/#tag:troubleshooting",
            "title": "troubleshooting",
            "text": "AKS 네트워크 진단",
        },
    ]


def test_search_index_contains_pages_full_text_and_tags(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    write_index(root, valid_index_docs())

    result = validate_search_index.validate_repository(root)

    assert result.document_count == 1
    assert result.tag_count == 2
    assert result.errors == []


def test_search_index_accepts_a_rendered_h1_title_at_the_expected_location(
    tmp_path: Path,
) -> None:
    root = make_repository(tmp_path)
    docs = valid_index_docs()
    docs[0]["title"] = "본문에서 렌더링된 H1"
    write_index(root, docs)

    result = validate_search_index.validate_repository(root)

    assert result.errors == []


def test_search_index_reports_missing_page_and_tag_entries(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    write_index(root, [])

    result = validate_search_index.validate_repository(root)

    assert any("page is missing" in error for error in result.errors)
    assert any("tag is missing: networking" in error for error in result.errors)


def test_search_index_requires_korean_and_english_source_text(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    docs = valid_index_docs()
    docs[0]["text"] = "<p>unrelated content</p>"
    write_index(root, docs)

    result = validate_search_index.validate_repository(root)

    assert any("Korean body text" in error for error in result.errors)
    assert any("English product phrase" in error for error in result.errors)


def test_search_index_diagnostics_are_safe_for_ascii_only_consoles(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    docs = valid_index_docs()
    docs[0]["text"] = "<p>unrelated content</p>"
    write_index(root, docs)

    result = validate_search_index.validate_repository(root)

    for error in result.errors:
        error.encode("cp1252")


def test_search_index_script_runs_outside_repository_cwd(tmp_path: Path) -> None:
    root = make_repository(tmp_path / "repository")
    write_index(root, valid_index_docs())
    script = Path(__file__).parents[2] / "scripts" / "docs" / "validate_search_index.py"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, str(script), "--repo-root", str(root)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
