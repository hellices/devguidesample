# Residual Voice Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining independent-review findings, make all three voice diagrams readable on a 390-pixel viewport, and obtain a clean latest-HEAD PR review.

**Architecture:** Preserve one SVG source per diagram and add a shared semantic scroll wrapper whose minimum width applies only below 760 pixels. Repair the executable plans so their probes, factual instructions, and push/review order agree with the final design, then validate the exact pushed revision locally, in CI, and through the PR reviewer.

**Tech Stack:** Markdown, SVG, MkDocs Material, CSS, Python 3.13, pytest, Playwright browser checks, GitHub CLI, GitHub GraphQL API

## Global Constraints

- Keep one source file for each SVG; do not add mobile-only diagram copies.
- Preserve every diagram link, alt text, label, and factual qualifier.
- At 760 pixels and below, use a 900-pixel diagram minimum width inside the scroll region.
- The page itself must have zero horizontal overflow at a 390-pixel viewport.
- Do not use JavaScript for diagram layout.
- Cold tier requires a general-purpose v2 account; do not assign Cold behavior to legacy Blob Storage accounts.
- Distinguish native audio input/output from a text-input/output STT/TTS path; do not classify the latter as nonmultimodal.
- Resolve PR threads only after the supporting commit is pushed and CI passes.
- Include `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` in every implementation commit.

---

### Task 1: Repair executable review contracts

**Files:**
- Modify: `project/plans/2026-10-18-voice-research-architecture-restructure.md`
- Modify: `project/plans/2026-10-19-final-voice-review.md`
- Modify: `project/plans/2026-10-19-two-page-voice-research-topic.md`
- Modify: `project/plans/2026-10-19-voice-business-evidence.md`

**Interfaces:**
- Consumes: the final factual decisions in `project/specs/2026-10-19-final-voice-review-design.md`.
- Produces: self-contained Python probes, factual instructions that match the final design, and push-before-resolution PR sequencing.

- [ ] **Step 1: Run the failing plan-contract probe**

```bash
../../.venv/bin/python - <<'PY'
from pathlib import Path

plans = Path("project/plans")
architecture = (plans / "2026-10-18-voice-research-architecture-restructure.md").read_text(encoding="utf-8")
final = (plans / "2026-10-19-final-voice-review.md").read_text(encoding="utf-8")
two_page = (plans / "2026-10-19-two-page-voice-research-topic.md").read_text(encoding="utf-8")
evidence = (plans / "2026-10-19-voice-business-evidence.md").read_text(encoding="utf-8")
final_flat = " ".join(final.split())

visible_start = evidence.index("**Step 1: Write the visible-order acceptance probe**")
visible_end = evidence.index("Expected before implementation:", visible_start)
visible_probe = evidence[visible_start:visible_end]
core_start = evidence.index("**Step 3: Verify core and appendix order**")
core_end = evidence.index("Expected: exit 0", core_start)
core_probe = evidence[core_start:core_end]

assert "import re" in visible_probe
assert "import re" in core_probe
assert "supports realtime and nonmultimodal models" not in architecture
assert "legacy Blob Storage 계정의 Cool·Cold" not in final_flat
assert "legacy Blob Storage 계정의 Cool에는 최소 보관기간이 없습니다" in final_flat
assert "Cold는 GPv2 계정에서만 지원됩니다" in final_flat

inspect = two_page.index("**Step 3: Inspect unresolved PR threads**")
push = two_page.index("**Step 5: Push and wait for CI**")
ci_check = two_page.index("GH_PAGER=cat gh pr checks 83 --watch", push)
ci_success = two_page.index('test "$ci_conclusion" = "success"', ci_check)
pr_body_update = two_page.index("Apply the prepared PR body update only now", ci_success)
resolve = two_page.index("Reply to and resolve actionable review threads", push)
assert inspect < push < ci_check < ci_success < pr_body_update < resolve
PY
```

Expected: FAIL because two probes do not import `re`, two old product claims
remain, and thread resolution is still required before push.

- [ ] **Step 2: Make both regular-expression probes self-contained**

In each heredoc that calls `re.search`, add `import re` immediately before
`from pathlib import Path`. Remove the two unused `import re` statements from
the unrelated earlier heredocs.

- [ ] **Step 3: Align the old product instructions**

Replace the architecture-plan claim with:

```markdown
| Voice Live is one managed API and supports Realtime models plus text-input/output model paths that combine STT and TTS | `https://learn.microsoft.com/azure/ai-services/speech-service/voice-live` |
```

Replace the final-plan account statement with:

```markdown
Cool 30일·Cold 90일은 **general-purpose v2(GPv2) 계정**에서 조기 삭제
과금을 계산하는 최소 보관기간입니다. legacy Blob Storage 계정의 Cool에는
최소 보관기간이 없고, Cold는 GPv2 계정에서만 지원됩니다. 이 값은 과금
기준이며 법정 보유기간이 아닙니다.
```

- [ ] **Step 4: Move review-thread resolution after push and CI**

Change Step 3 of the two-page plan to inspect and classify unresolved threads
without replying or resolving. After Step 5's successful CI requirement, add:

```markdown
Reply to and resolve actionable review threads only now, citing the pushed
commit and successful CI run. Resolve a partial-diff false positive only with
current source or built-output evidence. Requery all threads and require zero
unresolved threads before Step 6.
```

- [ ] **Step 5: Rerun the plan-contract probe**

Run the exact command from Step 1.

Expected: exit 0 with no output.

---

### Task 2: Make voice diagrams readable on mobile

**Files:**
- Modify: `docs/assets/stylesheets/extra.css`
- Modify: `docs/services/microsoft-foundry/voice-data-management/index.md`
- Modify: `docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md`

**Interfaces:**
- Consumes: the existing three linked SVG assets and MkDocs `md_in_html` support.
- Produces: `.voice-diagram-scroll`, a keyboard-focusable region that contains mobile-only horizontal overflow.

- [ ] **Step 1: Run the failing source-contract probe**

```bash
../../.venv/bin/python - <<'PY'
import re
from pathlib import Path

root = Path("docs/services/microsoft-foundry/voice-data-management/index.md").read_text(encoding="utf-8")
azure = Path("docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md").read_text(encoding="utf-8")
css = Path("docs/assets/stylesheets/extra.css").read_text(encoding="utf-8")
combined = root + azure

wrapper_tags = re.findall(r'<div class="voice-diagram-scroll"[^>]*>', combined)
assert len(wrapper_tags) == 3
wrapper_labels = []
for wrapper_tag in wrapper_tags:
    assert 'role="region"' in wrapper_tag
    assert 'tabindex="0"' in wrapper_tag
    label_match = re.search(r'aria-label="([^"]+)"', wrapper_tag)
    assert label_match
    wrapper_labels.append(label_match.group(1))
assert len(set(wrapper_labels)) == 3
assert ".md-typeset .voice-diagram-scroll" in css
assert "overflow-x: auto" in css
assert "min-width: 900px" in css
PY
```

Expected: FAIL because the wrappers and CSS do not exist.

- [ ] **Step 2: Wrap all three diagrams**

Use this structure for each of the two existing linked Azure diagrams,
retaining its link, image path, and alt text:

```markdown
<div class="voice-diagram-scroll" role="region" aria-label="<기존 대체텍스트> 도식 가로 스크롤" tabindex="0" markdown="1">
[![기존 대체텍스트](기존-svg-경로)](기존-svg-경로)
</div>
```

Wrap the unlinked lifecycle image without adding a link:

```markdown
<div class="voice-diagram-scroll" role="region" aria-label="<기존 대체텍스트> 도식 가로 스크롤" tabindex="0" markdown="1">
![기존 대체텍스트](기존-svg-경로)
</div>
```

- [ ] **Step 3: Add the shared CSS**

Add the base rules near the existing article-content styles:

```css
.md-typeset .voice-diagram-scroll {
  max-width: 100%;
  overflow-x: auto;
  overscroll-behavior-inline: contain;
}

.md-typeset .voice-diagram-scroll > p {
  margin: 0;
}

.md-typeset .voice-diagram-scroll a,
.md-typeset .voice-diagram-scroll img {
  display: block;
  width: 100%;
}
```

Inside the existing `@media (max-width: 760px)` block, add:

```css
.md-typeset .voice-diagram-scroll > p {
  min-width: 900px;
}
```

- [ ] **Step 4: Rerun the source-contract probe**

Run the exact command from Step 1.

Expected: exit 0 with no output.

- [ ] **Step 5: Build and run targeted document checks**

```bash
../../.venv/bin/python -m pytest \
  tests/docs/test_content.py \
  tests/docs/test_topics.py \
  tests/docs/test_site_pipeline.py -q
../../.venv/bin/python scripts/docs/validate_metadata.py
../../.venv/bin/python scripts/docs/validate_links.py
../../.venv/bin/python scripts/docs/validate_public_safety.py
../../.venv/bin/python -m mkdocs build --strict
```

Expected: 166 tests pass; every validator and the strict build exits 0.

---

### Task 3: Verify rendering and publish the reviewed revision

**Files:**
- Verify: `docs/services/microsoft-foundry/voice-data-management/`
- Update: pull request `hellices/devguidesample#83`

**Interfaces:**
- Consumes: Tasks 1-2 on a clean committed branch.
- Produces: browser evidence, full local validation, successful remote CI, zero unresolved threads, and a latest-HEAD review with no findings.

- [ ] **Step 1: Browser-check desktop and 390 pixels**

Start `../../.venv/bin/python -m mkdocs serve --dev-addr 127.0.0.1:8124`
through the execution harness in async mode. Record its shell ID and exact PID,
then use the bounded readiness probe already defined in the final review plan.

At a 390-pixel viewport, evaluate:

```javascript
const result = await page.evaluate(() => {
  const root = document.documentElement;
  const regions = [...document.querySelectorAll(".voice-diagram-scroll")];
  return {
    pageHasOverflow: root.scrollWidth > root.clientWidth,
    regions: regions.map((region) => ({
      clientWidth: region.clientWidth,
      scrollWidth: region.scrollWidth,
      role: region.getAttribute("role"),
      labelled: region.getAttribute("aria-label"),
      keyboardFocusable: region.getAttribute("tabindex") === "0",
    })),
  };
});
const pageLabels = result.regions.map((region) => region.labelled);
if (new Set(pageLabels).size !== pageLabels.length) {
  throw new Error("Diagram region labels must be unique per page");
}
```

Require `pageHasOverflow === false` on both pages. Collect one region from the
root and two from the Azure page; for all three require
`scrollWidth > clientWidth`, `role === "region"`, a nonempty label, and
`keyboardFocusable === true`. Require `pageLabels` to be unique on each page.
At desktop width, require each diagram to fit the content column without
forced horizontal scrolling.

- [ ] **Step 2: Run the complete documentation contract**

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

Expected: all 1,928 documentation tests and every validator pass.

- [ ] **Step 3: Commit the implementation**

```bash
git add \
  docs/assets/stylesheets/extra.css \
  docs/services/microsoft-foundry/voice-data-management/index.md \
  docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md \
  project/plans/2026-10-18-voice-research-architecture-restructure.md \
  project/plans/2026-10-19-final-voice-review.md \
  project/plans/2026-10-19-two-page-voice-research-topic.md \
  project/plans/2026-10-19-voice-business-evidence.md
git commit -m "docs(foundry): close residual voice review" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 4: Push and require successful CI**

```bash
set -euo pipefail
git fetch origin docs/voice-data-research-2026-10-17
read -r ahead incoming <<<"$(git rev-list --left-right --count \
  HEAD...origin/docs/voice-data-research-2026-10-17)"
test "$incoming" -eq 0
pushed_sha=$(git rev-parse HEAD)
git push origin docs/voice-data-research-2026-10-17

pr_head_ready=false
for attempt in {1..30}; do
  remote_head=$(gh pr view 83 --json headRefOid --jq .headRefOid)
  if test "$remote_head" = "$pushed_sha"; then
    pr_head_ready=true
    break
  fi
  sleep 2
done
test "$pr_head_ready" = true

check_run_id=
for attempt in {1..30}; do
  check_run_id=$(gh api \
    "repos/hellices/devguidesample/commits/$pushed_sha/check-runs" \
    --jq '[.check_runs[] | select(.name == "validate")][0].id // empty')
  test -n "$check_run_id" && break
  sleep 2
done
test -n "$check_run_id"

GH_PAGER=cat gh pr checks 83 --watch --interval 15
ci_conclusion=$(gh api \
  "repos/hellices/devguidesample/check-runs/$check_run_id" \
  --jq .conclusion)
test "$ci_conclusion" = "success"
```

Expected before push: zero incoming commits. Expected after push: the
`validate` check recorded for `pushed_sha` concludes with `success`.

- [ ] **Step 5: Require a clean latest-HEAD review**

Wait for a review containing:

```text
<!-- hermes-pr-review:v1:hellices/devguidesample#83@<full HEAD SHA> -->
```

If the review creates threads, record each thread ID and finding, address them,
and repeat Tasks 2-3 through the exact-SHA CI gate. Continue with Step 6 before
waiting for another latest-HEAD marker.

- [ ] **Step 6: Reply to and resolve reviewed findings**

For each actionable thread, set `thread_id` to the GraphQL thread ID returned
by the latest review query and set `reply_body` to a finding-specific message
that cites the pushed commit plus test, build, source, or CI evidence. Require
both values, reply in the inline thread, and resolve only after the supporting
commit's CI succeeds:

```bash
test -n "$thread_id"
test -n "$reply_body"
gh api graphql \
  -F threadId="$thread_id" \
  -f body="$reply_body" \
  -f query='mutation($threadId:ID!,$body:String!){
    addPullRequestReviewThreadReply(
      input:{pullRequestReviewThreadId:$threadId,body:$body}
    ){comment{id}}
    resolveReviewThread(input:{threadId:$threadId}){thread{id isResolved}}
  }'
```

After every evidenced thread is processed, requery the entire PR:

```bash
unresolved_count=$(gh api graphql \
  -F owner=hellices \
  -F name=devguidesample \
  -F number=83 \
  -f query='query($owner:String!,$name:String!,$number:Int!){
    repository(owner:$owner,name:$name){
      pullRequest(number:$number){
        reviewThreads(first:100){nodes{isResolved}}
      }
    }
  }' \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[]
    | select(.isResolved == false)] | length')
test "$unresolved_count" -eq 0
```

If fixes produced a new commit, return to Step 5 and require a marker for that
new full HEAD SHA. Completion requires the latest marker, zero new findings,
zero unresolved threads, branch divergence `0 0`, a clean worktree, passing
CI, and reviewer request `daeungo1`.
