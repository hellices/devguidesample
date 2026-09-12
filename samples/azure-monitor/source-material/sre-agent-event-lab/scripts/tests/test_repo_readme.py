"""Contracts for discovering the public site and its runnable SRE sample."""

from published_layout import README as LAB_PAGE, REPO_ROOT


ROOT_README = REPO_ROOT / "README.md"
SAMPLE_ROOT = "samples/azure-monitor/source-material/sre-agent-event-lab"


def test_root_readme_routes_readers_to_the_searchable_pages_site():
    text = ROOT_README.read_text(encoding="utf-8")

    assert "https://hellices.github.io/devguidesample/" in text
    assert "전체 문서 목록은 파일로 중복 관리하지 않습니다" in text


def test_public_lab_page_routes_runnable_commands_to_the_sample_tree():
    text = LAB_PAGE.read_text(encoding="utf-8")

    assert (REPO_ROOT / SAMPLE_ROOT / "azure.yaml").is_file()
    assert SAMPLE_ROOT in text
