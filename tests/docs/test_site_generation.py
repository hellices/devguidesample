from __future__ import annotations

from datetime import date
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

import yaml

from scripts.docs.content import load_document
from scripts.docs.generate_indexes import build_index_pages
from scripts.docs.hooks import on_page_markdown


def test_generated_indexes_include_each_document_once() -> None:
    taxonomy = {
        "collections": {
            "guide": {
                "path": "guides",
                "title": "일반 가이드",
                "description": "지속 갱신형 절차",
            },
            "case": {
                "path": "cases",
                "title": "문제 해결 사례",
                "description": "시점 고정 이력",
            },
        },
        "services": {
            "aks": "Azure Kubernetes Service",
            "azure-monitor": "Azure Monitor",
        },
    }
    documents = [
        load_document(
            Path(__file__).parent / "fixtures" / "valid-guide.md",
            docs_dir=Path(__file__).parent / "fixtures",
        ).with_metadata(
            {
                **load_document(
                    Path(__file__).parent / "fixtures" / "valid-guide.md",
                    docs_dir=Path(__file__).parent / "fixtures",
                ).metadata,
                "services": ["aks", "azure-monitor"],
            }
        )
    ]
    documents[0] = documents[0].__class__(
        path=documents[0].path,
        relative_path=PurePosixPath("guides/aks/network-diagnosis/index.md"),
        metadata=documents[0].metadata,
        body=documents[0].body,
    )

    pages = build_index_pages(documents, taxonomy)

    assert set(pages) == {
        PurePosixPath("cases/index.md"),
        PurePosixPath("guides/index.md"),
        PurePosixPath("services/index.md"),
        PurePosixPath("services/aks.md"),
        PurePosixPath("services/azure-monitor.md"),
    }
    assert pages[PurePosixPath("guides/index.md")].count("AKS 네트워크 진단") == 1
    assert "../guides/aks/network-diagnosis/index.md" in pages[
        PurePosixPath("services/aks.md")
    ]
    assert "아직 등록된 문서가 없습니다" in pages[PurePosixPath("cases/index.md")]


def test_generator_can_run_without_repository_on_python_path(tmp_path: Path) -> None:
    root = Path(__file__).parents[2]
    script = root / "scripts" / "docs" / "generate_indexes.py"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    command = (
        "import runpy; "
        f"runpy.run_path({str(script)!r}, run_name='mkdocs_gen_files_script')"
    )

    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_mkdocs_uses_generated_navigation_search_and_tags() -> None:
    root = Path(__file__).parents[2]
    config = yaml.safe_load((root / "mkdocs.yml").read_text(encoding="utf-8"))

    assert "nav" not in config
    assert config["site_url"] == "https://hellices.github.io/devguidesample/"
    plugins = config["plugins"]
    search = next(item["search"] for item in plugins if isinstance(item, dict) and "search" in item)
    assert search["lang"] == ["ko", "en"]
    assert "tags" in plugins
    assert any(isinstance(item, dict) and "gen-files" in item for item in plugins)
    assert "awesome-nav" in plugins


def test_root_navigation_has_catch_all_glob() -> None:
    root = Path(__file__).parents[2]
    navigation = yaml.safe_load((root / "docs" / ".nav.yml").read_text(encoding="utf-8"))

    assert navigation["nav"][-1] == {"glob": "*", "ignore_no_matches": True}


def test_tags_page_uses_material_listing_marker() -> None:
    root = Path(__file__).parents[2]

    assert "<!-- material/tags -->" in (root / "docs" / "tags.md").read_text(encoding="utf-8")


class Page:
    def __init__(self, metadata: dict) -> None:
        self.meta = metadata


def test_hook_renders_verification_and_official_sources() -> None:
    page = Page(
        {
            "document_type": "guide",
            "verification_status": "needs-review",
            "sources_checked_at": date(2026, 9, 12),
            "official_sources": [
                {
                    "title": "Azure Kubernetes Service documentation",
                    "url": "https://learn.microsoft.com/azure/aks/",
                }
            ],
        }
    )

    rendered = on_page_markdown("# Page\n", page, {}, None)

    assert "공식 문서 재검토 필요" in rendered
    assert "2026-09-12" in rendered
    assert "[Azure Kubernetes Service documentation](https://learn.microsoft.com/azure/aks/)" in rendered
