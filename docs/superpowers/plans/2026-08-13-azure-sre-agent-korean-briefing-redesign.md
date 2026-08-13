# Azure SRE Agent Korean Customer Briefing Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the Azure SRE Agent introduction as a natural Korean customer/partner briefing and replace fragile external images and unhelpful storyboards with local process diagrams and actual result screens.

**Architecture:** A briefing-specific test suite enforces the Microsoft Korean Localization Style Guide rules and local-image integrity. A focused renderer creates two original local diagrams plus a public-safe Agent conclusion card; the primary Markdown document is rewritten around those static visuals and actual GitHub/email screenshots, while detailed measurements remain in the validation appendix.

**Tech Stack:** Korean Markdown, Microsoft Korean Localization Style Guide, Python 3.12, Pillow, SVG, pytest, integrated browser.

## Global Constraints

- Use Microsoft Korean Localization Style Guide as the normative Korean source.
- Use `-합니다/-할 수 있습니다` for explanations and `-하세요` for direct instructions.
- Keep official Microsoft/Azure product names in English.
- Prefer Korean for general concepts: 경고, 인시던트, 근본 원인, 근거, 대응 계획, 검토 모드, 커넥터, 운영 절차서, 원격 분석 데이터, 완화 조치.
- Avoid mixed Korean-English translationese and noun-heavy phrasing.
- Remove every externally embedded Microsoft Learn image from the primary document; retain source links only.
- Remove storyboard GIFs from the primary document and remove storyboard generation artifacts from the repository.
- Use local relative PNG paths in the primary document.
- Keep actual GitHub Issue #43 and email draft screenshots.
- Distinguish native Azure Monitor integration from the lab-specific bridge.
- Preserve the measured validation appendix and live lab behavior.

---

## File Map

| File | Responsibility |
|---|---|
| `monitor/azure-sre-agent.md` | Natural Korean customer briefing |
| `monitor/sre-agent-event-lab/scripts/render_briefing_assets.py` | Create local process, scenario, and conclusion visuals |
| `monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py` | Korean tone, terminology, local image, and product/lab distinction checks |
| `monitor/sre-agent-event-lab/scripts/tests/test_briefing_assets.py` | SVG/PNG dimensions, privacy, and required panel checks |
| `monitor/sre-agent-event-lab/assets/briefing/sre-agent-process.svg` | Editable process diagram |
| `monitor/sre-agent-event-lab/assets/briefing/sre-agent-process.png` | Markdown-safe process diagram |
| `monitor/sre-agent-event-lab/assets/briefing/s1-three-panel.svg` | Editable representative scenario |
| `monitor/sre-agent-event-lab/assets/briefing/s1-three-panel.png` | Markdown-safe representative scenario |
| `monitor/sre-agent-event-lab/assets/briefing/s1-agent-conclusion.png` | Public-safe actual conclusion card |
| `monitor/sre-agent-event-lab/assets/storyboards/` | Delete |
| `monitor/sre-agent-event-lab/scripts/render_storyboard.py` | Delete |
| `monitor/sre-agent-event-lab/scripts/tests/test_storyboard.py` | Delete |

---

### Task 1: Add Korean briefing quality gates

**Files:**
- Create: `monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py`

**Interfaces:**
- Reads `monitor/azure-sre-agent.md`.
- Fails on translationese, external embedded images, storyboard references, missing product/lab distinction, or broken local image paths.

- [ ] **Step 1: Write the failing style tests**

The test must:

1. remove fenced code, inline code, links, and URLs before prose checks;
2. reject these general English terms in prose:

```python
FORBIDDEN_PROSE = (
    " alert", " incident", " evidence", " root cause", " hypothesis",
    " response plan", " connector", " runbook", " telemetry",
    " mitigation", " workflow", " ticket", " email",
)
```

3. reject `-다.` explanatory endings;
4. require `-합니다` or `-할 수 있습니다` across the introduction;
5. require `Microsoft Korean Localization Style Guide`;
6. reject remote Markdown image targets;
7. reject `storyboard` and `.gif` in the primary document;
8. resolve every local Markdown image path.

- [ ] **Step 2: Run RED**

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py -q
```

Expected: failures on current mixed terminology, `-다` tone, remote images, storyboard GIF, and missing local diagrams.

- [ ] **Step 3: Add product/lab distinction assertions**

Require the prose to include:

```text
제품에서 기본으로 지원하는 방식
이번 실증에서 사용한 방식
검토 모드
실제 연결하지 않았습니다
```

- [ ] **Step 4: Keep tests RED until the rewrite**

Do not weaken the checks to pass the old copy. Task 3 makes these tests green.

---

### Task 2: Create stable local briefing visuals

**Files:**
- Create: `monitor/sre-agent-event-lab/scripts/render_briefing_assets.py`
- Create: `monitor/sre-agent-event-lab/scripts/tests/test_briefing_assets.py`
- Create: `monitor/sre-agent-event-lab/assets/briefing/sre-agent-process.svg`
- Create: `monitor/sre-agent-event-lab/assets/briefing/sre-agent-process.png`
- Create: `monitor/sre-agent-event-lab/assets/briefing/s1-three-panel.svg`
- Create: `monitor/sre-agent-event-lab/assets/briefing/s1-three-panel.png`
- Create: `monitor/sre-agent-event-lab/assets/briefing/s1-agent-conclusion.png`

**Interfaces:**
- `render_briefing_assets.py --timeline PATH --output-dir PATH`
- Produces three 1600×900 PNGs and two equivalent SVG diagrams.

- [ ] **Step 1: Write failing asset tests**

Assert:

- all required files exist;
- PNG size is 1600×900;
- process SVG contains the stages `경고 수신`, `근거 수집`, `가설 검증`, `검토 및 승인`, `티켓과 알림`;
- scenario SVG contains `상황`, `Agent 조사`, `운영 결과`;
- conclusion PNG uses normalized fields and contains no subscription ID;
- image text contains no raw callback signature, token, or thread status JSON.

- [ ] **Step 2: Run RED**

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_assets.py -q
```

- [ ] **Step 3: Implement the process diagram**

Create an original seven-stage horizontal diagram:

```text
경고 수신 → 조사 범위 확인 → 근거 수집 → 가설 검증
→ 근본 원인과 조치 제안 → 검토 및 승인 → 티켓·알림·지식 축적
```

Use a restrained Microsoft/Azure-inspired blue palette without copying Microsoft Learn artwork.

- [ ] **Step 4: Implement the representative three-panel visual**

Use:

```text
상황: 주문 API 500 / 고객 주문 120건 실패
Agent 조사: Application Insights / 배포 설정 / 코드
운영 결과: 원인 확인 / Issue #43 / 이메일 초안
```

- [ ] **Step 5: Implement the actual conclusion card**

Use verified metadata:

```text
영향을 받은 서비스: ca-sre-event-lab-vnet
원격 분석 원본: appi-sre-event-lab-95933ae5
근본 원인: revision 0000010, FAILURE_MODE=http500
영향: GET /api/orders 120건 실패
완화 조치: 정상 revision으로 복귀
검토 모드: Agent가 Azure 리소스를 변경하지 않음
```

- [ ] **Step 6: Run GREEN and browser-review**

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_assets.py -q
```

Open all three PNGs in the browser and confirm no clipping and readable Korean.

- [ ] **Step 7: Commit**

```bash
git add monitor/sre-agent-event-lab/scripts/render_briefing_assets.py \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_assets.py \
  monitor/sre-agent-event-lab/assets/briefing
git commit -m "feat(monitor): add Korean SRE briefing visuals" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Rewrite the customer briefing and remove storyboards

**Files:**
- Rewrite: `monitor/azure-sre-agent.md`
- Modify: `monitor/sre-agent-event-lab/README.md`
- Delete: `monitor/sre-agent-event-lab/assets/storyboards/`
- Delete: `monitor/sre-agent-event-lab/scripts/render_storyboard.py`
- Delete: `monitor/sre-agent-event-lab/scripts/tests/test_storyboard.py`

**Interfaces:**
- The primary document embeds only local PNGs and actual Issue/Email screenshots.
- Detailed measurements link to the existing validation appendix.

- [ ] **Step 1: Rewrite the opening**

Use:

```markdown
# Azure SRE Agent 소개

Azure SRE Agent는 Azure 운영 환경에서 발생한 인시던트를 자동으로 조사하고,
관련 근거를 바탕으로 근본 원인과 조치 방안을 제안하는 AI 기반 운영 도우미입니다.
```

- [ ] **Step 2: Rewrite the full structure**

Use the approved 11-section structure from the design. Prefer questions in headings:

```text
Azure SRE Agent란 무엇인가요?
기존 장애 대응과 무엇이 달라지나요?
인시던트가 발생하면 어떻게 조사하나요?
어떤 시스템과 연결할 수 있나요?
권한과 승인 절차는 어떻게 제어하나요?
```

- [ ] **Step 3: Replace visuals**

Embed:

```text
sre-agent-event-lab/assets/briefing/sre-agent-process.png
sre-agent-event-lab/assets/briefing/s1-three-panel.png
sre-agent-event-lab/assets/briefing/s1-agent-conclusion.png
sre-agent-event-lab/assets/notifications/github-issue.png
sre-agent-event-lab/assets/notifications/s1-email-preview.png
```

Link to Microsoft Learn sources as references, not images.

- [ ] **Step 4: Remove storyboards**

Delete the storyboard generator, tests, manifests, PNGs, and GIFs. Keep raw evidence captures and the validation appendix.

- [ ] **Step 5: Rewrite the lab README introduction**

Change only the introduction/navigation copy to natural Korean and link to the new briefing. Keep operational commands unchanged.

- [ ] **Step 6: Run all quality gates**

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/app/tests \
  monitor/sre-agent-event-lab/scripts/tests \
  monitor/sre-agent-event-lab/infra/tests -q
git diff --check
```

- [ ] **Step 7: Render the Markdown for visual review**

Use a local Markdown renderer, open the generated HTML in the integrated browser, and verify:

- all local images render;
- headings and tables fit;
- no storyboard/GIF appears;
- actual Issue/Email screenshots are legible;
- no broken image icon appears.

- [ ] **Step 8: Commit**

```bash
git add monitor/azure-sre-agent.md \
  monitor/sre-agent-event-lab/README.md \
  monitor/sre-agent-event-lab/assets/storyboards \
  monitor/sre-agent-event-lab/scripts/render_storyboard.py \
  monitor/sre-agent-event-lab/scripts/tests/test_storyboard.py
git commit -m "docs(monitor): rewrite Azure SRE Agent briefing in Korean" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
