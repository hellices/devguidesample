# Azure Daily Update Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a date-indexed Azure daily update archive on GitHub Pages and make the 09:00 Asia/Seoul automation validate and push each report directly to `main`.

**Architecture:** Authored reports live at `docs/azure-daily-update/YYYY-MM-DD/index.md`. A focused Python module validates report metadata and renders a newest-first virtual archive index during the existing MkDocs generation phase; the root navigation exposes that index as `Azure Daily Update`. The automation researches the prior KST day in a temporary worktree based on the latest `origin/main`, runs the complete docs gate, and performs a normal non-force push to `main`.

**Tech Stack:** Python 3.13, pytest, MkDocs Material, mkdocs-gen-files, mkdocs-awesome-nav, Git, Copilot agent automation

## Global Constraints

- Use the researched previous calendar day in `Asia/Seoul` as the page date.
- Keep authored pages at `docs/azure-daily-update/YYYY-MM-DD/index.md`.
- Generate `/azure-daily-update/` at build time and sort reports newest first.
- Keep the archive outside `docs/services/`; do not add a `document_type`.
- Preserve the three categories `AI & Apps`, `Infra`, and `Database`.
- Select no more than three spotlight items and do not invent enough items to fill a quota.
- Verify public Microsoft and Azure product claims with `verify-with-microsoft-learn` and official Microsoft sources.
- Run every required repository documentation validation before a direct `main` push.
- Never force-push. A concurrent `main` update permits one rebase, complete revalidation, and normal retry.
- A failed research, verification, validation, commit, or push stage must not modify `main`.
- Include `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` in every implementation commit.

## File Structure

- Create `scripts/docs/daily_updates.py`: parse dated report metadata and render the archive landing page.
- Create `tests/docs/test_daily_updates.py`: unit coverage for path filtering, metadata validation, ordering, and empty state.
- Modify `scripts/docs/generate_indexes.py`: publish the generated archive landing page through mkdocs-gen-files.
- Modify `docs/.nav.yml`: add the top-level `Azure Daily Update` destination.
- Modify `docs/contributing/index.md`: document the fifth root destination and the daily archive exception to topic packages.
- Modify `tests/docs/test_faceted_discovery.py`: update the root-navigation contract.
- Modify `tests/docs/test_reader_navigation.py`: verify the archive appears in a strict built site.
- Modify `tests/docs/test_site_pipeline.py`: verify the generated landing and authored dated page build and remain searchable.
- Update the existing `Azure 전일 업데이트 브리핑` agent automation after the bootstrap code reaches `main`.

---

### Task 1: Dated report catalog and archive renderer

**Files:**
- Create: `scripts/docs/daily_updates.py`
- Create: `tests/docs/test_daily_updates.py`

**Interfaces:**
- Consumes: `scripts.docs.content.DocumentFormatError` and `load_document(path, docs_dir=...)`.
- Produces: `DailyUpdateReport`, `load_daily_update_reports(docs_dir: Path | str) -> tuple[DailyUpdateReport, ...]`, and `build_daily_update_index(docs_dir: Path | str) -> str`.

- [ ] **Step 1: Create the isolated execution worktree**

Invoke `superpowers:using-git-worktrees`, fetch `origin/main`, and create a new implementation worktree based on the fetched commit. Cherry-pick the design and plan commits into that worktree before changing implementation files.

Expected state:

```text
git merge-base --is-ancestor origin/main HEAD
# exit 0
git status --short
# no output
```

- [ ] **Step 2: Write failing catalog and renderer tests**

Create `tests/docs/test_daily_updates.py` with these cases:

```python
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

    with pytest.raises(DocumentFormatError, match="report_date must match directory date"):
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
```

- [ ] **Step 3: Run the tests to verify RED**

Run:

```bash
python -m pytest tests/docs/test_daily_updates.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.docs.daily_updates'`.

- [ ] **Step 4: Implement the focused daily-update module**

Create `scripts/docs/daily_updates.py`:

```python
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


def _required_text(metadata: dict[str, Any], field: str, relative_path: PurePosixPath) -> str:
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
        report_date = _report_date(document.metadata.get("report_date"), relative_path)
        if report_date != directory_date:
            raise DocumentFormatError(
                f"{relative_path.as_posix()}: report_date must match directory date"
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
    return tuple(sorted(reports, key=lambda report: report.report_date, reverse=True))


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
```

- [ ] **Step 5: Run the focused tests to verify GREEN**

Run:

```bash
python -m pytest tests/docs/test_daily_updates.py -q
```

Expected: all four tests pass.

- [ ] **Step 6: Commit the catalog**

```bash
git add scripts/docs/daily_updates.py tests/docs/test_daily_updates.py
git commit -m "feat(docs): generate Azure daily update archive" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: MkDocs generation, navigation, and authoring contract

**Files:**
- Modify: `scripts/docs/generate_indexes.py`
- Modify: `docs/.nav.yml`
- Modify: `docs/contributing/index.md`
- Modify: `tests/docs/test_faceted_discovery.py`
- Modify: `tests/docs/test_reader_navigation.py`
- Modify: `tests/docs/test_site_pipeline.py`

**Interfaces:**
- Consumes: `build_daily_update_index(docs_dir)` from Task 1.
- Produces: virtual `azure-daily-update/index.md` and root navigation label `Azure Daily Update`.

- [ ] **Step 1: Add failing navigation and strict-build assertions**

Update the root navigation assertions in
`tests/docs/test_faceted_discovery.py` and `tests/docs/test_reader_navigation.py`:

```python
assert [next(iter(item)) for item in nav if "glob" not in item] == [
    "홈",
    "Azure Daily Update",
    "서비스별 보기",
    "글 찾기",
    "기여하기",
]
```

```python
assert list(home.root_links.values()) == [
    "홈",
    "Azure Daily Update",
    "서비스별 보기",
    "글 찾기",
    "기여하기",
]
assert home.navigation_links["azure-daily-update/"] == "Azure Daily Update"
```

Add an integration test to `tests/docs/test_site_pipeline.py` that creates one
dated page in the existing temporary topic repository, performs a strict
build, and asserts:

```python
archive = root / "docs" / "azure-daily-update" / "2026-10-07" / "index.md"
archive.parent.mkdir(parents=True)
archive.write_text(
    """\
---
title: Azure Daily Update — 2026-10-07
description: 2026-10-07 Azure 업데이트 요약
report_date: 2026-10-07
generated_at: 2026-10-08T09:00:00+09:00
---

# Azure Daily Update — 2026-10-07

## AI & Apps

업데이트 없음
""",
    encoding="utf-8",
)

build(load_config(str(root / "mkdocs.yml"), strict=True))

landing = (root / "site" / "azure-daily-update" / "index.html").read_text(
    encoding="utf-8"
)
dated = (
    root / "site" / "azure-daily-update" / "2026-10-07" / "index.html"
).read_text(encoding="utf-8")
assert "2026-10-07" in landing
assert "2026-10-07/" in landing
assert "업데이트 없음" in dated
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```bash
python -m pytest \
  tests/docs/test_faceted_discovery.py \
  tests/docs/test_reader_navigation.py \
  tests/docs/test_site_pipeline.py -q
```

Expected: failures show the missing `Azure Daily Update` root destination and
missing generated landing page.

- [ ] **Step 3: Wire the landing page into mkdocs-gen-files**

Add this import to `scripts/docs/generate_indexes.py`:

```python
from scripts.docs.daily_updates import build_daily_update_index
```

Add this block at the end of `write_generated_pages`, before generating the
home page:

```python
    daily_update_index = build_daily_update_index(root / "docs")
    with mkdocs_gen_files.open("azure-daily-update/index.md", "w") as generated:
        generated.write(daily_update_index)
```

- [ ] **Step 4: Add the root menu destination**

Change `docs/.nav.yml` to:

```yaml
# Root reader destinations only; service and topic branches are generated.
nav:
  - 홈: index.md
  - Azure Daily Update: azure-daily-update
  - 서비스별 보기: services
  - 글 찾기: explore
  - 기여하기: contributing
  - glob: "*"
    ignore_no_matches: true
```

- [ ] **Step 5: Document the archive exception**

In `docs/contributing/index.md`, change the root menu sentence to:

```text
대메뉴는 **홈 · Azure Daily Update · 서비스별 보기 · 글 찾기 · 기여하기**입니다.
```

Add this paragraph immediately after the menu description:

```text
`Azure Daily Update`는 자동화가 생성하는 시계열 뉴스 아카이브입니다.
일자별 원본은 `docs/azure-daily-update/YYYY-MM-DD/index.md`에 두고,
`/azure-daily-update/` 색인은 빌드가 최신순으로 생성합니다. 이 페이지들은
서비스 topic package가 아니므로 `document_type`과 taxonomy 값을 선언하지
않습니다.
```

- [ ] **Step 6: Run focused tests to verify GREEN**

Run:

```bash
python -m pytest \
  tests/docs/test_daily_updates.py \
  tests/docs/test_faceted_discovery.py \
  tests/docs/test_reader_navigation.py \
  tests/docs/test_site_pipeline.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit site integration**

```bash
git add \
  scripts/docs/generate_indexes.py \
  docs/.nav.yml \
  docs/contributing/index.md \
  tests/docs/test_faceted_discovery.py \
  tests/docs/test_reader_navigation.py \
  tests/docs/test_site_pipeline.py
git commit -m "feat(docs): expose Azure daily update menu" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Validate and publish the bootstrap change directly to main

**Files:**
- Verify all files changed in Tasks 1 and 2.
- No generated `site/` files are committed.

**Interfaces:**
- Consumes: the complete archive implementation and repository validation contract.
- Produces: a normal fast-forward update to `origin/main` that triggers `.github/workflows/pages.yml`.

- [ ] **Step 1: Run the complete repository validation contract**

Run these commands from the implementation worktree:

```bash
python -m pytest tests/docs -q
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
python scripts/docs/audit_pre_pages.py
```

Expected: every command exits 0. Preserve the reported pytest count and each
validator success line for the completion summary.

- [ ] **Step 2: Confirm generated output is not staged**

Run:

```bash
git status --short
git diff --check
```

Expected: no `site/` or generated search-index paths are tracked, and
`git diff --check` exits 0.

- [ ] **Step 3: Reconcile with the latest remote main**

Run:

```bash
git fetch origin main
git rebase origin/main
```

Expected: rebase succeeds without conflict. If commits were replayed, rerun
all eight commands from Step 1 before continuing.

- [ ] **Step 4: Push without force**

Run:

```bash
git push origin HEAD:main
```

Expected: a fast-forward update to `main`. If rejected because `main`
advanced, fetch and rebase once, rerun all eight validations, and retry the
same normal push once. Stop on a conflict or second rejection.

- [ ] **Step 5: Verify the Pages workflow started**

Run:

```bash
gh run list --workflow pages.yml --branch main --limit 1
```

Expected: the newest `Deploy documentation to Pages` run references the
pushed commit and is queued, in progress, or completed. Do not report the
site as deployed until the workflow completes successfully.

---

### Task 4: Upgrade and verify the daily publishing automation

**Files:**
- Update external automation: `Azure 전일 업데이트 브리핑`.
- Create or update at runtime:
  `docs/azure-daily-update/<previous-KST-date>/index.md`.

**Interfaces:**
- Consumes: the dated-page schema and generated archive now present on `main`.
- Produces: one validated dated report commit per KST day on `main`.

- [ ] **Step 1: Replace the automation prompt**

Use `configureAutomation` with the existing automation ID, preserving
`daily`, hour `9`, minute `0`, and `enabled: true`. The prompt must include
these exact operational requirements:

```text
매일 Asia/Seoul 오전 9시에 Azure Daily Update를 조사하고 GitHub Pages에 게시한다.

1. 조사일은 실행일의 전일 00:00~23:59 Asia/Seoul이다.
2. Azure Updates 원문에서 해당 날짜에 게시 또는 업데이트된 항목만 수집한다.
3. AI & Apps, Infra, Database로 한 번씩만 분류하고 범주별 전체 항목을 기록한다.
4. 영향도, 신규성, 범위, 실무성, 마이그레이션·비용·보안 영향으로 최대 3건을
   스포트라이트한다. 유의미한 항목이 적으면 수를 채우지 않는다.
5. verify-with-microsoft-learn 스킬을 사용하고 Microsoft Learn, 공식 제품 문서,
   Azure 블로그 원문 전체를 확인한다. 확인되지 않은 사실은 '확인 필요'로 표시한다.
6. 최신 origin/main에서 임시 detached worktree를 만들고
   docs/azure-daily-update/YYYY-MM-DD/index.md를 생성 또는 갱신한다.
7. 페이지 front matter에는 title, description, report_date, generated_at을 쓰고
   report_date와 디렉터리 날짜를 일치시킨다.
8. 업데이트가 없어도 세 범주에 '업데이트 없음'을 명시한 날짜 페이지를 남긴다.
9. 저장소 문서 검증 8개 명령을 모두 실행하며 하나라도 실패하면 커밋·푸시하지 않는다.
10. 변경이 있으면 Copilot co-author trailer를 포함해 커밋하고
    git push origin HEAD:main으로 비강제 푸시한다.
11. main이 먼저 갱신되면 한 번만 fetch/rebase하고 전체 검증 후 정상 push를 재시도한다.
    충돌, 두 번째 거절, 원문 접근 실패, 날짜 불명확은 실패로 보고하고 force push하지 않는다.
12. 성공·실패와 관계없이 임시 worktree를 정리한다. 같은 날짜 내용이 동일하면
    빈 커밋 없이 성공한 no-op으로 보고한다.
```

Retain the detailed report fields from the existing prompt: service, release
state, scope or region, previous-state difference, use cases, target
workloads, availability, SKU or version, prerequisites, limitations,
compatibility, migration, cost, security, operations, next steps, and dated
official sources.

- [ ] **Step 2: Verify the persisted automation configuration**

Run `listAutomations` and assert:

```text
name: Azure 전일 업데이트 브리핑
enabled: true
schedule.interval: daily
schedule.scheduleHour: 9
schedule.scheduleMinute: 0
prompt contains: docs/azure-daily-update/YYYY-MM-DD/index.md
prompt contains: git push origin HEAD:main
prompt contains: verify-with-microsoft-learn
```

- [ ] **Step 3: Trigger one initial run**

Use `runAutomation` for the updated automation. The run must target the
previous KST date and must not be treated as successful merely because an
agent response exists.

Expected: either a validated dated-page commit reaches `main`, or the run
reports a concrete failed stage and leaves `main` unchanged.

- [ ] **Step 4: Verify the initial publication**

On successful automation completion:

```bash
git fetch origin main
git show --stat --oneline origin/main -- \
  docs/azure-daily-update/
gh run list --workflow pages.yml --branch main --limit 1
```

Expected: the latest relevant commit changes exactly one dated report page
and the corresponding Pages workflow completes successfully. Open the Pages
URL and verify that `/azure-daily-update/` links to the new dated page.

- [ ] **Step 5: Record failure truthfully when publication cannot complete**

If authentication, source access, validation, rebase, push, or Pages
deployment fails, preserve the successful bootstrap state, report the exact
failed stage, and do not claim that the dated report was published.
