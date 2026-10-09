"""Dated Azure daily update catalog and archive page rendering."""

from __future__ import annotations

from calendar import Calendar
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from markdown import Markdown
from mkdocs.utils import get_relative_url
import yaml

from scripts.docs.content import DocumentFormatError, load_document
from scripts.docs.search_text import visible_text


_DATE_DIRECTORY = re.compile(r"\d{4}-\d{2}-\d{2}")
_SUMMARY_LABELS = ("AI & Apps", "Infra", "Database", "총계", "핵심 한 줄")
_SUMMARY_ITEM = re.compile(
    r"(?m)^-\s+\*\*(AI & Apps|Infra|Database|총계|핵심 한 줄):\*\*"
    r"[ \t]*(.*(?:\n(?:[ \t]{2,}).*)*)"
)
_COUNT = re.compile(r"^(\d+)건(?:\s|$)")


@dataclass(frozen=True)
class DailyUpdateSummary:
    ai_apps: int
    infra: int
    database: int
    total: int
    highlight: str


@dataclass(frozen=True)
class DailyUpdateReport:
    report_date: date
    title: str
    description: str
    relative_path: PurePosixPath
    text: str
    summary: DailyUpdateSummary


def is_publishable_daily_update_path(relative_path: PurePosixPath | str) -> bool:
    path = PurePosixPath(relative_path)
    if path == PurePosixPath("azure-daily-update/index.md"):
        return True
    if (
        len(path.parts) != 3
        or path.parts[0] != "azure-daily-update"
        or path.parts[2] != "index.md"
        or _DATE_DIRECTORY.fullmatch(path.parts[1]) is None
    ):
        return False
    try:
        date.fromisoformat(path.parts[1])
    except ValueError:
        return False
    return True


def _required_text(
    metadata: dict[str, Any], field: str, relative_path: PurePosixPath
) -> str:
    value = metadata.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DocumentFormatError(
            f"{relative_path.as_posix()}: {field} must be a non-empty string"
        )
    return value.strip()


def _report_date(value: Any, relative_path: PurePosixPath) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise DocumentFormatError(
        f"{relative_path.as_posix()}: report_date must be an ISO calendar date"
    )


def _daily_update_summary(
    body: str, relative_path: PurePosixPath
) -> DailyUpdateSummary:
    preamble = re.split(r"(?m)^##\s+", body, maxsplit=1)[0]
    values: dict[str, list[str]] = {label: [] for label in _SUMMARY_LABELS}
    for match in _SUMMARY_ITEM.finditer(preamble):
        values[match.group(1)].append(match.group(2).strip())

    for label, matches in values.items():
        if len(matches) != 1:
            raise DocumentFormatError(
                f"{relative_path.as_posix()}: {label} must appear exactly once"
            )

    counts: dict[str, int] = {}
    for label in _SUMMARY_LABELS[:4]:
        match = _COUNT.match(values[label][0])
        if match is None:
            raise DocumentFormatError(
                f"{relative_path.as_posix()}: {label} must start with "
                "a non-negative count followed by 건"
            )
        counts[label] = int(match.group(1))

    if counts["총계"] != sum(counts[label] for label in _SUMMARY_LABELS[:3]):
        raise DocumentFormatError(
            f"{relative_path.as_posix()}: 총계 must equal the category count sum"
        )

    renderer = Markdown(extensions=["extra"])
    highlight = " ".join(
        visible_text(renderer.convert(values["핵심 한 줄"][0])).split()
    )
    if not highlight:
        raise DocumentFormatError(
            f"{relative_path.as_posix()}: 핵심 한 줄 must be non-empty"
        )
    return DailyUpdateSummary(
        ai_apps=counts["AI & Apps"],
        infra=counts["Infra"],
        database=counts["Database"],
        total=counts["총계"],
        highlight=highlight,
    )


def load_daily_update_reports(
    docs_dir: Path | str,
) -> tuple[DailyUpdateReport, ...]:
    docs_root = Path(docs_dir)
    archive_root = docs_root / "azure-daily-update"
    if not archive_root.is_dir():
        return ()

    reports: list[DailyUpdateReport] = []
    for path in sorted(archive_root.glob("*/index.md")):
        directory = path.parent.name
        if _DATE_DIRECTORY.fullmatch(directory) is None:
            continue
        relative_path = PurePosixPath(path.relative_to(docs_root).as_posix())
        document = load_document(path, docs_dir=docs_root)
        try:
            directory_date = date.fromisoformat(directory)
        except ValueError as error:
            raise DocumentFormatError(
                f"{relative_path.as_posix()}: "
                "directory must be a valid ISO calendar date"
            ) from error
        report_date = _report_date(
            document.metadata.get("report_date"), relative_path
        )
        if report_date != directory_date:
            raise DocumentFormatError(
                f"{relative_path.as_posix()}: "
                "report_date must match directory date"
            )
        reports.append(
            DailyUpdateReport(
                report_date=report_date,
                title=_required_text(document.metadata, "title", relative_path),
                description=_required_text(
                    document.metadata, "description", relative_path
                ),
                relative_path=relative_path,
                text=document.body,
                summary=_daily_update_summary(document.body, relative_path),
            )
        )
    return tuple(
        sorted(reports, key=lambda report: report.report_date, reverse=True)
    )


def build_daily_update_data(
    docs_dir: Path | str, *, include_search: bool = True
) -> str:
    renderer = Markdown(extensions=["extra", "admonition", "pymdownx.superfences"]) if include_search else None
    reports = []
    for report in load_daily_update_reports(docs_dir):
        record = {
            "date": report.report_date.isoformat(),
            "title": report.title,
            "url": f"{report.report_date.isoformat()}/",
        }
        if renderer is not None:
            excerpt = visible_text(renderer.reset().convert(report.text))
            record.update(
                description=report.description,
                text=report.text,
                excerpt="\n".join(line.strip() for line in excerpt.splitlines() if line.strip()),
            )
        reports.append(record)
    return json.dumps({"reports": reports}, ensure_ascii=False) + "\n"


def _archive_attributes(source_url: str, *, search: bool = False) -> str:
    filename = "daily-updates.json" if search else "daily-updates-calendar.json"
    source = get_relative_url(f"assets/{filename}", source_url)
    archive = get_relative_url("azure-daily-update/", source_url)
    return (
        f'data-daily-source="{escape(source, quote=True)}" '
        f'data-daily-base="{escape(archive, quote=True)}"'
    )


def build_daily_update_calendar(
    reports: tuple[DailyUpdateReport, ...],
    *,
    source_url: str,
    selected_date: date | str | None = None,
) -> str:
    if not reports:
        return '<p class="dg-daily-empty">아직 게시된 일일 업데이트가 없습니다.</p>'

    by_date = {report.report_date.isoformat(): report for report in reports}
    selected = selected_date.isoformat() if isinstance(selected_date, date) else selected_date
    if selected is not None and selected not in by_date:
        raise ValueError(f"selected daily update is not published: {selected}")
    month = (selected or reports[0].report_date.isoformat())[:7]
    year, month_number = map(int, month.split("-"))
    month_label = f"{year}년 {month_number}월"
    months = sorted({value[:7] for value in by_date}, reverse=True)
    lines = [
        f'<section class="dg-daily-calendar" data-daily-calendar="{month}" '
        f'data-daily-selected="{selected or ""}" {_archive_attributes(source_url)} '
        'aria-label="업데이트 발행 달력">',
        '<div class="dg-daily-calendar-controls">',
        '<button type="button" data-daily-prev aria-label="이전 발행 월" disabled>&lsaquo;</button>',
        '<select data-daily-month aria-label="발행 월 선택" disabled>',
    ]
    for value in months:
        option_year, option_month = map(int, value.split("-"))
        selected_attribute = " selected" if value == month else ""
        lines.append(
            f'<option value="{value}"{selected_attribute}>{option_year}년 {option_month}월</option>'
        )
    lines.extend([
        "</select>",
        '<button type="button" data-daily-next aria-label="다음 발행 월" disabled>&rsaquo;</button>',
        "</div>",
        f'<table class="dg-daily-calendar-grid" data-daily-grid aria-label="{month_label} 발행 달력">',
        "<thead><tr>",
        *[f'<th scope="col">{day}</th>' for day in ("일", "월", "화", "수", "목", "금", "토")],
        "</tr></thead>",
        "<tbody data-daily-days>",
    ])
    for week in Calendar(firstweekday=6).monthdayscalendar(year, month_number):
        lines.append("<tr>")
        for day in week:
            if day == 0:
                lines.append('<td aria-hidden="true"></td>')
                continue
            iso_date = f"{month}-{day:02d}"
            report = by_date.get(iso_date)
            if report is None:
                lines.append(
                    f'<td><span data-daily-unavailable="{iso_date}" '
                    f'aria-label="{iso_date} 자료 없음">{day}</span></td>'
                )
                continue
            href = get_relative_url(f"azure-daily-update/{iso_date}/", source_url)
            current = ' aria-current="page"' if iso_date == selected else ""
            label = escape(f"{iso_date} 업데이트: {report.title}", quote=True)
            lines.append(
                f'<td><a href="{escape(href, quote=True)}" data-daily-date="{iso_date}" '
                f'aria-label="{label}"{current}>{day}</a></td>'
            )
        lines.append("</tr>")
    count = sum(value.startswith(month) for value in by_date)
    lines.extend([
        "</tbody></table>",
        f'<p class="dg-daily-calendar-status" data-daily-status role="status">{count}일 발행</p>',
        '<p class="dg-daily-calendar-legend"><span>자료 있음</span>'
        + ("<span>현재 문서</span>" if selected else "") + "</p>",
        '<p class="dg-daily-error" data-daily-error role="alert" hidden></p>',
        "</section>",
    ])
    return "\n".join(lines)


def build_daily_update_index(docs_dir: Path | str) -> str:
    reports = load_daily_update_reports(docs_dir)
    front_matter = yaml.safe_dump(
        {
            "title": "Azure Daily Update",
            "description": "최근 Azure 업데이트를 읽고 달력과 검색으로 지난 자료를 찾습니다.",
            "hide": ["toc"],
        },
        allow_unicode=True,
        sort_keys=False,
    ).rstrip()
    lines = [
        "---",
        front_matter,
        "---",
        "",
        '<p class="dg-eyebrow">AZURE DAILY UPDATE</p>',
        "",
        "# Azure Daily Update",
        "",
        "매일 오전 9시(KST)에 전일 Azure 업데이트를 정리합니다.",
        "",
    ]
    if not reports:
        lines.append('<p id="archive">아직 게시된 일일 업데이트가 없습니다.</p>')
        return "\n".join(lines).rstrip() + "\n"

    lines.extend([
        "## 최근 업데이트",
        "",
        "자료가 있는 최신 발행일 3개를 보여줍니다. 지난 자료는 아래 달력과 검색에서 찾을 수 있습니다.",
        "",
        '<div class="dg-daily-recent">',
    ])
    for report in reports[:3]:
        iso_date = report.report_date.isoformat()
        lines.extend([
            f'<article class="dg-daily-card" data-daily-recent="{iso_date}">',
            f'<time datetime="{iso_date}">{iso_date}</time>',
            f'<h3><a href="{iso_date}/">{escape(report.title)}</a></h3>',
            f"<p>{escape(report.description)}</p>",
            "</article>",
        ])
    lines.extend([
        "</div>",
        "",
        '## 지난 업데이트 찾기 {#archive}',
        "",
        '<div class="dg-daily-archive" data-search-exclude="true">',
        build_daily_update_calendar(reports, source_url="azure-daily-update/"),
        '<section class="dg-daily-search" data-daily-search '
        f'{_archive_attributes("azure-daily-update/", search=True)} aria-label="일일 업데이트 검색">',
        '<form data-daily-form role="search">',
        '<label><span>업데이트 검색</span>',
        '<input type="search" data-daily-query placeholder="검색어 또는 YYYY-MM-DD" '
        'aria-describedby="daily-search-help" disabled></label>',
        '<button type="reset" disabled>검색 초기화</button>',
        "</form>",
        '<p id="daily-search-help">전체 기간의 제목·요약·본문을 검색합니다. '
        "상단의 사이트 전체 검색도 사용할 수 있습니다.</p>",
        '<p data-daily-search-status role="status">검색어를 입력하거나 달력에서 날짜를 선택하세요.</p>',
        '<ol data-daily-results hidden></ol>',
        '<button type="button" data-daily-more hidden>결과 더 보기</button>',
        '<p class="dg-daily-error" data-daily-error role="alert" hidden></p>',
        "</section>",
        "<noscript>",
        "<p>JavaScript가 꺼져 있어 월 이동과 아카이브 검색을 사용할 수 없습니다. "
        "아래 전체 발행일 목록에서 문서를 선택하세요.</p>",
        "<details><summary>전체 발행일 목록</summary><ul>",
    ])
    for report in reports:
        lines.append(
            f'<li><a href="{report.report_date.isoformat()}/">{escape(report.title)}</a></li>'
        )
    lines.extend(["</ul></details>", "</noscript>", "</div>"])
    return "\n".join(lines).rstrip() + "\n"
