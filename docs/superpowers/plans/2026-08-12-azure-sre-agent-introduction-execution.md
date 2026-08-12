# Azure SRE Agent Hybrid Introduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the report-first experience with a practical Azure SRE Agent introduction that explains the product, walks through an understandable incident story, and demonstrates ticket/email operational outputs.

**Architecture:** A new `monitor/azure-sre-agent.md` is the entry point and uses Microsoft Learn-hosted official images for product concepts. Existing raw event timelines feed a storyboard renderer that adds scenario, expectation, actual evidence, and outcome frames; a notification generator converts the validated S1 conclusion into a GitHub issue body and Outlook-compatible email draft.

**Tech Stack:** Markdown, Microsoft Learn images, Python 3.12, Pillow, HTML, RFC 5322 email, GitHub CLI, pytest.

## Global Constraints

- The new introduction is the primary document; the existing results document becomes a validation appendix.
- Use Microsoft Learn images by direct HTTPS URL with source attribution; do not copy or alter Microsoft screenshots.
- Distinguish `SCENARIO` explanatory frames from `ACTUAL` API-evidence frames.
- Never claim ServiceNow, PagerDuty, Outlook, or Teams were connected in this lab.
- Create one real GitHub issue in `hellices/devguidesample` with `[SRE-LAB]` prefix.
- Do not send a real email; create `.eml`, HTML, and PNG preview artifacts labeled Draft.
- Exclude tokens, callback URLs, connection strings, identity claims, and private evidence from ticket/email assets.
- Preserve the existing measured S1/S2/S3 results and known S3 limitation.

---

## File Map

| File | Responsibility |
|---|---|
| `monitor/azure-sre-agent.md` | Product introduction and primary navigation |
| `monitor/sre-agent-event-lab/scripts/render_storyboard.py` | Merge explanatory frames with selected actual evidence |
| `monitor/sre-agent-event-lab/scripts/generate_notifications.py` | Build sanitized GitHub issue body, HTML email, and `.eml` |
| `monitor/sre-agent-event-lab/scripts/tests/test_storyboard.py` | Story order, badges, dimensions, GIF tests |
| `monitor/sre-agent-event-lab/scripts/tests/test_notifications.py` | Ticket/email content, RFC headers, secret redaction tests |
| `monitor/sre-agent-event-lab/assets/storyboards/` | Commit-safe scenario storyboard frames and GIFs |
| `monitor/sre-agent-event-lab/assets/notifications/` | Commit-safe issue/email artifacts and screenshots |
| `docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md` | Validation appendix with introduction backlink |

---

### Task 1: Build the product introduction

**Files:**
- Create: `monitor/azure-sre-agent.md`
- Modify: `monitor/sre-agent-event-lab/README.md`
- Modify: `docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md`

**Interfaces:**
- Introduction links to the lab README, actual storyboard assets, GitHub issue, email preview, and validation appendix.

- [ ] **Step 1: Create a failing document contract**

Verify the new document is absent:

```bash
test ! -f monitor/azure-sre-agent.md
```

- [ ] **Step 2: Write the introduction**

Include:

- one-sentence definition;
- manual-before/agent-after comparison;
- `Detect → Investigate → Recommend/Act → Communicate → Learn`;
- hypothesis-driven RCA;
- incident platforms, built-in Azure tools, source/knowledge, connectors;
- ReadOnly/Review/Autonomous safety;
- representative HTTP 500 scenario;
- ticket/email operational output;
- S2/S3 pattern cards;
- Dynamic Threshold operating extension;
- adoption checklist and limitations.

- [ ] **Step 3: Add official images**

Embed and attribute at least:

```text
https://learn.microsoft.com/en-us/azure/sre-agent/media/root-cause-analysis/root-cause-analysis.svg
https://learn.microsoft.com/en-us/azure/sre-agent/media/tutorial-incident-response/incident-response-plans.png
https://learn.microsoft.com/en-us/azure/sre-agent/media/tutorial-incident-response/sample-app-memory-search-results.png
https://learn.microsoft.com/en-us/azure/sre-agent/media/managed-connectors/managed-connectors-icon-grid.png
https://learn.microsoft.com/en-us/azure/sre-agent/media/managed-connectors/office365-operations.png
https://learn.microsoft.com/en-us/azure/sre-agent/media/managed-connectors/office365-parameter-policy.png
```

- [ ] **Step 4: Reframe the report**

Change the report title/intro to “actual behavior validation appendix,” link to `monitor/azure-sre-agent.md`, and preserve all measured tables.

- [ ] **Step 5: Verify and commit**

```bash
for phrase in \
  "Detect" "Investigate" "Communicate" "Review" \
  "GitHub Issue" "Outlook" "ServiceNow" "PagerDuty"; do
  rg -q "$phrase" monitor/azure-sre-agent.md
done
test "$(rg -c 'learn.microsoft.com/en-us/azure/sre-agent/media/' \
  monitor/azure-sre-agent.md)" -ge 5
git diff --check
git add monitor/azure-sre-agent.md \
  monitor/sre-agent-event-lab/README.md \
  docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md
git commit -m "docs(monitor): introduce Azure SRE Agent workflows" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Render scenario-aware storyboard GIFs

**Files:**
- Create: `monitor/sre-agent-event-lab/scripts/render_storyboard.py`
- Create: `monitor/sre-agent-event-lab/scripts/tests/test_storyboard.py`
- Create: `monitor/sre-agent-event-lab/assets/storyboards/s1/`
- Create: `monitor/sre-agent-event-lab/assets/storyboards/s2/`
- Create: `monitor/sre-agent-event-lab/assets/storyboards/s3/`

**Interfaces:**
- `render_storyboard.py --scenario s1 --timeline PATH --output-dir PATH --ticket-url URL --email-preview PATH`
- Produces a seven-frame 1280×720 GIF with explanatory and actual badges.

- [ ] **Step 1: Write failing storyboard tests**

Assert:

- frame 1 badge is `SCENARIO`;
- frame 2 badge is `EXPECTATION`;
- actual frames use `ACTUAL`;
- final frame uses `OPERATIONAL OUTPUT`;
- all frames are 1280×720;
- GIF has 7 frames;
- S1 final frame contains ticket and email labels.

- [ ] **Step 2: Run RED**

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/scripts/tests/test_storyboard.py -q
```

- [ ] **Step 3: Implement storyboard rendering**

Reuse fonts/colors from `render_capture.py`. Each scenario supplies:

```python
{
  "situation": "...",
  "impact": "...",
  "expectations": ["...", "..."],
  "actual_event_states": ["alert-fired", "thread-created", "investigating", "conclusion"],
  "result": "...",
}
```

Select representative actual events instead of every message.

- [ ] **Step 4: Generate S1/S2/S3 storyboards**

Use normalized timelines:

```text
evidence/s1-20260812T080606Z/normalized-timeline.json
evidence/s2-20260812T081539Z/normalized-timeline.json
evidence/s3-20260812T084004Z/normalized-timeline.json
```

- [ ] **Step 5: Browser-validate the final frame and commit**

Open S1 GIF and conclusion/output PNG in the browser, verify text hierarchy and clipping, then:

```bash
git add monitor/sre-agent-event-lab/scripts/render_storyboard.py \
  monitor/sre-agent-event-lab/scripts/tests/test_storyboard.py \
  monitor/sre-agent-event-lab/assets/storyboards
git commit -m "feat(monitor): add SRE incident storyboards" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Generate and publish the ticket artifact

**Files:**
- Create: `monitor/sre-agent-event-lab/scripts/generate_notifications.py`
- Create: `monitor/sre-agent-event-lab/scripts/tests/test_notifications.py`
- Create: `monitor/sre-agent-event-lab/assets/notifications/s1-github-issue.md`
- Create after issue creation: `monitor/sre-agent-event-lab/assets/notifications/github-issue.json`
- Create after browser capture: `monitor/sre-agent-event-lab/assets/notifications/github-issue.png`

**Interfaces:**
- `generate_notifications.py --timeline PATH --report-url URL --output-dir PATH`
- Produces sanitized issue body and email artifacts.

- [ ] **Step 1: Write failing notification tests**

Assert issue body contains:

- Impact
- Detection
- Root cause
- Evidence
- Current status
- Recommended follow-up

Assert no bearer token, instrumentation key, callback signature, or connection string.

- [ ] **Step 2: Implement issue generation**

Use the final S1 conclusion and measured timestamps. Do not read unredacted callback URLs or Agent setup secrets.

- [ ] **Step 3: Create the real GitHub issue**

```bash
ISSUE_URL=$(gh issue create \
  --repo hellices/devguidesample \
  --title "[SRE-LAB] ca-sre-event-lab-vnet HTTP 500 incident" \
  --body-file monitor/sre-agent-event-lab/assets/notifications/s1-github-issue.md)
gh issue view "$ISSUE_URL" --repo hellices/devguidesample --json number,url,title,state \
  > monitor/sre-agent-event-lab/assets/notifications/github-issue.json
```

- [ ] **Step 4: Capture the issue page**

Open the public issue URL in the integrated browser and save a screenshot.

- [ ] **Step 5: Verify and commit**

```bash
jq -e '.url and .number and .state' \
  monitor/sre-agent-event-lab/assets/notifications/github-issue.json
git add monitor/sre-agent-event-lab/scripts/generate_notifications.py \
  monitor/sre-agent-event-lab/scripts/tests/test_notifications.py \
  monitor/sre-agent-event-lab/assets/notifications/s1-github-issue.md \
  monitor/sre-agent-event-lab/assets/notifications/github-issue.json \
  monitor/sre-agent-event-lab/assets/notifications/github-issue.png
git commit -m "docs(monitor): publish SRE incident ticket example" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Create the Outlook email draft and integrate outputs

**Files:**
- Create: `monitor/sre-agent-event-lab/assets/notifications/s1-incident-summary.html`
- Create: `monitor/sre-agent-event-lab/assets/notifications/s1-incident-summary.eml`
- Create: `monitor/sre-agent-event-lab/assets/notifications/s1-email-preview.png`
- Modify: `monitor/azure-sre-agent.md`
- Modify: `monitor/sre-agent-event-lab/README.md`

- [ ] **Step 1: Generate HTML and `.eml`**

Use:

```text
From: azure-sre-agent-demo@example.invalid
To: oncall@example.invalid
Subject: [Resolved][SRE-LAB] Order API HTTP 500 incident
```

Include issue URL, timeline, root cause, evidence, mitigation, status, and follow-up.

- [ ] **Step 2: Render the email preview**

Open the HTML in the integrated browser at 1280×900 and save a screenshot.

- [ ] **Step 3: Document Outlook production setup**

Explain:

- Send email (Outlook) connector;
- locked `To` parameter;
- Agent-defined subject/body;
- `Ask` permission in Review workflows;
- Autonomous mode bypass warning from Microsoft Learn.

- [ ] **Step 4: Integrate ticket/email into storyboard and introduction**

Regenerate S1 final storyboard frame with real issue URL and email preview link. Add both artifacts to the introduction.

- [ ] **Step 5: Final verification**

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/scripts/tests -q
for path in \
  monitor/sre-agent-event-lab/assets/storyboards/s1/investigation-guide.gif \
  monitor/sre-agent-event-lab/assets/notifications/github-issue.png \
  monitor/sre-agent-event-lab/assets/notifications/s1-email-preview.png; do
  test -s "$path"
done
if rg -n -i \
  'Bearer eyJ|InstrumentationKey=[0-9a-fA-F-]{36}|sig=[A-Za-z0-9_-]{20,}' \
  monitor/sre-agent-event-lab/assets/notifications \
  monitor/sre-agent-event-lab/assets/storyboards; then
  exit 1
fi
git diff --check
```

- [ ] **Step 6: Commit**

```bash
git add monitor/azure-sre-agent.md \
  monitor/sre-agent-event-lab/README.md \
  monitor/sre-agent-event-lab/assets/storyboards/s1 \
  monitor/sre-agent-event-lab/assets/notifications
git commit -m "docs(monitor): integrate SRE ticket and email workflow" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
