from pathlib import Path

import pytest
import yaml

from scripts.docs.content import DocumentFormatError
from scripts.docs.daily_updates import (
    build_daily_update_index,
    load_daily_update_reports,
)


def write_report(
    docs_dir: Path,
    directory_date: str,
    *,
    report_date: str | None = None,
    title: str | None = None,
) -> None:
    path = docs_dir / "azure-daily-update" / directory_date / "index.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "title": title or f"Azure Daily Update — {directory_date}",
        "description": f"{directory_date} Azure 업데이트 요약",
        "report_date": report_date or directory_date,
        "generated_at": "2026-10-08T09:00:00+09:00",
    }
    path.write_text(
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        + "---\n\n"
        + f"# {metadata['title']}\n",
        encoding="utf-8",
    )


def test_load_daily_update_reports_ignores_non_date_paths_and_sorts_newest_first(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    write_report(docs, "2026-10-05")
    write_report(docs, "2026-10-07")
    ignored = docs / "azure-daily-update" / "draft" / "index.md"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("# Draft\n", encoding="utf-8")

    reports = load_daily_update_reports(docs)

    assert [report.report_date.isoformat() for report in reports] == [
        "2026-10-07",
        "2026-10-05",
    ]
    assert all(report.relative_path.name == "index.md" for report in reports)


def test_load_daily_update_reports_rejects_directory_metadata_mismatch(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    write_report(docs, "2026-10-07", report_date="2026-10-06")

    with pytest.raises(
        DocumentFormatError, match="report_date must match directory date"
    ):
        load_daily_update_reports(docs)


def test_build_daily_update_index_lists_each_date_once_newest_first(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    write_report(docs, "2026-10-06")
    write_report(docs, "2026-10-07")

    page = build_daily_update_index(docs)

    assert page.count("2026-10-07/index.md") == 1
    assert page.count("2026-10-06/index.md") == 1
    assert page.index("2026-10-07/index.md") < page.index("2026-10-06/index.md")
    assert "# Azure Daily Update" in page


def test_build_daily_update_index_has_explicit_empty_state(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()

    page = build_daily_update_index(docs)

    assert "아직 게시된 일일 업데이트가 없습니다." in page
