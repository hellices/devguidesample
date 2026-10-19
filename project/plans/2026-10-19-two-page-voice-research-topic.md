# Two-Page Voice Research Topic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the summary-only voice-data landing page with the substantive business and policy research so the published topic contains exactly two content pages.

**Architecture:** The business and policy document becomes the required topic root. The Azure architecture and storage document remains the only child, is renumbered to `topic_order: 1`, and links back to the promoted root. The old child path is removed because it existed only on the unmerged pull-request branch.

**Tech Stack:** Markdown, YAML front matter, MkDocs Material, Python 3.13, pytest, GitHub CLI

## Global Constraints

- The topic root must remain `docs/services/microsoft-foundry/voice-data-management/index.md`.
- The Azure child URL must remain `/services/microsoft-foundry/voice-data-management/azure-storage/`.
- The unpublished business child path must not remain in the authored or built site.
- Preserve every explicit anchor from the current business document.
- Remove `topic_order` from the promoted root.
- Set the Azure child to `topic_order: 1`.
- Keep `published_at: 2026-10-17`.
- Keep `sources_checked_at: 2026-10-18`.
- Keep `verification_status: needs-review`.
- Do not merge the old summary prose into the promoted business document.
- Keep both architecture SVG previews in PR #83.
- Include `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` in every implementation commit.

## File Structure

- Replace `docs/services/microsoft-foundry/voice-data-management/index.md` with the complete current contents of `business-patterns/index.md`, adjusted for root-relative metadata and links.
- Remove `docs/services/microsoft-foundry/voice-data-management/business-patterns/index.md`.
- Modify `docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md`: child order and root link.
- Keep all files under `docs/services/microsoft-foundry/voice-data-management/images/` unchanged.
- Keep `project/specs/2026-10-19-two-page-voice-research-topic-design.md` as the governing design.

---

### Task 1: Promote the business research to the topic root

**Files:**
- Replace: `docs/services/microsoft-foundry/voice-data-management/index.md`
- Remove: `docs/services/microsoft-foundry/voice-data-management/business-patterns/index.md`
- Modify: `docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md:1-66`

**Interfaces:**
- Consumes: the complete business-document front matter, body, and explicit anchors.
- Produces: one topic root and one ordered child.

- [ ] **Step 1: Verify the current state fails the two-page acceptance probe**

Run:

```bash
../../.venv/bin/python - <<'PY'
from pathlib import Path
import yaml

topic = Path("docs/services/microsoft-foundry/voice-data-management")
root = (topic / "index.md").read_text(encoding="utf-8")
metadata = yaml.safe_load(root.split("---", 2)[1])

assert metadata["title"] == "앱 음성 서비스 기록관리 사례와 정책"
assert "topic_order" not in metadata
assert "redirect_from" not in metadata
assert not (topic / "business-patterns" / "index.md").exists()
assert "images/voice-data-lifecycle.svg" in root
assert "(azure-storage/index.md)" in root
PY
```

Expected: FAIL because the current root title is the summary title and the
business child still exists.

- [ ] **Step 2: Promote the business file**

Replace the current root with the complete business document. The promoted
front matter must contain:

```yaml
services:
- microsoft-foundry
- azure-openai
- azure-storage
- azure-architecture
official_sources:
- title: Foundry Tools for Call Center Overview
  url: https://learn.microsoft.com/azure/ai-services/speech-service/call-center-overview
- title: Data, privacy, and security for Speech to text
  url: https://learn.microsoft.com/azure/foundry/responsible-ai/speech-service/speech-to-text/data-privacy-security
- title: Learn about retention for Copilot and AI apps
  url: https://learn.microsoft.com/purview/retention-policies-copilot
document_type: research
status: current
verification_status: needs-review
sources_checked_at: 2026-10-18
title: 앱 음성 서비스 기록관리 사례와 정책
description: 실제 음성 서비스가 원음, 음성 텍스트, 요약과 업무 결과를 저장·삭제하는 방식을 비교합니다.
technologies:
- rest-api
tags:
- evaluate
- ai-agents
- storage
published_at: 2026-10-17
```

Do not carry `topic_order` into the root.

- [ ] **Step 3: Rewrite the promoted root's relative links**

Apply exactly these replacements in the promoted root:

```text
(../azure-storage/index.md)  → (azure-storage/index.md)
(../images/voice-data-lifecycle.svg) → (images/voice-data-lifecycle.svg)
```

Run:

```bash
rg -n "\\.\\./" \
  docs/services/microsoft-foundry/voice-data-management/index.md

../../.venv/bin/python - <<'PY'
from pathlib import Path

root = Path(
    "docs/services/microsoft-foundry/voice-data-management/index.md"
).read_text(encoding="utf-8")
body = root.split("---", 2)[2]
assert "business-patterns" not in body
PY
```

Expected: `rg` has no matches and the Python assertion exits 0.

- [ ] **Step 4: Remove the old child source**

The authored file must no longer exist:

```text
docs/services/microsoft-foundry/voice-data-management/business-patterns/index.md
```

Do not leave a stub Markdown file or add redirect infrastructure for this
unpublished pull-request path.

- [ ] **Step 5: Renumber and relink the Azure child**

In `azure-storage/index.md`, change:

```yaml
topic_order: 2
```

to:

```yaml
topic_order: 1
```

Change the connected-document link to:

```markdown
> - 연결 문서: [앱 음성 서비스 기록관리 사례와 정책](../index.md)
```

Do not change its shared-image links:

```text
../images/azure-voice-agent-realtime-architectures.svg
../images/azure-voice-agent-ms-reference-architecture.svg
```

- [ ] **Step 6: Verify the acceptance probe passes**

Rerun the Step 1 probe.

Expected: exit 0 with no output.

- [ ] **Step 7: Run focused topic and document gates**

Run:

```bash
../../.venv/bin/python -m pytest tests/docs/test_topics.py -q
../../.venv/bin/python scripts/docs/validate_metadata.py
../../.venv/bin/python scripts/docs/validate_sources.py
../../.venv/bin/python scripts/docs/validate_links.py
../../.venv/bin/python scripts/docs/validate_public_safety.py
../../.venv/bin/python -m mkdocs build --strict
```

Expected: every command exits 0.

- [ ] **Step 8: Verify generated root and child**

Run:

```bash
test -f site/services/microsoft-foundry/voice-data-management/index.html
test -f site/services/microsoft-foundry/voice-data-management/azure-storage/index.html
test ! -e site/services/microsoft-foundry/voice-data-management/business-patterns/index.html

rg -n "앱 음성 서비스 기록관리 사례와 정책" \
  site/services/microsoft-foundry/voice-data-management/index.html
```

Expected:

- the root contains the promoted title;
- the Azure child exists; and
- the unpublished business child path is absent.

- [ ] **Step 9: Verify stable anchors**

Run:

```bash
rg -n \
  'id="(business-use-cases|transcript-summary-quality|voice-biometric-attacks|product-storage-comparison|microsoft-record-locations|gaming-public-identity)"' \
  site/services/microsoft-foundry/voice-data-management/index.html
```

Expected: six matching explicit IDs in the promoted root.

- [ ] **Step 10: Browser-check both pages**

Open:

```text
http://127.0.0.1:8123/devguidesample/services/microsoft-foundry/voice-data-management/
http://127.0.0.1:8123/devguidesample/services/microsoft-foundry/voice-data-management/azure-storage/
```

Verify:

- the root renders the business and policy page immediately;
- the Azure link and lifecycle image load;
- the Azure page links back to the root;
- the root navigation lists only the root and Azure child; and
- desktop and 390px widths have no page overflow.

- [ ] **Step 11: Commit the two-page topic**

```bash
git add -A docs/services/microsoft-foundry/voice-data-management
git commit -m "docs(foundry): reduce voice research to two pages" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: one commit containing the root replacement, removed child source,
link rewrites, and Azure child order change.

---

### Task 2: Validate and update the pull request

**Files:**
- Verify: `docs/services/microsoft-foundry/voice-data-management/`
- Update after successful validation: pull request `hellices/devguidesample#83`

**Interfaces:**
- Consumes: the two-page topic produced by Task 1.
- Produces: a fully validated branch and a PR overview with exactly two document links.

- [ ] **Step 1: Run the complete documentation contract**

Run:

```bash
../../.venv/bin/python -m pytest tests/docs -q
../../.venv/bin/python scripts/docs/validate_metadata.py
../../.venv/bin/python scripts/docs/validate_sources.py
../../.venv/bin/python scripts/docs/validate_links.py
../../.venv/bin/python scripts/docs/validate_public_safety.py
../../.venv/bin/python -m mkdocs build --strict
../../.venv/bin/python scripts/docs/validate_search_index.py
../../.venv/bin/python scripts/docs/audit_pre_pages.py
```

Expected:

```text
1928 passed
Validated metadata for 79 public documents.
Validated official sources for 79 public documents.
Validated links for 79 public documents.
Documentation built
Validated search coverage for 79 public documents and 13 tags.
```

Use the actual test and public-text-file counts if repository discovery changes
them; require zero failures.

- [ ] **Step 2: Review the branch diff**

Run:

```bash
git diff --check origin/main...HEAD
git status --short
git --no-pager diff --name-status origin/main...HEAD
```

Expected:

- no whitespace errors;
- a clean worktree;
- no authored `business-patterns/index.md`;
- one promoted root, one Azure child, three topic SVG assets, and project
  design/plan files; and
- no unrelated files.

- [ ] **Step 3: Inspect unresolved PR threads**

Query PR 83 review threads. Reply to actionable feedback in the inline thread
and resolve only addressed or evidenced partial-diff false positives.

Expected: unresolved review thread count is 0 before push.

- [ ] **Step 4: Update the PR body**

The review table must contain exactly:

```markdown
| Document | Review link |
|---|---|
| 앱 음성 서비스 기록관리 사례와 정책 | [Open business patterns](https://github.com/hellices/devguidesample/blob/docs/voice-data-research-2026-10-17/docs/services/microsoft-foundry/voice-data-management/index.md) |
| Microsoft 공식 문서로 본 Azure 음성 에이전트 데이터 저장 | [Open Azure storage research](https://github.com/hellices/devguidesample/blob/docs/voice-data-research-2026-10-17/docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md) |
```

Remove the obsolete overview row and the old direct business-child link. Keep
both SVG previews and add this summary bullet:

```markdown
- collapse the summary-only landing page into the business and policy topic root, leaving two substantive pages
```

- [ ] **Step 5: Push and wait for CI**

Run:

```bash
git fetch origin docs/voice-data-research-2026-10-17
git rev-list --left-right --count \
  HEAD...origin/docs/voice-data-research-2026-10-17
git push origin HEAD
```

Expected before push: zero incoming commits.

Wait for the new PR workflow run and require `completed success`. If a
long-running `gh` watch request times out while the run remains in progress,
use bounded REST status polling.

- [ ] **Step 6: Confirm final state**

Run:

```bash
git fetch origin docs/voice-data-research-2026-10-17
git status --short
git rev-list --left-right --count \
  HEAD...origin/docs/voice-data-research-2026-10-17
GH_PAGER=cat gh pr checks 83
```

Expected:

```text
# status: no output
0  0
validate  pass
```

Requery unresolved review threads and require a final count of `0`.
