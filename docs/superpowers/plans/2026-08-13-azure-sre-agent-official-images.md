# Azure SRE Agent Official Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five official Microsoft Learn Azure SRE Agent SVGs to the existing Korean briefing at the sections where each concept is explained.

**Architecture:** Store unmodified official SVG files under a dedicated local asset folder so the briefing renders reliably without external image requests. Keep the product briefing responsible for conceptual explanations, while the lab README and validation report remain focused on reproduction and evidence.

**Tech Stack:** Markdown, SVG, Python 3.12, pytest, curl

## Global Constraints

- Preserve each Microsoft Learn SVG without translating or editing its internal text.
- Add Korean prose and the source Microsoft Learn page next to every official image.
- Place images in existing matching sections; add sections only for root cause analysis, unified memory search, and automatic learning.
- Keep product-standard behavior distinct from the lab HTTP Trigger path.
- Do not add Storyboard or GIF references to the product briefing.
- Use only local image paths in Markdown.

---

## File Structure

- `monitor/sre-agent-event-lab/assets/official/`: local, unmodified copies of the five official Microsoft Learn SVG files.
- `monitor/azure-sre-agent.md`: customer/partner product briefing and the only document that embeds the official concept images.
- `monitor/sre-agent-event-lab/README.md`: reproduction guide; adds source links but does not duplicate concept images.
- `monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py`: verifies required official assets, section placement, source attribution, local paths, and the Storyboard/GIF prohibition.

### Task 1: Add and validate official SVG assets

**Files:**
- Create: `monitor/sre-agent-event-lab/assets/official/incident-response-flow.svg`
- Create: `monitor/sre-agent-event-lab/assets/official/root-cause-analysis.svg`
- Create: `monitor/sre-agent-event-lab/assets/official/agent-reasoning-flow.svg`
- Create: `monitor/sre-agent-event-lab/assets/official/memory-unified-search.svg`
- Create: `monitor/sre-agent-event-lab/assets/official/memory-auto-learning.svg`
- Modify: `monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py`

**Interfaces:**
- Consumes: Official SVG responses from the five verified `learn.microsoft.com` asset URLs.
- Produces: Five local SVG paths that `monitor/azure-sre-agent.md` can reference.

- [ ] **Step 1: Write the failing asset test**

Add this test to `test_briefing_docs.py`:

```python
OFFICIAL_ASSETS = {
    "incident-response-flow.svg",
    "root-cause-analysis.svg",
    "agent-reasoning-flow.svg",
    "memory-unified-search.svg",
    "memory-auto-learning.svg",
}


def test_official_sre_agent_svgs_are_stored_locally():
    asset_dir = (
        REPO_ROOT
        / "monitor"
        / "sre-agent-event-lab"
        / "assets"
        / "official"
    )

    assert {path.name for path in asset_dir.glob("*.svg")} == OFFICIAL_ASSETS
    for name in OFFICIAL_ASSETS:
        svg = (asset_dir / name).read_text()
        assert "<svg" in svg
        assert "learn.microsoft.com" not in svg
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py::test_official_sre_agent_svgs_are_stored_locally -v
```

Expected: FAIL because `assets/official/` and the five SVG files do not exist.

- [ ] **Step 3: Download the verified official SVG files**

Run:

```bash
mkdir -p monitor/sre-agent-event-lab/assets/official
curl --fail --location \
  https://learn.microsoft.com/en-us/azure/sre-agent/media/incident-response/incident-response-flow.svg \
  --output monitor/sre-agent-event-lab/assets/official/incident-response-flow.svg
curl --fail --location \
  https://learn.microsoft.com/en-us/azure/sre-agent/media/root-cause-analysis/root-cause-analysis.svg \
  --output monitor/sre-agent-event-lab/assets/official/root-cause-analysis.svg
curl --fail --location \
  https://learn.microsoft.com/en-us/azure/sre-agent/media/agent-reasoning/agent-reasoning-flow.svg \
  --output monitor/sre-agent-event-lab/assets/official/agent-reasoning-flow.svg
curl --fail --location \
  https://learn.microsoft.com/en-us/azure/sre-agent/media/memory/memory-unified-search.svg \
  --output monitor/sre-agent-event-lab/assets/official/memory-unified-search.svg
curl --fail --location \
  https://learn.microsoft.com/en-us/azure/sre-agent/media/memory/memory-auto-learning.svg \
  --output monitor/sre-agent-event-lab/assets/official/memory-auto-learning.svg
```

- [ ] **Step 4: Run the asset test and verify it passes**

Run the Step 2 command again.

Expected: `1 passed`.

- [ ] **Step 5: Commit the assets and test**

```bash
git add monitor/sre-agent-event-lab/assets/official \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py
git commit -m "docs(monitor): add official SRE Agent diagrams"
```

### Task 2: Place each image in its matching product section

**Files:**
- Modify: `monitor/azure-sre-agent.md`
- Modify: `monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py`

**Interfaces:**
- Consumes: Five local SVG paths from Task 1.
- Produces: A product briefing where each official image has a self-contained Korean explanation and source link.

- [ ] **Step 1: Write the failing placement test**

Add:

```python
def test_official_images_are_placed_with_sections_and_sources():
    text = BRIEFING.read_text()
    expected = {
        "incident-response-flow.svg": "## 인시던트가 발생하면 어떻게 조사하나요?",
        "root-cause-analysis.svg": "## 근본 원인은 어떻게 찾나요?",
        "agent-reasoning-flow.svg": "## 권한과 승인 절차는 어떻게 제어하나요?",
        "memory-unified-search.svg": "## 과거 경험과 운영 문서는 어떻게 활용하나요?",
        "memory-auto-learning.svg": "## 조사가 끝난 뒤 무엇을 학습하나요?",
    }
    for image, heading in expected.items():
        assert image in text
        assert heading in text

    for source in (
        "https://learn.microsoft.com/azure/sre-agent/incident-response",
        "https://learn.microsoft.com/azure/sre-agent/root-cause-analysis",
        "https://learn.microsoft.com/azure/sre-agent/agent-reasoning",
        "https://learn.microsoft.com/azure/sre-agent/memory",
    ):
        assert source in text
```

- [ ] **Step 2: Run the placement test and verify it fails**

Run:

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py::test_official_images_are_placed_with_sections_and_sources -v
```

Expected: FAIL because the briefing does not yet reference the official SVGs or new headings.

- [ ] **Step 3: Update the product briefing**

Make these precise placements in `monitor/azure-sre-agent.md`:

```markdown
## 인시던트가 발생하면 어떻게 조사하나요?

![Azure SRE Agent 공식 인시던트 대응 흐름](sre-agent-event-lab/assets/official/incident-response-flow.svg)

> 출처: [Automate Incident Response in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/incident-response)
```

After the numbered investigation steps, add:

```markdown
## 근본 원인은 어떻게 찾나요?

![Azure SRE Agent 공식 근본 원인 분석 흐름](sre-agent-event-lab/assets/official/root-cause-analysis.svg)

> 출처: [Root Cause Analysis in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/root-cause-analysis)

Azure SRE Agent는 오류 로그를 나열하는 데서 멈추지 않습니다. 증상을 기준으로 관련 로그, 메트릭, 배포 이력, 소스 코드와 과거 경험을 모으고 가능한 원인을 가설로 세웁니다. 이후 각 가설을 근거와 비교해 제외하거나 확인하고, 결론을 뒷받침하는 자료와 함께 조치 방안을 제시합니다.
```

In `권한과 승인 절차는 어떻게 제어하나요?`, place:

```markdown
![Azure SRE Agent 공식 추론과 실행 흐름](sre-agent-event-lab/assets/official/agent-reasoning-flow.svg)

> 출처: [Agent Reasoning in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/agent-reasoning)
```

After `어떤 정보를 조사할 수 있나요?`, add the two independent sections:

```markdown
## 과거 경험과 운영 문서는 어떻게 활용하나요?

![Azure SRE Agent 공식 메모리 통합 검색 구조](sre-agent-event-lab/assets/official/memory-unified-search.svg)

> 출처: [Memory and Knowledge in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/memory)

Azure SRE Agent는 과거 조사 대화, 사용자가 기억하도록 지정한 내용, 업로드한 운영 문서와 연결된 지식 원본을 함께 검색합니다. 답변에는 근거와 출처를 포함해 어떤 경험과 문서를 사용했는지 확인할 수 있습니다.

## 조사가 끝난 뒤 무엇을 학습하나요?

![Azure SRE Agent 공식 자동 학습 흐름](sre-agent-event-lab/assets/official/memory-auto-learning.svg)

> 출처: [Memory and Knowledge in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/memory)

조사가 완료되면 Azure SRE Agent는 확인한 증상, 효과가 있었던 해결 단계, 근본 원인과 피해야 할 접근을 추출합니다. 이렇게 축적한 내용은 이후 유사한 인시던트를 조사할 때 다시 검색할 수 있습니다.
```

Move the existing local Korean process image and its editable SVG link to `이번 실증에서 사용한 방식`, immediately before the lab-specific text flow. Do not delete either file.

- [ ] **Step 4: Run all briefing tests**

Run:

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_assets.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the product briefing**

```bash
git add monitor/azure-sre-agent.md \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py
git commit -m "docs(monitor): explain SRE Agent with official diagrams"
```

### Task 3: Update source links and run full verification

**Files:**
- Modify: `monitor/sre-agent-event-lab/README.md`

**Interfaces:**
- Consumes: Microsoft Learn source pages used by the product briefing.
- Produces: A reproduction guide with current official references and no duplicated concept images.

- [ ] **Step 1: Update the official resources list**

Add these links under `## 공식 자료` without embedding images:

```markdown
- [Azure SRE Agent 제품 소개](../azure-sre-agent.md)
- [Incident response](https://learn.microsoft.com/azure/sre-agent/incident-response)
- [Root cause analysis](https://learn.microsoft.com/azure/sre-agent/root-cause-analysis)
- [Agent reasoning](https://learn.microsoft.com/azure/sre-agent/agent-reasoning)
- [Memory and knowledge](https://learn.microsoft.com/azure/sre-agent/memory)
```

- [ ] **Step 2: Run complete tests**

Run:

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest monitor/sre-agent-event-lab
```

Expected: `47 passed` plus the two new tests, for a total of `49 passed`.

- [ ] **Step 3: Validate Bicep and document assets**

Run:

```bash
cd monitor/sre-agent-event-lab/infra
az bicep build --file subscription.bicep --stdout >/dev/null
az bicep build --file main.bicep --stdout >/dev/null
az deployment sub validate \
  --location koreacentral \
  --template-file subscription.bicep \
  --parameters subscription.bicepparam \
  --query properties.provisioningState -o tsv
```

Expected: `Succeeded`.

From the repository root, run:

```bash
test "$(grep -Eo '!\[[^]]*\]\([^)]+\)' monitor/azure-sre-agent.md | grep -Ec 'https?://')" -eq 0
test "$(grep -Eic 'storyboard|\.gif' monitor/azure-sre-agent.md)" -eq 0
git grep -I -nE \
  'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|AccountKey=[A-Za-z0-9+/=]{20,}' \
  -- . ':!monitor/sre-agent-event-lab/evidence/**' && exit 1 || true
```

Expected: all commands exit with status 0 and print no secret matches.

- [ ] **Step 4: Review the rendered briefing**

Open the Markdown preview and verify:

- all five official SVGs render at readable width;
- each image sits in its matching section;
- the local Korean process image appears only with the lab-specific path;
- the GitHub Issue, email draft, and Agent conclusion images still render;
- product-standard and lab-specific behavior remain visibly separated.

- [ ] **Step 5: Commit the source-link update**

```bash
git add monitor/sre-agent-event-lab/README.md
git commit -m "docs(monitor): link official SRE Agent concepts"
```
