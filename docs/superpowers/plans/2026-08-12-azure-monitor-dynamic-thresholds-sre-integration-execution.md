# Azure Monitor Dynamic Thresholds SRE Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explain how the deterministic static-threshold lab evolves into a production Dynamic Threshold design without claiming an unexecuted result.

**Architecture:** Keep the deployed one-minute static scheduled-query rules unchanged. Add a documentation-only operating model that maps the same numeric KQL signals to five-minute Dynamic Threshold shadow rules and reuses the tested Action Group → Logic App → SRE Agent bridge after the learning gate passes.

**Tech Stack:** Markdown, Azure Monitor scheduled-query alerts, KQL, Azure SRE Agent HTTP Trigger bridge.

## Global Constraints

- State explicitly that Dynamic Thresholds were not executed in this session.
- Preserve the static rules as the source of all measured S1/S2/S3 results.
- Include the official minimum of three days and 30 samples before firing.
- Include the 10-day baseline window and three-week weekly-seasonality requirement.
- State that one-minute Log Search Dynamic Threshold rules are unsupported.
- Recommend numeric query results, Medium/Low sensitivity, and 2-of-4 violations.
- Reuse `ag-sre-agent-event-lab`; do not add unvalidated preview Bicep.

---

### Task 1: Add the Static-to-Dynamic operating guide

**Files:**
- Modify: `monitor/sre-agent-event-lab/README.md`
- Modify: `docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md`

**Interfaces:**
- README produces the reusable configuration and rollout checklist.
- Results report produces the measured-vs-proposed distinction and operational recommendation.

- [ ] **Step 1: Add a documentation contract check**

Run after editing:

```bash
for phrase in \
  "3일" \
  "30 samples" \
  "10일" \
  "3주" \
  "1분" \
  "미실증" \
  "ag-sre-agent-event-lab"; do
  rg -q "$phrase" monitor/sre-agent-event-lab/README.md
  rg -q "$phrase" \
    docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md
done
```

Expected before implementation: one or more commands exit nonzero.

- [ ] **Step 2: Add README operating guidance**

Add:

- Static vs Dynamic decision table.
- S1/S2/S3 numeric KQL candidate table.
- Five-minute frequency, 15–20-minute window, Medium sensitivity, and 2-of-4 recommendation.
- Three-day/30-sample gate, 10-day baseline, and three-week seasonality caveat.
- Shadow mode rollout and existing Action Group bridge reuse.
- Official Dynamic Threshold link.

- [ ] **Step 3: Add report recommendation**

Add a “Static에서 Dynamic으로” section that:

- says all current scores use static rules;
- explains why static was required for a same-day deterministic test;
- lists Dynamic candidate signals;
- labels Dynamic as `미실증`;
- describes the future comparison metrics: alert latency, pickup, conclusion, false positives, false negatives.

- [ ] **Step 4: Verify**

```bash
for phrase in \
  "3일" \
  "30 samples" \
  "10일" \
  "3주" \
  "1분" \
  "미실증" \
  "ag-sre-agent-event-lab"; do
  rg -q "$phrase" monitor/sre-agent-event-lab/README.md
  rg -q "$phrase" \
    docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md
done
git diff --check
```

Expected: all checks pass.

- [ ] **Step 5: Commit**

```bash
git add monitor/sre-agent-event-lab/README.md \
  docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md
git commit -m "docs(monitor): explain Dynamic Threshold SRE rollout" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
