# Voice Business Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a two-page voice-data topic whose business root leads with open product-retention evidence, exact statutory periods, and a concrete Amazon Alexa enforcement case instead of broad legal and operational generalities.

**Architecture:** Promote the business page to the topic root and keep Azure as the only child. Reorder the root into product evidence, business decisions and cases, exact-period statutes, Alexa enforcement, and compact appendices; preserve record-type boundaries so audio, transcript, voiceprint, transaction record, and AI log periods are never merged.

**Tech Stack:** Markdown, YAML front matter, MkDocs Material, Python 3.13, pytest, GitHub CLI

## Global Constraints

- Keep exactly two authored pages: the business/policy topic root and the Azure child.
- Do not add a redirect for the unpublished pull-request-only `business-patterns` path.
- Preserve `published_at: 2026-10-17`.
- Set `sources_checked_at: 2026-10-19`.
- Keep the separate case/product policy date `2026-10-14`.
- Keep `verification_status: needs-review`.
- Keep the heading and anchor `주요 AI·음성 제품은 무엇을 저장하고 언제 지우는가? { #product-storage-comparison }`.
- Render the Bixby/Gemini/ChatGPT/Copilot/Siri comparison without a collapsed wrapper.
- Show only exact statutory periods or immediate-deletion rules in the numeric-law table.
- Distinguish raw audio, transcript, voiceprint, transaction record, financial record, and high-risk AI log.
- Label Amazon complaint statements as allegations and filed-order requirements as remedies.
- Do not provide legal advice or decide whether a rule applies to a reader.
- Preserve existing direct sources and source-specific unknowns.
- Keep both Azure architecture SVG previews in PR #83.
- Include `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` in every implementation commit.

## File Structure

- Modify `docs/services/microsoft-foundry/voice-data-management/index.md`: promoted root metadata, product table, business decision table, case order, exact-law table, Alexa case, compact checklist, and appendices.
- Remove `docs/services/microsoft-foundry/voice-data-management/business-patterns/index.md`: unpublished child source already promoted into the root.
- Modify `docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md`: `topic_order: 1` and root link.
- Keep all files under `docs/services/microsoft-foundry/voice-data-management/images/` unchanged.
- Modify `project/specs/2026-10-19-two-page-voice-research-topic-design.md` and `project/plans/2026-10-19-two-page-voice-research-topic.md` only to retain the corrected no-redirect decision.
- Keep `project/specs/2026-10-19-voice-business-evidence-design.md` as the controlling content spec.

---

### Task 1: Finish the two-page topic root

**Files:**
- Modify: `docs/services/microsoft-foundry/voice-data-management/index.md:1-43`
- Remove: `docs/services/microsoft-foundry/voice-data-management/business-patterns/index.md`
- Modify: `docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md:1-66`
- Modify: `project/specs/2026-10-19-two-page-voice-research-topic-design.md`
- Modify: `project/plans/2026-10-19-two-page-voice-research-topic.md`

**Interfaces:**
- Consumes: the complete business document already moved into the root.
- Produces: one root, one child, no unpublished child source, corrected links, and source dates consumed by Tasks 2-4.

- [ ] **Step 1: Verify the two-page acceptance state**

Run:

```bash
../../.venv/bin/python - <<'PY'
from pathlib import Path
import yaml

topic = Path("docs/services/microsoft-foundry/voice-data-management")
root = (topic / "index.md").read_text(encoding="utf-8")
metadata = yaml.safe_load(root.split("---", 2)[1])
body = root.split("---", 2)[2]

assert metadata["title"] == "앱 음성 서비스 기록관리 사례와 정책"
assert "topic_order" not in metadata
assert "redirect_from" not in metadata
assert not (topic / "business-patterns" / "index.md").exists()
assert "business-patterns" not in body
assert "images/voice-data-lifecycle.svg" in body
assert "(azure-storage/index.md)" in body

azure = (topic / "azure-storage" / "index.md").read_text(encoding="utf-8")
azure_metadata = yaml.safe_load(azure.split("---", 2)[1])
assert azure_metadata["topic_order"] == 1
assert "(../index.md)" in azure
PY
```

Expected: exit 0 with no output.

- [ ] **Step 2: Update root source metadata**

Set:

```yaml
sources_checked_at: 2026-10-19
published_at: 2026-10-17
verification_status: needs-review
```

Keep the visible product-policy case date `2026-10-14`. Set the visible
recent-source and legal/source verification dates to `2026-10-19 (한국시간)`.

Keep the root front matter's existing Microsoft/Azure `official_sources`.
The validator reserves that field for allowlisted Microsoft hosts. Task 3
adds the following government and court sources as inline links in the
exact-law and Alexa sections instead; do not add them to front matter:

```text
- title: 전자상거래법 시행령 제6조
  url: https://law.go.kr/LSW/lsLinkCommonInfo.do?lspttninfSeq=63460&chrClsCd=010202
- title: 금융소비자 보호에 관한 법률 제28조
  url: https://www.law.go.kr/LSW/lsLinkCommonInfo.do?lsJoLnkSeq=1033002393
- title: 금융소비자보호법 시행령 제26조
  url: https://law.go.kr/lsLinkCommonInfo.do?lspttninfSeq=166903&chrClsCd=010202
- title: MiFID II consolidated text
  url: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02014L0065-20240109
- title: EU Artificial Intelligence Act
  url: https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng
- title: COPPA 2025 final rule
  url: https://www.federalregister.gov/api/v1/documents/2025-05904.json
- title: Illinois Biometric Information Privacy Act Section 15
  url: https://www.ilga.gov/documents/legislation/ilcs/documents/074000140K15.htm
- title: Texas biometric identifiers statute
  url: https://tcss.legis.texas.gov/resources/BC/htm/BC.503.htm
- title: Amazon Alexa complaint
  url: https://search.ftc.gov/system/files/ftc_gov/pdf/Amazon-Complaint-%28Dkt.1%29.pdf
- title: Amazon Alexa filed stipulated order
  url: https://search.ftc.gov/system/files/ftc_gov/pdf/1923128amazonalexaorderfiled.pdf
```

- [ ] **Step 3: Stage the structural move before topic tests**

Run:

```bash
git add -A \
  docs/services/microsoft-foundry/voice-data-management \
  project/specs/2026-10-19-two-page-voice-research-topic-design.md \
  project/plans/2026-10-19-two-page-voice-research-topic.md
```

This is required because repository topic tests use `git ls-files`; an
unstaged deletion would make them inspect a path that no longer exists.

- [ ] **Step 4: Run focused structure checks**

Run:

```bash
../../.venv/bin/python -m pytest tests/docs/test_topics.py -q
../../.venv/bin/python scripts/docs/validate_metadata.py
../../.venv/bin/python scripts/docs/validate_sources.py
../../.venv/bin/python scripts/docs/validate_links.py
```

Expected: all commands exit 0 and discovery reports 79 public documents.

- [ ] **Step 5: Commit the root promotion**

```bash
git commit -m "docs(foundry): reduce voice research to two pages" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: the commit contains the root replacement, child deletion, Azure
renumbering/link, metadata date, source list, and corrected no-redirect design
documents.

---

### Task 2: Lead with product and business evidence

**Files:**
- Modify: `docs/services/microsoft-foundry/voice-data-management/index.md`

**Interfaces:**
- Consumes: the promoted root from Task 1.
- Produces: an open product-policy table, compact decision table, open
  business-use comparison, and collapsed detailed case evidence.

- [ ] **Step 1: Write the visible-order acceptance probe**

Run:

```bash
../../.venv/bin/python - <<'PY'
from pathlib import Path

text = Path(
    "docs/services/microsoft-foundry/voice-data-management/index.md"
).read_text(encoding="utf-8")

product = text.index("## 주요 AI·음성 제품은 무엇을 저장하고 언제 지우는가?")
decisions = text.index("## 비즈니스가 먼저 결정할 기록")
comparison = text.index("## 업무별 저장 방식과 기록 수명주기")
laws = text.index("## 법령이 보존기간을 직접 정한 경우")

assert product < decisions < comparison < laws
assert "<summary><strong>Bixby·Gemini·ChatGPT·Microsoft Copilot·Siri" not in text
assert "### 1. [한 번의 음성에서 여러 기록이 생김]" not in text
PY
```

Expected before implementation: FAIL because the product section is later,
collapsed, and the six numbered patterns still exist.

- [ ] **Step 2: Move and open the product-policy table**

Place this heading directly after the reading boundary:

```markdown
## 주요 AI·음성 제품은 무엇을 저장하고 언제 지우는가? { #product-storage-comparison }

이 표는 서비스·기능 모드·설정·지역별 공개 정책을 직접 비교한 이
문서의 핵심 리서치 결과입니다. 실제 고객 설정이나 비공개 운영을
추정하지 않습니다.
```

Move the existing Bixby, Gemini Live, ChatGPT Voice, Microsoft Copilot Voice
Chat, and Siri/Dictation table below it. Remove only its surrounding
`<details>` and `<summary>` tags. Preserve every table cell and source link.

Leave `Microsoft 제품마다 기록은 어디에 남는가?` in a collapsed appendix
later in the document.

- [ ] **Step 3: Replace the six patterns with the decision table**

Create:

```markdown
## 비즈니스가 먼저 결정할 기록

| 결정 | 필요한 근거 |
|---|---|
| **어떤 기록이 생기는가?** | 입력·출력 오디오, 전사문, 요약, 이벤트, 도구 호출, 업무 기록, 추적, 생체 템플릿 |
| **왜 보관하는가?** | 기능 제공, 이용자 이력, 거래 증빙, 분쟁 처리, 법정 기록, 보안, 평가, 모델 개선 |
| **언제 기간이 시작·종료되는가?** | 요청 완료, 계약·공급, 불만 종료, 목적 만료, 마지막 상호작용, 프로필 비활성, 삭제 요청 |
| **어떤 근거가 기간을 정하는가?** | 제품 정책, 법령, 법원 명령, 조직 정책, 고객 설정 |
| **무엇을 함께 지워야 하는가?** | 오디오, 전사문, 위치정보, 파생 사본, 모델 개선 입력, 처리자 사본, 색인, 백업 |

### 어떤 기록인가?

원음·전사문·요약·업무 결과·추적·voiceprint는 서로 다른 기록입니다.

### 왜·얼마나 보관하는가?

업무 목적과 정확한 기간 근거를 기록별로 연결하고, 다른 기록의 기간을
원음에 복사하지 않습니다.

### 무엇을 함께 지우는가?

삭제 요청은 원음뿐 아니라 전사문·위치정보·파생 사본·모델 개선 입력과
처리자 사본의 범위를 함께 확인해야 합니다.
```

The existing long-form sections continue to own `#voice-record-types`,
`#raw-audio-retention`, and `#deletion-completion` until Task 4 removes those
sections and transfers the anchors to these H3 headings.

- [ ] **Step 4: Put the business comparison before case details**

Under:

```markdown
## 업무별 저장 방식과 기록 수명주기를 비교하면 무엇이 보이는가?
```

render the existing `업무마다 무엇을 어디에 얼마나 저장하는가?` table
first.

After the table, add:

```markdown
<details markdown="1">
<summary><strong>사례별 공개 근거와 적용 범위 보기</strong></summary>
```

Move all 14 detailed case subsections into that wrapper. Preserve their
explicit anchors, dates, legal-entity boundaries, unknowns, and source links.
Close the wrapper after Duolingo.

Remove the earlier duplicate detailed-case block.

- [ ] **Step 5: Run the visible-order probe**

Rerun Step 1.

Expected: exit 0 with no output.

- [ ] **Step 6: Build and browser-check the core evidence**

Run:

```bash
../../.venv/bin/python scripts/docs/validate_links.py
../../.venv/bin/python -m mkdocs build --strict
```

In the browser verify:

- the product table is open without clicking;
- product comparison precedes the decision and business tables;
- exactly 14 detailed cases remain in the collapsed evidence block; and
- all product and case anchors resolve.

- [ ] **Step 7: Commit the product/business reorder**

```bash
git add docs/services/microsoft-foundry/voice-data-management/index.md
git commit -m "docs(foundry): lead with voice retention evidence" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Replace general law prose with exact periods and Alexa remedies

**Files:**
- Modify: `docs/services/microsoft-foundry/voice-data-management/index.md`

**Interfaces:**
- Consumes: official source URLs added in Task 1.
- Produces: one open exact-period table and one open Alexa case section with
  complaint/order separation.

- [ ] **Step 1: Replace the broad legal overview**

Remove the current Korea/EU/US general-principles table and its surrounding
`<details>`.

Insert:

```markdown
## 법령이 보존기간을 직접 정한 경우 { #jurisdiction-rules }

아래 표는 조문이 숫자나 즉시 삭제 시점을 직접 제시한 범위만 옮깁니다.
적용 여부를 해석하지 않으며, 다른 기록의 기간을 원음에 확대하지 않습니다.

| 관할·근거 | 정확한 대상 | 기간·기산점 | 원문 핵심 | 음성 경계 |
|---|---|---|---|---|
| **한국 전자상거래법 시행령 제6조** | 표시·광고 / 계약·청약철회 / 대금결제·공급 / 불만·분쟁 기록 | **6개월 / 5년 / 5년 / 3년** | `거래기록의 대상ㆍ범위 및 기간` | 거래 결과 기록이며 모든 통화 원음의 기간이 아님 |
| **한국 금융소비자보호법 제28조·시행령 제26조** | 계약체결·이행, 광고, 권리행사, 업무위탁 자료 | 원칙 **10년**. 10년 초과 보장·계약은 해당 보장·계약기간 | `대통령령으로 정하는 기간이란 10년` | 적용 규칙이 녹취를 요구 자료로 보는 경우에만 해당하며 모든 금융 통화 원음의 공통 기간이 아님 |
| **금융 내부통제 자료 / 이에 준하는 고시 자료** | 시행령 제26조제1항제5호 / 제7호 위임 자료 | 내부통제는 금융위원회 고시로 **5년 이내**, 제7호 자료는 고시로 **10년 이내** | 기본 10년의 명시적 예외 | 실제 기간은 적용되는 고시를 별도 확인 |
| **EU MiFID II Article 16(7)** | 자기계정 거래·고객 주문 접수·전달·실행과 관련되거나 이를 의도한 전화·전자통신 | **5년**, 감독기관 요청 시 **최대 7년** | `five years ... up to seven years` | 대상 투자업무 통화에 직접 적용 |
| **EU AI Act Articles 19(1), 26(6)** | 공급자·배포자가 통제하는 고위험 AI 자동 생성 로그 | 목적에 맞는 기간, **최소 6개월**. 적용되는 EU·회원국 법률이 달리 정하면 그 규칙 적용 | `at least six months, unless provided otherwise` | 고위험 AI 로그 규칙이며 모든 음성·전사 보관 의무가 아님 |
| **COPPA 16 CFR 312.5(c)(9)** | 아동의 특정 요청 응답용 음성 파일만 수집하고 다른 개인정보·이용·공개가 없는 예외 | 응답 **직후 삭제** | `deletes it immediately after responding` | 조건을 모두 충족한 제한적 예외 |
| **Illinois BIPA §15(a)** | voiceprint를 포함한 생체 식별자·정보 | 목적 달성 또는 마지막 상호작용 후 **3년** 중 빠른 시점 | `whichever occurs first` | 일반 음성 녹음이 아니라 voiceprint |
| **Texas B&amp;C Code §503.001** | 상업 목적으로 수집한 voiceprint 등 생체 식별자 | 목적 종료 후 합리적 기간, 늦어도 **1년**. 다른 법정 문서와 연결되면 그 의무 종료 후 1년 | `not later than the first anniversary` | 금융기관 voiceprint와 법이 정한 일부 AI·보안·사기 용도 예외를 별도 확인 |
```

Link each row's statute name to its official source.

- [ ] **Step 2: Add the no-universal-period boundary**

Immediately below the table:

```markdown
### 일률적인 일수가 없는 규정

[한국 개인정보 보호법](https://www.law.go.kr/법령/개인정보보호법),
[GDPR](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng),
[CCPA/CPRA](https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?sectionNum=1798.100.&lawCode=CIV)는
목적·필요성·고지한 기준 또는 필요 종료 후 삭제를 요구하지만 모든 음성
원음에 적용할 하나의 공통 일수를 정하지 않습니다. 따라서 위 숫자 표에
임의 기간을 만들지 않습니다.

[COPPA §312.10](https://www.federalregister.gov/documents/full_text/text/2025/04/22/2025-05904.txt)도
일반 아동 개인정보에는 공통 일수를 두지 않고, 특정 목적에 합리적으로
필요한 기간만 보유하고 무기한 보유를 금지하며 서면 삭제 시점을 정하도록
요구합니다.
```

- [ ] **Step 3: Replace the Alexa summary with the actual case**

Create this open section:

```markdown
## Amazon Alexa 사건에서 실제로 무엇이 문제였는가? { #alexa-deletion-case }

이 사건은 현재 Alexa 정책의 설명이 아니라 2023년 고소장의 혐의와
2023-07-19 법원 제출 합의명령의 조치를 구분해 보는 집행 사례입니다.

### 고소장이 제기한 혐의

| 대상 | FTC·DOJ 고소장의 주장 |
|---|---|
| **원음·전사문** | 기본 설정이 아동·성인의 원음과 전사문을 비활성 계정까지 무기한 저장 |
| **제품 개선** | 저장한 원음·전사문을 요청 처리뿐 아니라 Alexa 학습·개선에 사용 |
| **삭제 요청** | 일부 요청에서 원음 삭제 뒤에도 전사문을 유지하고 이를 알리지 않음 |
| **위치·음성정보** | 이용자 요청 뒤에도 위치·음성정보를 삭제하지 않고 잠재적 이용을 위해 유지 |

### 합의명령이 요구한 조치

| 조치 | 명령 내용 |
|---|---|
| **민사 벌금** | **USD 25 million** |
| **비활성 아동 프로필 식별** | Alexa와 상호작용한 뒤 **18개월 이상** 사용되지 않은 아동 프로필을 찾는 절차를 명령 입력 후 **6개월 이내** 구축 |
| **비활성 아동 정보 삭제** | 위 정의에 해당하는 프로필 식별 후 **90일 이내** 삭제. 부모가 보유를 요청하거나 프로필이 다시 활성화되면 예외 |
| **삭제 요청 이행** | Amazon이 제공한 삭제 기능으로 요청된 Alexa 위치·음성정보와 아동 개인정보 삭제 |
| **삭제 뒤 모델·제품 이용** | 삭제 처리한 정보를 이후 어떤 데이터 제품이든 생성·개선하는 데 사용 금지. 삭제 처리 전에 이미 만들어진 제품의 계속 이용까지 금지한 것은 아님 |

고소장 주장은 혐의이고, 합의명령은 이 사건 당사자에게 적용되는 조치입니다.
모든 음성 서비스의 법정 보유기간이나 현재 Alexa 동작으로 일반화하지 않습니다.
```

Link the complaint, filed order, and FTC case page directly in this section.

- [ ] **Step 4: Add source-specific exactness checks**

Run:

```bash
../../.venv/bin/python - <<'PY'
from pathlib import Path

text = Path(
    "docs/services/microsoft-foundry/voice-data-management/index.md"
).read_text(encoding="utf-8")

required = [
    "6개월 / 5년 / 5년 / 3년",
    "최대 7년",
    "최소 6개월",
    "응답 **직후 삭제**",
    "마지막 상호작용 후 **3년**",
    "목적 종료 후 합리적 기간, 늦어도 **1년**",
    "USD 25 million",
    "명령 입력 후 **6개월 이내** 구축",
    "**90일 이내** 삭제",
]
for value in required:
    assert value in text, value

assert "고소장이 제기한 혐의" in text
assert "합의명령이 요구한 조치" in text
assert "모든 음성 원음에 적용할 하나의 공통" in text
PY
```

Expected: exit 0 with no output.

- [ ] **Step 5: Run source, link, and strict-build gates**

Run:

```bash
../../.venv/bin/python scripts/docs/validate_sources.py
../../.venv/bin/python scripts/docs/validate_links.py
../../.venv/bin/python scripts/docs/validate_public_safety.py
../../.venv/bin/python -m mkdocs build --strict
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit exact laws and Alexa**

```bash
git add docs/services/microsoft-foundry/voice-data-management/index.md
git commit -m "docs(foundry): cite exact voice retention rules" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Compress generic implementation guidance

**Files:**
- Modify: `docs/services/microsoft-foundry/voice-data-management/index.md`

**Interfaces:**
- Consumes: the core evidence sections from Tasks 2-3.
- Produces: a short business checklist and collapsed secondary appendices.

- [ ] **Step 1: Replace long retention and deletion recipes**

Remove the long `목적에 따라 달라지는 원음 보관 방식`, `음성의 관리
항목에는 무엇이 있는가?`, and `삭제 요청은 언제 완전히 끝났다고 볼 수
있는가?` bodies.

Create:

```markdown
## 기록·삭제 결정 체크리스트

![음성 데이터 산출물과 삭제 검증 수명주기 검토 예시](images/voice-data-lifecycle.svg)

| 확인 질문 | 기록할 답 |
|---|---|
| 어떤 기록인가? | 원음·전사문·요약·이벤트·업무 결과·trace·voiceprint |
| 왜 필요한가? | 기능·이용자 이력·증빙·분쟁·법정 기록·보안·평가·개선 |
| 어떤 근거가 기간을 정하는가? | 제품 정책·법령·명령·조직 정책·고객 설정과 버전 |
| 기산점은 무엇인가? | 요청 완료·계약/공급·불만 종료·목적 만료·마지막 상호작용·프로필 비활성 |
| 무엇을 함께 지우는가? | 원음·전사문·위치·파생물·모델 개선 입력·처리자 사본·색인·백업 |
| 완료를 무엇으로 확인하는가? | 저장소별 삭제 결과·검색 미반환·재생성 차단·처리자 확인·백업 만료 |
```

Do not retain prescriptive tombstone, JIT, cryptographic deletion, or
legal-hold workflow recipes in the core page.
Transfer the explicit `#voice-record-types`, `#raw-audio-retention`, and
`#deletion-completion` anchors from the removed H2 sections to the three H3
headings created in Task 2.

- [ ] **Step 2: Group secondary research into collapsed appendices**

Keep concise versions of the existing material under:

```markdown
## 추가 검증·제품 자료

<details markdown="1">
<summary><strong>음성 텍스트·요약·생체정보·접근성 검토</strong></summary>
```

Preserve:

- `#transcript-summary-quality`;
- `#voice-biometric-attacks`;
- WER/DER/JER and event-order evaluation;
- NIST/ISO scope boundaries; and
- accessibility, bystander, and shared-device controls.

Create a second collapsed block:

```markdown
<details markdown="1">
<summary><strong>Microsoft·컨택센터·금융·공공 추가 사례</strong></summary>
```

Preserve:

- `#microsoft-record-locations`;
- `#gaming-public-identity`;
- unique product periods and direct source links; and
- customer-case claims with their stated measurement boundaries.

Remove repeated introductions and generic statements that do not change a
record, purpose, period, trigger, or deletion decision.

- [ ] **Step 3: Verify core and appendix order**

Run:

```bash
../../.venv/bin/python - <<'PY'
from pathlib import Path

text = Path(
    "docs/services/microsoft-foundry/voice-data-management/index.md"
).read_text(encoding="utf-8")

order = [
    "## 주요 AI·음성 제품은 무엇을 저장하고 언제 지우는가?",
    "## 비즈니스가 먼저 결정할 기록",
    "## 업무별 저장 방식과 기록 수명주기를 비교하면 무엇이 보이는가?",
    "## 법령이 보존기간을 직접 정한 경우",
    "## Amazon Alexa 사건에서 실제로 무엇이 문제였는가?",
    "## 기록·삭제 결정 체크리스트",
    "## 추가 검증·제품 자료",
]
positions = [text.index(value) for value in order]
assert positions == sorted(positions)
assert "### 1. [한 번의 음성에서 여러 기록이 생김]" not in text
assert "암호학적 삭제 검토 항목" not in text
PY
```

Expected: exit 0 with no output.

- [ ] **Step 4: Browser-check the compressed page**

Verify at desktop and 390px:

- product comparison, exact-law table, and Alexa case are open;
- detailed business cases and secondary appendices are collapsed;
- table containers scroll without page overflow;
- every retained anchor navigates to visible or auto-opened content; and
- the page has exactly two authored navigation entries: root and Azure.

- [ ] **Step 5: Commit the content compression**

```bash
git add docs/services/microsoft-foundry/voice-data-management/index.md
git commit -m "docs(foundry): focus voice research on business evidence" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Complete validation and update PR #83

**Files:**
- Verify: `docs/services/microsoft-foundry/voice-data-management/`
- Update: pull request `hellices/devguidesample#83`

**Interfaces:**
- Consumes: the two-page evidence-first topic from Tasks 1-4.
- Produces: complete local validation, two-link PR overview, passing CI, and zero unresolved threads.

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

Expected: every command exits 0. Use the actual document and file counts after
the authored page count decreases from 80 to 79.

- [ ] **Step 2: Verify built pages and anchors**

Run:

```bash
test -f site/services/microsoft-foundry/voice-data-management/index.html || exit 1
test -f site/services/microsoft-foundry/voice-data-management/azure-storage/index.html || exit 1
test ! -e site/services/microsoft-foundry/voice-data-management/business-patterns/index.html || exit 1

for anchor in \
  product-storage-comparison business-use-cases jurisdiction-rules \
  alexa-deletion-case voice-record-types raw-audio-retention \
  deletion-completion transcript-summary-quality voice-biometric-attacks \
  microsoft-record-locations gaming-public-identity; do
  if ! rg -n -F -- "id=\"$anchor\"" \
    site/services/microsoft-foundry/voice-data-management/index.html; then
    printf 'Missing required anchor: %s\n' "$anchor" >&2
    exit 1
  fi
done
```

Expected: root and Azure pages exist, the unpublished child path is absent,
and all retained anchors are present. Removing any one required anchor must
make the probe exit nonzero.

- [ ] **Step 3: Review changes**

Run:

```bash
git diff --check origin/main...HEAD
git status --short
git --no-pager diff --name-status origin/main...HEAD
```

Expected: no whitespace errors, a clean worktree, and changes limited to the
voice-data topic plus project specs/plans.

Request one read-only review of the complete change. Fix every Critical or
Important factual-boundary issue before publication.

- [ ] **Step 4: Update the PR body**

The review table must contain exactly:

```markdown
| Document | Review link |
|---|---|
| 앱 음성 서비스 기록관리 사례와 정책 | [Open business and policy research](https://github.com/hellices/devguidesample/blob/docs/voice-data-research-2026-10-17/docs/services/microsoft-foundry/voice-data-management/index.md) |
| Microsoft 공식 문서로 본 Azure 음성 에이전트 데이터 저장 | [Open Azure storage research](https://github.com/hellices/devguidesample/blob/docs/voice-data-research-2026-10-17/docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md) |
```

Keep both SVG previews. Add summary bullets:

```markdown
- collapse the summary-only landing page into the business and policy topic root, leaving two substantive pages
- lead with the open cross-product retention comparison and exact statutory periods
- expand the Amazon Alexa case into complaint allegations and filed-order remedies
- compress generic implementation guidance into secondary appendices
```

- [ ] **Step 5: Push and wait for CI**

Run:

```bash
git fetch origin
git rev-list --left-right --count \
  HEAD...origin/docs/voice-data-research-2026-10-17
git push origin HEAD
```

Expected before push: zero incoming commits. Wait for the new workflow run and
require `completed success`.

- [ ] **Step 6: Confirm final state**

Run:

```bash
git fetch origin
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

Requery review threads and require a final unresolved count of `0`.
