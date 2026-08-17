# Dynamic Threshold Introduction-Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore PR #54 to the original one-file Azure Monitor Dynamic Threshold introduction and remove every hands-on experiment change.

**Architecture:** Commit `d35c219e7ba0e9724a488b9e9ab40aa0f17823e0` is the approved reference state. Restore every path changed after that commit to the reference, then prove that the branch diff against `origin/main` contains exactly the original brief and that the brief is byte-identical to the reference.

**Tech Stack:** Git, Markdown, Python/pytest, curl.

## Global Constraints

- Keep only `monitor/azure-monitor-dynamic-thresholds-brief.md`.
- The brief must match commit `d35c219e7ba0e9724a488b9e9ab40aa0f17823e0` byte for byte.
- Remove all lab, Bicep, asset, test, deployment-plan, SRE Agent, README, ignore-file, and workflow-artifact changes made after the original brief.
- Keep the official Microsoft chart embedded from Microsoft Learn.
- PR #54 must describe an introduction only and must not mention a runnable case.

---

### Task 1: Restore the One-File Brief

**Files:**
- Keep: `monitor/azure-monitor-dynamic-thresholds-brief.md`
- Restore/remove: every other path in `git diff --name-only d35c219..HEAD`

**Interfaces:**
- Consumes: reference commit `d35c219e7ba0e9724a488b9e9ab40aa0f17823e0`.
- Produces: one-file branch diff against `origin/main`.

- [ ] **Step 1: Record the failing scope check**

Run:

```bash
python3 - <<'PY'
import subprocess

base = "b378da83594f89f81deea40f1fadaaab0db891ad"
paths = subprocess.check_output(
    ["git", "diff", "--name-only", f"{base}..HEAD"],
    text=True,
).splitlines()
assert paths == ["monitor/azure-monitor-dynamic-thresholds-brief.md"], paths
PY
```

Expected: FAIL because the branch currently contains the lab experiment and
workflow specification changes.

- [ ] **Step 2: Restore every post-brief path to the approved reference**

Run:

```bash
git diff --name-only -z d35c219e7ba0e9724a488b9e9ab40aa0f17823e0..HEAD \
  | xargs -0 git restore \
      --source=d35c219e7ba0e9724a488b9e9ab40aa0f17823e0 \
      --staged \
      --worktree \
      --
```

This restores modified pre-existing files and removes files that do not exist
in the reference commit, including the temporary `docs/superpowers` artifacts.

- [ ] **Step 3: Prove the branch scope and byte identity**

Run:

```bash
python3 - <<'PY'
import subprocess
from pathlib import Path

merge_base = "b378da83594f89f81deea40f1fadaaab0db891ad"
reference = "d35c219e7ba0e9724a488b9e9ab40aa0f17823e0"
brief = "monitor/azure-monitor-dynamic-thresholds-brief.md"

paths = subprocess.check_output(
    ["git", "diff", "--cached", "--name-only", merge_base],
    text=True,
).splitlines()
assert paths == [brief], paths

expected = subprocess.check_output(["git", "show", f"{reference}:{brief}"])
actual = Path(brief).read_bytes()
assert actual == expected
print("one-file scope and reference content verified")
PY
```

Expected: `one-file scope and reference content verified`.

- [ ] **Step 4: Run documentation validation**

Run:

```bash
cd monitor/sre-agent-event-lab
app/.venv/bin/python -m pytest scripts/tests/test_privacy.py scripts/tests/test_repo_readme.py -q
cd ../..
python3 - <<'PY'
from pathlib import Path
import re
import urllib.request

doc = Path("monitor/azure-monitor-dynamic-thresholds-brief.md")
urls = sorted(set(re.findall(r"https://[^)\\s]+", doc.read_text())))
for url in urls:
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        assert response.status < 400, (url, response.status)
print(f"validated {len(urls)} official URLs")
PY
git diff --check
```

Expected: all tests pass, every official URL returns below 400, and
`git diff --check` is silent.

- [ ] **Step 5: Commit the introduction-only cleanup**

```bash
git add -A
git commit -m "docs(monitor): keep Dynamic Threshold introduction only" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 6: Update and verify PR #54**

Run:

```bash
git push origin docs/azure-monitor-dynamic-threshold-brief
gh pr edit 54 \
  --title "docs(monitor): introduce Azure Monitor Dynamic Thresholds" \
  --body $'## Summary\n- explain how Dynamic Thresholds learn an allowed range and when the model becomes useful\n- distinguish static thresholds from Metric, Log Search, and PromQL dynamic alert paths\n- provide a safe shadow-mode adoption flow with official Microsoft imagery and references\n\n## Validation\n- relevant monitoring documentation tests passed\n- all official URLs in the brief returned successfully\n- branch diff contains only the introduction document'
gh pr view 54 --json state,title,headRefOid,files,url
```

Expected: PR #54 is open and lists only
`monitor/azure-monitor-dynamic-thresholds-brief.md`.
