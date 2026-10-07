# Azure Daily Update archive design

## Goal

Publish a Korean Azure daily update archive to GitHub Pages. Every day at
09:00 Asia/Seoul, the automation researches Azure updates from the previous
calendar day, stores one report page for that date, and pushes the validated
change directly to `main`.

## Reader experience

- Add `Azure Daily Update` as a top-level navigation destination.
- Serve the archive landing page at `/azure-daily-update/`.
- Serve each report at `/azure-daily-update/YYYY-MM-DD/`, where the date is
  the researched day, not the automation execution day.
- List reports newest first on the landing page.
- Keep a page for every run date, including dates with no matching updates.
- Group each report into `AI & Apps`, `Infra`, and `Database`, followed by up
  to three spotlight items.

## Source layout

Authored reports use this layout:

```text
docs/
  azure-daily-update/
    YYYY-MM-DD/
      index.md
```

The dated page has lightweight front matter:

```yaml
title: Azure Daily Update — YYYY-MM-DD
description: YYYY-MM-DD Azure 업데이트 요약
report_date: YYYY-MM-DD
generated_at: 2026-10-08T09:00:00+09:00
```

The archive is intentionally separate from `docs/services/`. Daily reports
are time-series news summaries, not service topic packages with one of the
existing `case`, `guide`, `lab`, or `research` lifecycles.

## Generated archive index

`scripts/docs/generate_indexes.py` scans only paths matching
`docs/azure-daily-update/YYYY-MM-DD/index.md`. It validates that the directory
date and `report_date` agree, sorts entries newest first, and generates
`azure-daily-update/index.md` during the MkDocs build.

The generated landing page shows the report date, title, description, and a
direct link. The daily automation never edits a shared archive index, which
avoids a daily merge-conflict hotspot.

`docs/.nav.yml` adds the archive as a top-level destination. The contributing
contract and navigation tests are updated because the repository currently
defines exactly four top-level destinations.

## Automation flow

The existing `Azure 전일 업데이트 브리핑` automation keeps its 09:00 daily
schedule and gains a publishing workflow:

1. Resolve the previous calendar day in `Asia/Seoul`.
2. Fetch the latest `origin/main`.
3. Work from a temporary detached worktree based on that commit so the
   automation does not depend on the branch checked out in the target
   workspace.
4. Research the matching Azure Updates entries.
5. Verify Microsoft and Azure claims with the repository
   `verify-with-microsoft-learn` skill and official Microsoft sources.
6. Create or replace
   `docs/azure-daily-update/YYYY-MM-DD/index.md`.
7. Run the complete documentation validation contract.
8. Commit only the dated report, with the required Copilot co-author trailer.
9. Push with `git push origin HEAD:main`.
10. Remove the temporary worktree.

The push is never forced. If a concurrent update advances `main`, the
automation fetches the new tip, rebases once, reruns the complete validation
contract, and retries the normal push. A conflict or second rejection stops
publication and is reported as a failure.

Rerunning the automation for a date updates the existing date page. If the
rendered report is unchanged, the run exits as a successful no-op without an
empty commit.

## Report content contract

Each page contains:

1. Research window and category counts.
2. A complete category list for `AI & Apps`, `Infra`, and `Database`.
3. For each update: title, service, release state, concise change summary,
   known scope or region, and Azure Updates URL.
4. Two or three spotlight analyses selected by impact, novelty, scope,
   operational relevance, and migration, cost, or security consequences.
5. Availability, prerequisites, limitations, adoption considerations, and
   concrete next steps for each spotlight.
6. Official source links with publication or last-updated dates.

Unverified facts are marked `확인 필요`. Preview and general availability
states are never conflated. Source access failures and ambiguous publication
dates are reported explicitly rather than converted into success-shaped
summaries.

## Failure behavior

- Research, source verification, rendering, validation, commit, and push
  failures stop publication.
- Failed runs do not modify `main`.
- The automation response names the failed stage and preserves enough command
  output to diagnose it without exposing credentials or local identifiers.
- Temporary worktrees are cleaned up after both success and failure.
- An empty update day still produces a dated report stating
  `업데이트 없음`; it is not treated as a failure.

## Validation

Add focused tests for:

- scanning only valid dated report paths;
- rejecting a directory date and `report_date` mismatch;
- newest-first archive ordering;
- one archive card per date;
- top-level `Azure Daily Update` navigation;
- successful strict rendering of the landing and dated pages.

Before the bootstrap change is pushed to `main`, run:

```text
python -m pytest tests/docs -q
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
python scripts/docs/audit_pre_pages.py
```

The daily automation runs the same commands before every direct push.
