from datetime import date
from html.parser import HTMLParser
import json
from pathlib import Path

from markdown import Markdown
import pytest
import yaml

from scripts.docs import daily_updates
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
    body: str = "",
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
        + f"# {metadata['title']}\n\n{body}\n",
        encoding="utf-8",
    )


class ArchiveMarkup(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        body = source.split("---", 2)[2] if source.startswith("---") else source
        self.feed(Markdown(extensions=["md_in_html"]).convert(body))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, dict(attrs)))

    def select(self, attribute: str) -> list[dict[str, str | None]]:
        return [attrs for _, attrs in self.elements if attribute in attrs]


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


def test_load_daily_update_reports_rejects_impossible_directory_date(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    write_report(docs, "2026-02-30")

    with pytest.raises(
        DocumentFormatError,
        match=(
            r"azure-daily-update/2026-02-30/index\.md: "
            r"directory must be a valid ISO calendar date"
        ),
    ):
        load_daily_update_reports(docs)


def test_build_daily_update_index_lists_each_date_once_newest_first(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    write_report(docs, "2026-10-06")
    write_report(docs, "2026-10-07")

    page = build_daily_update_index(docs)

    assert [
        item["data-daily-recent"]
        for item in ArchiveMarkup(page).select("data-daily-recent")
    ] == ["2026-10-07", "2026-10-06"]
    assert "# Azure Daily Update" in page


def test_index_limits_recent_reports_to_three_available_dates(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    for day in ("2025-12-31", "2026-01-02", "2026-09-25", "2026-10-06", "2026-10-07"):
        write_report(docs, day)

    page = build_daily_update_index(docs)
    markup = ArchiveMarkup(page)

    assert [item["data-daily-recent"] for item in markup.select("data-daily-recent")] == [
        "2026-10-07", "2026-10-06", "2026-09-25",
    ]
    assert len(markup.select("data-daily-calendar")) == 1
    assert len(markup.select("data-daily-search")) == 1
    fallback = page.split("<noscript>", 1)[1].split("</noscript>", 1)[0]
    assert 'href="2025-12-31/"' in fallback
    assert 'href="2026-01-02/"' in fallback
    assert "사이트 전체 검색" in page


def test_calendar_marks_only_published_days_and_the_current_report(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    for day in ("2023-12-31", "2024-02-01", "2024-02-29", "2026-10-07"):
        write_report(docs, day)

    calendar = daily_updates.build_daily_update_calendar(
        load_daily_update_reports(docs),
        source_url="azure-daily-update/2024-02-29/",
        selected_date=date(2024, 2, 29),
    )
    markup = ArchiveMarkup(calendar)
    links = markup.select("data-daily-date")

    assert [link["data-daily-date"] for link in links] == ["2024-02-01", "2024-02-29"]
    assert links[0]["href"] == "../2024-02-01/"
    assert links[1]["aria-current"] == "page"
    assert "aria-current" not in links[0]
    assert len(markup.select("data-daily-unavailable")) == 27
    assert markup.select("data-daily-source")[0]["data-daily-source"] == "../../assets/daily-updates-calendar.json"
    assert markup.select("data-daily-month")[0]["disabled"] is None
    assert [
        attrs["value"] for tag, attrs in markup.elements if tag == "option"
    ] == ["2026-10", "2024-02", "2023-12"]
    assert 'aria-label="2024년 2월 발행 달력"' in calendar


def test_calendar_defaults_to_latest_publication_not_wall_clock(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    write_report(docs, "2024-02-29")

    markup = ArchiveMarkup(daily_updates.build_daily_update_calendar(
        load_daily_update_reports(docs), source_url="azure-daily-update/",
    ))

    assert markup.select("data-daily-calendar")[0]["data-daily-calendar"] == "2024-02"
    assert markup.select("data-daily-date")[0]["href"] == "2024-02-29/"
    assert not markup.select("aria-current")


def test_archive_data_retains_all_dates_and_body_search_text(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    write_report(docs, "2025-12-31", body="## Container networking\n\n연결 진단 절차")
    write_report(docs, "2026-10-07")

    data = json.loads(daily_updates.build_daily_update_data(docs))

    assert [report["date"] for report in data["reports"]] == ["2026-10-07", "2025-12-31"]
    assert data["reports"][1]["url"] == "2025-12-31/"
    assert "Container networking" in data["reports"][1]["text"]
    assert "연결 진단" in data["reports"][1]["text"]
    assert data["reports"][1]["description"] == "2025-12-31 Azure 업데이트 요약"


def test_calendar_data_excludes_search_fields_and_does_not_grow_with_body(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    write_report(docs, "2026-10-07", body="Short report")
    calendar = daily_updates.build_daily_update_data(docs, include_search=False)

    data = json.loads(calendar)
    assert data["reports"] == [{
        "date": "2026-10-07",
        "title": "Azure Daily Update — 2026-10-07",
        "url": "2026-10-07/",
    }]
    long_body = "Archived body text " * 10_000
    write_report(docs, "2026-10-07", body=long_body)
    assert daily_updates.build_daily_update_data(docs, include_search=False) == calendar
    assert long_body in json.loads(daily_updates.build_daily_update_data(docs))["reports"][0]["text"]


def test_search_excerpts_use_readable_markdown_text_without_changing_raw_search(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    body = (
        "## Networking updates\n\n"
        "**AKS**와 [Ubuntu](https://example.test/networking) 연결 진단\n\n"
        "| Service | Status |\n|---|---|\n| AKS | Preview |\n\n"
        "<script>hiddenScript()</script><style>.hidden {}</style>\n"
    )
    write_report(docs, "2026-10-07", body=body)
    report = json.loads(daily_updates.build_daily_update_data(docs))["reports"][0]

    assert body in report["text"]
    assert "Networking updates\n" in report["excerpt"]
    assert "AKS와 Ubuntu 연결 진단" in report["excerpt"]
    assert "Preview" in report["excerpt"]
    assert all(value not in report["excerpt"] for value in (
        "**", "##", "https://", "|", "hiddenScript", ".hidden",
    ))


def test_index_loads_full_text_only_for_search(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    write_report(docs, "2026-10-07")
    markup = ArchiveMarkup(build_daily_update_index(docs))

    assert markup.select("data-daily-calendar")[0]["data-daily-source"] == "../assets/daily-updates-calendar.json"
    assert markup.select("data-daily-search")[0]["data-daily-source"] == "../assets/daily-updates.json"


def test_archive_escapes_report_titles_in_cards_calendar_and_fallback(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    write_report(docs, "2026-10-07", title='<img src=x onerror="alert(1)"> & [news]')

    page = build_daily_update_index(docs)
    markup = ArchiveMarkup(page)

    assert not any(tag == "img" for tag, _ in markup.elements)
    assert "&lt;img" in page
    assert markup.select("data-daily-date")[0]["aria-label"] == (
        '2026-10-07 업데이트: <img src=x onerror="alert(1)"> & [news]'
    )


def test_build_daily_update_index_has_explicit_empty_state(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()

    page = build_daily_update_index(docs)

    assert "아직 게시된 일일 업데이트가 없습니다." in page
    markup = ArchiveMarkup(page)
    assert not markup.select("data-daily-calendar")
    assert any(item.get("id") == "archive" for _, item in markup.elements)
