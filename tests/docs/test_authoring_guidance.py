from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_readme_introduces_public_pages_and_four_collections() -> None:
    text = read("README.md")

    assert "https://hellices.github.io/devguidesample/" in text
    assert "CONTRIBUTING.md" in text
    for label in ("문제 해결 사례", "일반 가이드", "실습", "리서치"):
        assert label in text
    assert "내부 지식 공유" not in text


def test_root_contributing_links_detailed_site_guide() -> None:
    text = read("CONTRIBUTING.md")

    assert "docs/contributing/index.md" in text
    assert "verify-with-microsoft-learn" in text


def test_agents_file_contains_executable_document_contract() -> None:
    text = read("AGENTS.md")

    assert "docs/<collection>/<service>/<topic>/index.md" in text
    assert "verify-with-microsoft-learn" in text
    for command in (
        "python scripts/docs/validate_metadata.py",
        "python scripts/docs/validate_sources.py",
        "python scripts/docs/validate_links.py",
        "python scripts/docs/validate_public_safety.py",
        "mkdocs build --strict",
        "python scripts/docs/validate_search_index.py",
    ):
        assert command in text
    assert "cases" in text and "guides" in text
    assert "samples/" in text


def test_detailed_guide_explains_automatic_inclusion_and_verification() -> None:
    text = read("docs/contributing/index.md")

    assert "자동" in text
    assert "mkdocs.yml" in text
    assert "수정하지" in text
    assert "official_sources" in text
    assert "sources_checked_at" in text
    assert "Microsoft Learn MCP" in text
    assert "validate_public_safety.py" in text
    assert "validate_search_index.py" in text
    assert "사례" in text and "가이드" in text


def test_document_templates_cover_type_specific_contracts() -> None:
    templates = {
        "case-template.md": ("document_type: case", "occurred_at", "근본 원인"),
        "guide-template.md": (
            "document_type: guide",
            "review_cycle_days",
            "롤백과 트러블슈팅",
        ),
        "lab-template.md": ("document_type: lab", "cleanup_required", "정리"),
        "research-template.md": (
            "document_type: research",
            "published_at",
            "조사 방법",
        ),
    }
    for filename, required in templates.items():
        text = read(f"docs/contributing/{filename}")
        for phrase in required:
            assert phrase in text, f"{filename} is missing {phrase}"
        for common in (
            "verification_status",
            "sources_checked_at",
            "official_sources",
            "https://learn.microsoft.com/",
        ):
            assert common in text, f"{filename} is missing {common}"
