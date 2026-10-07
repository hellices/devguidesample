"""Dated Azure daily update catalog and archive page rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from pathlib import Path, PurePosixPath
import re
from typing import Any

import yaml

from scripts.docs.content import DocumentFormatError, load_document


_DATE_DIRECTORY = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class DailyUpdateReport:
    report_date: date
    title: str
    description: str
    relative_path: PurePosixPath


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
        directory_date = date.fromisoformat(directory)
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
            )
        )
    return tuple(
        sorted(reports, key=lambda report: report.report_date, reverse=True)
    )


def build_daily_update_index(docs_dir: Path | str) -> str:
    reports = load_daily_update_reports(docs_dir)
    front_matter = yaml.safe_dump(
        {
            "title": "Azure Daily Update",
            "description": "Azure 전일 업데이트를 날짜별로 확인합니다.",
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
        lines.append("아직 게시된 일일 업데이트가 없습니다.")
    for report in reports:
        target = f"{report.report_date.isoformat()}/index.md"
        lines.extend(
            [
                f"## {report.report_date.isoformat()}",
                "",
                f"### [{escape(report.title)}]({target})",
                "",
                escape(report.description),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
