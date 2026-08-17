# Dynamic Threshold Visual Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the official Dynamic Threshold chart durable inside the repository, verify its rendered contract, and close the current PR review feedback without adding an experiment or custom diagram.

**Architecture:** Store the unmodified Microsoft PNG under `monitor/assets/official/`, render it through a relative Markdown path, and keep the click target and attribution on the official Learn article. A focused pytest contract verifies the asset, dimensions, local reference, and source attribution. Review-thread replies explain the implemented hotlink fix and the evidence for retaining the official page title.

**Tech Stack:** Markdown, PNG, Python/pytest, Pillow, curl, GitHub CLI.

## Global Constraints

- Do not add a hands-on experiment, Bicep, workload changes, or custom diagram.
- Store the official chart at `monitor/assets/official/dynamic-threshold-preview-chart.png`.
- The local PNG must be byte-identical to the official 1000x598 image.
- Render the image from a relative path and link it to the official Microsoft Learn article.
- Keep the exact official article title `Create a Log Search alert rule with dynamic threshold`.
- Reply inside existing GitHub inline review threads.
- Remove temporary `docs/superpowers` workflow artifacts before the product commit.

---

### Task 1: Localize and Verify the Official Chart

**Files:**
- Create: `monitor/assets/official/dynamic-threshold-preview-chart.png`
- Modify: `monitor/azure-monitor-dynamic-thresholds-brief.md`
- Create: `monitor/sre-agent-event-lab/scripts/tests/test_dynamic_threshold_brief.py`
- Remove before commit: `docs/superpowers/specs/2026-08-17-dynamic-threshold-visual-review-design.md`
- Remove before commit: `docs/superpowers/plans/2026-08-17-dynamic-threshold-visual-review.md`

**Interfaces:**
- Consumes: official image URL
  `https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/media/alerts-dynamic-thresholds/threshold-picture-8bit.png`.
- Produces: a local Markdown asset at
  `assets/official/dynamic-threshold-preview-chart.png` relative to the brief.

- [ ] **Step 1: Write the failing asset contract**

Create
`monitor/sre-agent-event-lab/scripts/tests/test_dynamic_threshold_brief.py`:

```python
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).parents[4]
BRIEF = REPO_ROOT / "monitor" / "azure-monitor-dynamic-thresholds-brief.md"
ASSET = REPO_ROOT / "monitor" / "assets" / "official" / "dynamic-threshold-preview-chart.png"
ARTICLE = "https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-dynamic-thresholds"
RAW_MEDIA = (
    "https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/media/"
    "alerts-dynamic-thresholds/threshold-picture-8bit.png"
)


def test_brief_uses_the_local_official_chart():
    text = BRIEF.read_text()

    assert ASSET.is_file()
    assert "assets/official/dynamic-threshold-preview-chart.png" in text
    assert RAW_MEDIA not in text
    assert f"]({ARTICLE})" in text
    assert f"Source: [Create a Log Search alert rule with dynamic threshold]({ARTICLE})" in text


def test_official_chart_is_a_valid_1000_by_598_png():
    assert ASSET.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(ASSET) as image:
        assert image.format == "PNG"
        assert image.size == (1000, 598)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd monitor/sre-agent-event-lab
app/.venv/bin/python -m pytest \
  scripts/tests/test_dynamic_threshold_brief.py \
  -q
```

Expected: FAIL because the local asset does not exist and the brief still
contains the raw media URL.

- [ ] **Step 3: Download the official image without modification**

Run:

```bash
mkdir -p monitor/assets/official
curl -fsSL \
  https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/media/alerts-dynamic-thresholds/threshold-picture-8bit.png \
  -o monitor/assets/official/dynamic-threshold-preview-chart.png
```

Verify byte identity:

```bash
curl -fsSL \
  https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/media/alerts-dynamic-thresholds/threshold-picture-8bit.png \
  -o /tmp/dynamic-threshold-preview-chart.png
cmp monitor/assets/official/dynamic-threshold-preview-chart.png \
  /tmp/dynamic-threshold-preview-chart.png
rm /tmp/dynamic-threshold-preview-chart.png
```

Expected: `cmp` exits 0.

- [ ] **Step 4: Replace the hotlink while preserving the article target**

Replace the chart Markdown in
`monitor/azure-monitor-dynamic-thresholds-brief.md` with:

```markdown
[![Screenshot that shows a metric alert preview chart with dynamic threshold: a blue line for the measured metric, a blue shaded allowed range, and red dots marking values outside that range.](assets/official/dynamic-threshold-preview-chart.png)](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-dynamic-thresholds)
```

Keep the existing source caption unchanged.

- [ ] **Step 5: Run focused and repository documentation tests**

Run:

```bash
cd monitor/sre-agent-event-lab
app/.venv/bin/python -m pytest \
  scripts/tests/test_dynamic_threshold_brief.py \
  scripts/tests/test_privacy.py \
  scripts/tests/test_repo_readme.py \
  -q
```

Expected: all tests PASS.

- [ ] **Step 6: Remove workflow artifacts and verify final scope**

Remove both temporary design/plan files through the patch/edit workflow, then
run:

```bash
git diff --check
git status --short
```

Expected product paths:

```text
M  monitor/azure-monitor-dynamic-thresholds-brief.md
?? monitor/assets/official/dynamic-threshold-preview-chart.png
?? monitor/sre-agent-event-lab/scripts/tests/test_dynamic-threshold-brief.py
```

- [ ] **Step 7: Commit the visual review fix**

```bash
git add \
  monitor/azure-monitor-dynamic-thresholds-brief.md \
  monitor/assets/official/dynamic-threshold-preview-chart.png \
  monitor/sre-agent-event-lab/scripts/tests/test_dynamic-threshold-brief.py
git commit -m "docs(monitor): preserve official Dynamic Threshold chart" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 8: Verify rendered GitHub content after push**

After controller review and push, use browser automation to confirm:

- the image element is complete;
- natural dimensions are 1000x598;
- the rendered `currentSrc` is GitHub's local repository asset proxy;
- clicking the chart targets the official Learn article.

- [ ] **Step 9: Reply to existing review threads**

Reply to hotlink comment `3793789223`:

```text
Implemented. The official 1000×598 PNG is now stored unchanged at `monitor/assets/official/dynamic-threshold-preview-chart.png`; the Markdown renders the relative asset and the chart link/source still point to the Microsoft Learn article. A focused test verifies the PNG signature, dimensions, local reference, and attribution.
```

Reply to source-label comment `3792391823`:

```text
Verified against the current Microsoft Learn page. Its published title is `Create a Log Search alert rule with dynamic threshold`, so the source label remains exact. The same article's considerations section states that Dynamic Threshold Log Search alerts do not support one-minute evaluation; the brief also links the general Log Search alert creation article separately. No wording change was made for this item.
```

Reply to obsolete experiment comment `3793673632`:

```text
The hands-on experiment, availability test, and Dynamic Threshold Bicep rule were removed from this PR. The current PR is introduction-only, so this baseline-density comment no longer applies to the changed files.
```

Use the inline reply endpoint:

```bash
gh api \
  repos/hellices/devguidesample/pulls/54/comments/<COMMENT_ID>/replies \
  -f body='<REPLY>'
```

