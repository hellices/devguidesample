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


def summary_body(
    *,
    ai_apps: int = 1,
    infra: int = 1,
    database: int = 1,
    highlight: str = "AKS와 Azure SQL의 운영 선택지가 확대됐습니다.",
    remainder: str = "",
) -> str:
    total = ai_apps + infra + database
    return (
        f"- **AI & Apps:** {ai_apps}건\n"
        f"- **Infra:** {infra}건\n"
        f"- **Database:** {database}건\n"
        f"- **총계:** {total}건\n"
        f"- **핵심 한 줄:** {highlight}\n\n"
        f"{remainder}"
    )


def write_report(
    docs_dir: Path,
    directory_date: str,
    *,
    report_date: str | None = None,
    title: str | None = None,
    body: str | None = None,
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
        + f"# {metadata['title']}\n\n"
        + (summary_body() if body is None else body)
        + "\n",
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


def test_load_daily_update_reports_parses_multiline_safe_summary(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    body = summary_body(
        ai_apps=2,
        infra=0,
        database=1,
        highlight=(
            "Anyscale on Azure가 **GA**로 발표됐으며,\n"
            "  Linux용 SQL Server는 `sysadmin` 없이 적재할 수 있습니다."
        ),
        remainder="## AI & Apps\n\n세부 내용",
    )
    write_report(docs, "2026-10-08", body=body)

    report = load_daily_update_reports(docs)[0]

    assert report.summary == daily_updates.DailyUpdateSummary(
        ai_apps=2,
        infra=0,
        database=1,
        total=3,
        highlight=(
            "Anyscale on Azure가 GA로 발표됐으며, "
            "Linux용 SQL Server는 sysadmin 없이 적재할 수 있습니다."
        ),
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            summary_body().replace("- **Infra:** 1건\n", ""),
            "Infra must appear exactly once",
        ),
        (
            summary_body() + "\n- **Infra:** 0건\n",
            "Infra must appear exactly once",
        ),
        (
            summary_body().replace("- **Database:** 1건", "- **Database:** many"),
            "Database must start with a non-negative count followed by 건",
        ),
        (
            summary_body().replace("- **총계:** 3건", "- **총계:** 4건"),
            "총계 must equal the category count sum",
        ),
        (
            summary_body(highlight=" "),
            "핵심 한 줄 must be non-empty",
        ),
    ],
)
def test_load_daily_update_reports_rejects_invalid_summary(
    tmp_path: Path, body: str, message: str
) -> None:
    docs = tmp_path / "docs"
    write_report(docs, "2026-10-08", body=body)

    with pytest.raises(
        DocumentFormatError,
        match=rf"azure-daily-update/2026-10-08/index\.md: {message}",
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


def test_recent_cards_show_counts_and_highlight_instead_of_generic_metadata(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    write_report(
        docs,
        "2026-10-08",
        body=summary_body(
            ai_apps=2,
            infra=0,
            database=1,
            highlight="Anyscale on Azure GA와 SQL Server 최소 권한 변화",
        ),
    )

    page = build_daily_update_index(docs)
    card = page.split(
        '<article class="dg-daily-card" data-daily-recent="2026-10-08">', 1
    )[1].split("</article>", 1)[0]

    assert '<time datetime="2026-10-08">2026-10-08</time>' in card
    assert '<span class="dg-daily-total">총 3건</span>' in card
    assert (
        '<div class="dg-daily-counts" role="group" '
        'aria-label="분야별 업데이트 수">'
    ) in card
    assert '<span class="dg-daily-count">AI &amp; Apps 2</span>' in card
    assert '<span class="dg-daily-count">Infra 0</span>' in card
    assert '<span class="dg-daily-count">Database 1</span>' in card
    assert (
        '<h3 class="dg-daily-card-summary"><a href="2026-10-08/">'
        "Anyscale on Azure GA와 SQL Server 최소 권한 변화</a></h3>"
    ) in card
    assert "Azure Daily Update — 2026-10-08" not in card
    assert "2026-10-08 Azure 업데이트 요약" not in card


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
    write_report(
        docs,
        "2025-12-31",
        body=summary_body(remainder="## Container networking\n\n연결 진단 절차"),
    )
    write_report(docs, "2026-10-07")

    data = json.loads(daily_updates.build_daily_update_data(docs))

    assert [report["date"] for report in data["reports"]] == ["2026-10-07", "2025-12-31"]
    assert data["reports"][1]["url"] == "2025-12-31/"
    assert "Container networking" in data["reports"][1]["text"]
    assert "연결 진단" in data["reports"][1]["text"]
    assert data["reports"][1]["description"] == "2025-12-31 Azure 업데이트 요약"


def test_calendar_data_excludes_search_fields_and_does_not_grow_with_body(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    write_report(docs, "2026-10-07", body=summary_body(remainder="Short report"))
    calendar = daily_updates.build_daily_update_data(docs, include_search=False)

    data = json.loads(calendar)
    assert data["reports"] == [{
        "date": "2026-10-07",
        "title": "Azure Daily Update — 2026-10-07",
        "url": "2026-10-07/",
    }]
    long_body = "Archived body text " * 10_000
    write_report(docs, "2026-10-07", body=summary_body(remainder=long_body))
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
    write_report(docs, "2026-10-07", body=summary_body(remainder=body))
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
