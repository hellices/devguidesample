# Voice Research Architecture Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe the published voice-data research around current native realtime, cascaded, and post-call architectures while preserving the existing case evidence, retention boundaries, stable URLs, and review history.

**Architecture:** Keep the existing three-page topic package. The overview establishes the reading order, the Azure child page owns architecture and product behavior, and the business child page owns public cases, policy dates, and record-reliability evaluation. Two separate local SVGs distinguish an authored realtime comparison from a restatement of Microsoft's post-call reference; persistence, PII, processing scope, and tracing remain explicit side paths rather than implied defaults.

**Tech Stack:** Markdown, YAML front matter, SVG, MkDocs Material, Python 3.13, pytest, GitHub CLI

## Global Constraints

- Preserve `published_at: 2026-10-17` as the original publication date.
- Set the revised source-check date and visible architecture/product verification date to `2026-10-18`.
- Preserve the existing public topic and child URLs.
- Preserve existing stable explicit anchors or provide an equivalent redirecting link target in the same page.
- Keep Voice Live described as a managed API that can expose native realtime or cascaded processing, not as a model architecture.
- Keep native speech-to-speech, cascaded STT → text model → TTS, and post-call batch analysis separate.
- Keep Microsoft-provided figures and locally authored diagrams explicitly distinguished.
- Do not infer a customer architecture, current migration, private setting, retention period, GA status, or preview status that a cited source does not state.
- Keep `verification_status: needs-review` for claims that cannot complete the repository's `verify-with-microsoft-learn` workflow.
- Do not publish a source-evidence ledger or downloadable evidence artifact.
- Keep capacity, throughput, codec, access-tier, restore, and latency details as supplementary material after the architecture and record-control sections.
- Include `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` in every implementation commit.

## File Structure

- Modify `docs/services/microsoft-foundry/voice-data-management/index.md`: current architecture map, reading order, and topic-level evidence boundary.
- Modify `docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md`: architecture-first Azure research, structure-by-record matrix, processing scopes, PII stages, post-call reference, and supplementary details.
- Modify `docs/services/microsoft-foundry/voice-data-management/business-patterns/index.md`: per-case public timing and architecture-aware record-reliability evaluation.
- Create `docs/services/microsoft-foundry/voice-data-management/images/azure-voice-agent-realtime-architectures.svg`: locally authored native-versus-cascaded realtime comparison.
- Modify `docs/services/microsoft-foundry/voice-data-management/images/azure-voice-agent-ms-reference-architecture.svg`: post-call-only restatement of the Microsoft reference architecture.
- Keep `project/specs/2026-10-18-voice-research-architecture-restructure-design.md`: governing implementation decisions.

---

### Task 1: Reframe the topic overview and dated evidence boundary

**Files:**
- Modify: `docs/services/microsoft-foundry/voice-data-management/index.md:1-68`
- Modify: `docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md:1-62`
- Modify: `docs/services/microsoft-foundry/voice-data-management/business-patterns/index.md:1-43`

**Interfaces:**
- Consumes: the date, evidence, architecture, and non-goal rules in `project/specs/2026-10-18-voice-research-architecture-restructure-design.md`.
- Produces: topic-level terms and reading order used by Tasks 2-4: `네이티브 Realtime`, `분리형 파이프라인`, `통화 후 분석`, `공식 문서를 기반으로 한 종합 구성 예시`, and `Microsoft 공식 참조 아키텍처`.

- [ ] **Step 1: Confirm the implementation worktree and Python**

Run:

```bash
git status --short
git branch --show-current
../../.venv/bin/python --version
```

Expected:

```text
# git status: no output
docs/voice-data-research-2026-10-17
Python 3.13.x
```

- [ ] **Step 2: Recheck the architecture sources**

Use the repository `verify-with-microsoft-learn` workflow if it is available. If
that workflow is unavailable, retrieve the complete official pages directly,
retain `verification_status: needs-review`, and do not describe the source
verification as complete.

Check these exact claims:

| Claim | Required official source |
|---|---|
| Voice Live is one managed API and supports Realtime models plus text-input/output model paths that combine STT and TTS | `https://learn.microsoft.com/azure/ai-services/speech-service/voice-live` |
| Voice Live speech features and LLMs have separate processing scopes | `https://learn.microsoft.com/azure/ai-services/speech-service/regions?tabs=voice-live` |
| GPT Realtime is speech-in/speech-out and optional input transcription uses a deployment | `https://learn.microsoft.com/azure/foundry/openai/how-to/realtime-audio` |
| Voice-agent `store` defaults to false and is session-overridable | `https://learn.microsoft.com/azure/foundry/agents/how-to/configure-voice-agent` |
| The call-center reference is post-call batch analysis | `https://learn.microsoft.com/azure/architecture/ai-ml/openai/architecture/call-center-openai-analytics` |
| Conversation PII and Text PII have different language support | `https://learn.microsoft.com/azure/ai-services/language-service/personally-identifiable-information/language-support` |

Expected: each published claim has a matching source scope, date, feature, and
version note; unsupported claims are removed or explicitly marked
`확인되지 않음`.

- [ ] **Step 3: Update source dates and official-source metadata**

In all three Markdown files:

```yaml
sources_checked_at: 2026-10-18
published_at: 2026-10-17
verification_status: needs-review
```

Add Voice Live and Realtime sources to the overview's `official_sources`.
Add Voice Live regions, voice-agent configuration, Foundry tracing,
Conversation PII, and PII language support to the Azure child's
`official_sources`.

Do not change the business document's existing `2026-10-14` case-policy date
or `2026-10-10` legal-review date.

- [ ] **Step 4: Replace the overview reading order**

Insert this architecture matrix before `## 핵심 관찰`:

```markdown
## 2026년 기준으로 어떤 구조부터 읽어야 하는가?

| 구조 | 실시간 핵심 흐름 | 기록관리에서 구분할 점 |
|---|---|---|
| **네이티브 Realtime** | 음성 ↔ 음성 처리 모델 ↔ 도구·업무 시스템 | 모델이 오디오를 직접 처리하며, 선택 전사는 별도 보조 기록일 수 있음 |
| **분리형 파이프라인** | STT → 텍스트 모델·에이전트 → TTS | 모델 입력 텍스트와 각 단계의 로그·사본을 구분 |
| **통화 후 분석** | 보관 원음·전사 → PII·분석 → 결과 저장 | 실시간 세션과 목적·실행 시점·보유 정책이 독립적 |

Voice Live는 별도 모델 유형이 아니라 여러 모델·음성 기능을 하나의
인터페이스로 제공하는 관리형 API입니다. 선택한 모델에 따라 네이티브
Realtime 또는 분리형 처리가 사용될 수 있습니다.
```

Follow it with this reading order:

```markdown
1. Azure 문서에서 현재 실시간 구조와 구조별 기록을 먼저 확인합니다.
2. 통화 후 분석은 실시간 처리와 분리된 별도 흐름으로 읽습니다.
3. 업무 사례는 공개된 도입·정책 시점의 근거이며 현재 구조를 추정하지 않습니다.
```

- [ ] **Step 5: Rewrite the five core observations**

The observations must state, in this order:

1. architecture determines which component handles audio and text;
2. transcripts can be cascaded model input, optional native-path helper
   records, or post-call records;
3. storage is selected through application recording, `store`, tracing,
   support logging, or post-call copies;
4. storage region, speech processing, model inference, support logs, and
   trace storage are separate location questions; and
5. public cases and policies do not reveal private current configurations.

Keep each observation to one or two sentences and retain links to the two child
documents.

- [ ] **Step 6: Run the focused metadata and link gates**

Run:

```bash
../../.venv/bin/python scripts/docs/validate_metadata.py
../../.venv/bin/python scripts/docs/validate_sources.py
../../.venv/bin/python scripts/docs/validate_links.py
```

Expected:

```text
Validated metadata for 80 public documents.
Validated official sources for 80 public documents.
Validated links for 80 public documents.
```

- [ ] **Step 7: Commit the overview boundary**

```bash
git add \
  docs/services/microsoft-foundry/voice-data-management/index.md \
  docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md \
  docs/services/microsoft-foundry/voice-data-management/business-patterns/index.md
git commit -m "docs(foundry): reframe voice research architectures" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: one commit containing only front matter, date, overview, and
top-of-document boundary changes.

---

### Task 2: Separate realtime and post-call diagrams

**Files:**
- Create: `docs/services/microsoft-foundry/voice-data-management/images/azure-voice-agent-realtime-architectures.svg`
- Modify: `docs/services/microsoft-foundry/voice-data-management/images/azure-voice-agent-ms-reference-architecture.svg:1-124`
- Modify: `docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md:48-78`

**Interfaces:**
- Consumes: the three architecture terms established in Task 1.
- Produces: stable diagram files and labels consumed by the Azure document:
  `azure-voice-agent-realtime-architectures.svg` and the existing
  `azure-voice-agent-ms-reference-architecture.svg`.

- [ ] **Step 1: Create the realtime architecture SVG**

Create an accessible SVG with this exact semantic structure:

```xml
<svg role="img"
     aria-labelledby="azure-realtime-architectures-title azure-realtime-architectures-desc">
  <title id="azure-realtime-architectures-title">
    Azure 음성 에이전트의 네이티브 Realtime과 분리형 파이프라인
  </title>
  <desc id="azure-realtime-architectures-desc">
    위쪽은 음성이 Realtime 모델에 직접 들어가는 경로이고, 아래쪽은
    음성 인식, 텍스트 모델 또는 에이전트, 음성 합성을 분리한 경로입니다.
    Voice Live는 두 경로를 제공할 수 있는 관리형 API로 표시하며,
    저장과 추적은 선택 경로로 분리합니다.
  </desc>
</svg>
```

The visible diagram must contain:

- title: `실시간 음성 처리 구조 비교`;
- source label: `공식 문서를 기반으로 한 종합 구성 예시`;
- native lane:
  `단말·전화 → Realtime 음성 모델 → 도구·업무 시스템 → 음성 응답`;
- cascaded lane:
  `단말·전화 → STT → 텍스트 모델·에이전트 → TTS → 음성 응답`;
- a bracket or caption explaining that Voice Live can manage either path
  depending on the selected model;
- optional dotted branches for `선택 전사`, `store`, `추적 로그`, and
  `사후 분석 사본`; and
- no Blob Storage node on the required realtime path.

Reuse the existing diagram's typography, colors, arrow markers, and minimum
12px body text. Use a `1280`-pixel-wide viewBox and keep all labels inside it.

- [ ] **Step 2: Convert the existing SVG to post-call only**

Retain the existing path but change its semantic title to:

```xml
<title id="azure-ms-voice-arch-title">
  Microsoft 통화 후 분석 참조 아키텍처의 처리·저장 흐름
</title>
```

The diagram must start with `녹음 오디오 · Blob` and preserve two separate
lanes:

```text
Speech batch transcription
  → optional raw transcript
  → Conversation PII
  → Foundry model analysis
  → processed results

Content Understanding
  → transcript and extracted results
  → optional application PII step
  → processed results
```

Remove the current realtime zone, `Voice Live · GPT Realtime` node, and dotted
realtime-to-Blob arrow. Label the image:

```text
Microsoft 공식 참조를 작성자가 재도식화 · 공식 원본 링크는 본문 제공
```

- [ ] **Step 3: Replace the Azure document's combined opening**

Add these headings and explicit anchors:

```markdown
## 2026년 기준 실시간 음성 구조 { #realtime-voice-architectures }

### 네이티브 Realtime과 분리형 파이프라인

![네이티브 Realtime과 분리형 음성 파이프라인 비교](../images/azure-voice-agent-realtime-architectures.svg)

## Microsoft 통화 후 분석 참조 { #post-call-architecture }

![Microsoft 통화 후 분석 참조의 처리·저장 흐름](../images/azure-voice-agent-ms-reference-architecture.svg)
```

Immediately above the post-call image, keep direct links to the
Microsoft-provided SVG and Visio. Call those links `Microsoft 공식 그림` and
`Microsoft 제공 Visio`; do not call either local SVG an official Microsoft
figure.

- [ ] **Step 4: Build and inspect both SVGs**

Run:

```bash
../../.venv/bin/python -m mkdocs build --strict
```

Expected: `Documentation built` with exit code 0.

Always start a dedicated preview server from the current worktree:

```bash
../../.venv/bin/mkdocs serve --dev-addr 127.0.0.1:8124
```

Run it as a separate bounded async process through the execution harness.
Record both its shell ID and exact PID, export the PID as `preview_pid`, and
verify readiness from a separate probe shell:

```bash
: "${preview_pid:?Set preview_pid to the exact preview-server PID}"
preview_ready=false
for attempt in {1..30}; do
  if curl -fsS http://127.0.0.1:8124/devguidesample/ >/dev/null; then
    preview_ready=true
    break
  fi
  if ! kill -0 "$preview_pid" 2>/dev/null; then
    echo "Preview server exited before becoming ready" >&2
    exit 1
  fi
  sleep 1
done
test "$preview_ready" = true
```

Keep that exact process for the remaining browser checks, then stop it through
its recorded shell ID or exact PID. Do not use `pkill` or `killall`.

Open:

```text
http://127.0.0.1:8124/devguidesample/services/microsoft-foundry/voice-data-management/azure-storage/
```

Verify:

- the diagrams are separate;
- the first diagram has two realtime lanes;
- the second begins with recorded audio;
- no text is clipped at desktop width;
- at a 390px viewport the SVG remains readable through scaling;
- both accessible names match their visible purpose.

- [ ] **Step 5: Commit the diagram boundary**

```bash
git add \
  docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md \
  docs/services/microsoft-foundry/voice-data-management/images/azure-voice-agent-realtime-architectures.svg \
  docs/services/microsoft-foundry/voice-data-management/images/azure-voice-agent-ms-reference-architecture.svg
git commit -m "docs(foundry): separate realtime and post-call flows" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: one commit containing the two diagram files and their immediate
Azure prose.

---

### Task 3: Connect architectures to records, regions, PII, and persistence

**Files:**
- Modify: `docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md:79-283`

**Interfaces:**
- Consumes: diagram anchors and terminology from Tasks 1-2.
- Produces: the architecture-by-record matrix, five location questions, PII
  stage controls, and the final Azure page order.

- [ ] **Step 1: Add the architecture-by-record matrix**

Place this matrix immediately after the realtime architecture section:

```markdown
## 구조별로 어떤 기록이 생기는가? { #records-by-architecture }

| 기록 | 네이티브 Realtime | 분리형 파이프라인 | 통화 후 분석 |
|---|---|---|---|
| 입력·출력 오디오 | 모델이 직접 처리; 녹음·`store`는 별도 선택 | STT 입력·TTS 출력; 단계별 사본 여부 확인 | 이미 보관된 녹음이 분석 입력 |
| 전사문 | 선택 전사 모델이 만드는 보조 기록일 수 있음 | 텍스트 모델에 전달되는 STT 결과 | 배치 전사 또는 Content Understanding 결과 |
| 대화·도구 이벤트 | conversation item·response·tool event 연결 | STT·모델·TTS 단계와 업무 호출 연결 | 분석 작업·파일·결과 ID 연결 |
| 업무 결과 | 주문·기기 동작·티켓 등 권위 시스템 기록 | 동일 | CRM·보고·분석 결과 |
| 추적·지원 로그 | 기능을 켠 경우 별도 저장 | 기능을 켠 경우 별도 저장 | 파이프라인·Functions·Storage 로그 |
| 분석 사본 | 실시간 경로 밖에서 별도 생성 | 실시간 경로 밖에서 별도 생성 | 원음·전사·분석 결과를 독립 보관 |
```

Follow it with:

```markdown
전사문을 하나의 의미로 다루지 않습니다. 네이티브 경로의 선택 전사는
별도 배포가 만든 보조 기록이고, 분리형 경로의 STT 결과는 텍스트 모델
입력일 수 있으며, 통화 후 전사는 이미 끝난 세션을 다시 처리한 기록입니다.
```

- [ ] **Step 2: Replace the flat service-storage table with control groups**

Keep every current fact, but group rows under these labels:

```markdown
### 실시간 세션 저장
- Voice Live API default non-retention
- Voice Live opt-in support logs
- Foundry voice agent `store=false`
- per-session `store` query override

### 연결 모델과 관측성
- stateful model features
- abuse monitoring
- Foundry tracing in connected Application Insights and Log Analytics

### 배치 전사와 사후 분석
- `contentContainerUrl` / `contentUrls`
- `destinationContainerUrl`
- `timeToLiveHours`
- customer-owned copies
```

State the voice-agent behavior exactly:

```markdown
`store=false`이면 대화가 영속화되지 않습니다. `store=true`이면 전사문,
이벤트 시간선과 원음이 함께 저장되며 별도 오디오 저장 스위치는 없습니다.
연결 요청의 `store` 쿼리 매개변수로 한 세션만 재정의할 수 있습니다.
```

- [ ] **Step 3: Add the five location questions**

Create:

```markdown
## 저장 위치와 처리 위치는 왜 다른가? { #storage-and-processing-scope }

1. 애플리케이션이 원음·파생 기록을 저장하는 리전
2. STT·TTS 같은 음성 기능의 처리 범위
3. 선택 모델의 추론 범위
4. 선택 지원 로그의 저장 위치
5. Application Insights·Log Analytics 추적 저장 위치
```

Include this boundary:

```markdown
한국 리전 Blob Storage에 원음을 저장해도 Voice Live의 음성 기능, 선택한
LLM 추론, 지원 로그와 추적 데이터까지 모두 국내에서만 처리·저장된다는
뜻은 아닙니다. Voice Live 리전 표에서 음성 기능과 LLM의 Global,
Data Zone, Regional 범위를 각각 확인해야 합니다.
```

Do not reproduce the full volatile region matrix. Link the current Microsoft
table and give `koreacentral` only as a dated example if both speech and model
scope values are copied with `2026-10-18 기준`.

- [ ] **Step 4: Add PII controls by stage**

Create:

```markdown
## PII는 어느 처리 단계에서 통제하는가? { #pii-by-stage }

| 경로 | PII 통제 시점 | 통제가 되돌리지 못하는 범위 |
|---|---|---|
| 네이티브 Realtime | 모델 처리 뒤 선택 전사·출력·저장 단계 | 모델에 이미 전달된 원음 |
| 애플리케이션 분리형 | STT 뒤, 텍스트 모델 전달 전 적용 가능 | 원음과 별도 음성 사본 |
| Voice Live 관리형 분리 경로 | 문서가 공개한 지원 통제만 적용 | 내부 단계에 임의 통제를 삽입했다고 가정하지 않음 |
| 통화 후 Speech 경로 | 배치 전사 뒤, Foundry 모델 전달 전 Conversation PII | 원음 Blob |
| Content Understanding 경로 | 추출 결과 반환 뒤 애플리케이션 단계 | 서비스에 이미 전달된 원음 |
```

Add these explicit statements:

```markdown
- 전사문 마스킹은 원음 마스킹·삭제가 아닙니다.
- 사후 마스킹은 이미 완료된 모델 전송을 되돌리지 않습니다.
- Conversation PII가 주는 오디오 타이밍은 원음의 민감 구간을 처리할
  근거이며 저장된 원음을 자동 삭제했다는 뜻이 아닙니다.
- 2026-10-18 확인 기준 Text PII는 한국어를 지원하지만 Conversation PII
  `2024-11-01` GA 언어 목록은 영어·프랑스어·독일어·스페인어입니다.
```

Preserve the source discrepancy:

```markdown
Architecture Center 본문은 Conversation PII를 preview로 표기하지만,
언어 지원 문서는 `2024-11-01` GA를 별도로 제시합니다. 이 문서는 두
자료의 버전·표기를 병기하며 하나의 무조건적인 상태로 합치지 않습니다.
```

- [ ] **Step 5: Move the post-call and supplementary sections**

Ensure the Azure page order is:

```text
Basis and architecture map
Realtime architectures
Records and persistence
Storage and processing scope
PII by stage
Post-call reference
Storage lifecycle and deletion constraints
Supplement: formats and compression
Supplement: calculated capacity
Supplement: latency and connection guidance
Supplement: Blob/Data Lake targets and access tiers
```

Move current sections without weakening their source qualifications. Keep the
Blob lifecycle explanation that 24 hours is not a deletion-completion
guarantee and that soft delete, versions, snapshots, and immutability remain
separate controls.

- [ ] **Step 6: Run the Azure page gates**

Run:

```bash
../../.venv/bin/python scripts/docs/validate_sources.py
../../.venv/bin/python scripts/docs/validate_links.py
../../.venv/bin/python scripts/docs/validate_public_safety.py
../../.venv/bin/python -m mkdocs build --strict
```

Expected: all commands exit 0 and strict build reports `Documentation built`.

- [ ] **Step 7: Commit record and control boundaries**

```bash
git add docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md
git commit -m "docs(foundry): connect voice records to architecture" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: one Azure-content commit with no SVG or business-case changes.

---

### Task 4: Add case timing and architecture-aware reliability checks

**Files:**
- Modify: `docs/services/microsoft-foundry/voice-data-management/business-patterns/index.md:90-635`

**Interfaces:**
- Consumes: architecture terms and record distinctions from Tasks 1 and 3.
- Produces: one `공개 시점` field per detailed case and the quality-evaluation
  checklist linked from the six-pattern summary.

- [ ] **Step 1: Add a public-timing field to every detailed case**

For each of these case headings, insert `- **공개 시점:**` after the
`업체·업무` or equivalent identity line:

```text
Microsoft Disability Answer Desk × Be My Eyes
Alexa Shopping
Samsung Bixby × SmartThings
LG ThinQ·Smart TV
Dyson Care on Alexa
Samsung Electronics Service
LG Electronics Service AICC
Whirlpool·Wpro
Lemonade
AXA UK
Aviva × Verint
교보생명 × Kakao Enterprise
Bank of America Erica
Duolingo
```

Use one of these exact forms:

```markdown
- **공개 시점:** YYYY-MM-DD 발표. 현재 운영 지속 여부는 인용 자료에서 확인되지 않음.
- **공개 시점:** YYYY년 도입·발표. 월·일과 현재 운영 지속 여부는 인용 자료에서 확인되지 않음.
- **공개 시점:** 미확인. 페이지 접근일을 도입·발표일로 대신하지 않음.
```

Use a date only when the cited source states it. Keep the shared policy-check
date (`2026-10-14`) separate. Do not infer that any case uses native Realtime,
a cascaded pipeline, or post-call analysis unless the cited case exposes that
flow.

- [ ] **Step 2: Extend the transcript and summary reliability matrix**

Add these rows to the existing quality table:

```markdown
| 보조 전사와 모델 해석 | 선택 전사 배포·모델 응답·업무 결과의 차이 | 전사를 네이티브 모델의 실제 내부 입력으로 간주하지 않음 |
| 무발화·저음량 | 빈 구간·저음량·배경음에서 생성된 텍스트 비율 | 제품 결함으로 단정하지 않고 배포별 실패 시험으로 기록 |
| 이벤트 상태 | partial/delta·provider-completed·application-accepted·human-confirmed | 상태를 섞지 않고 확정 주체와 시간을 보존 |
| 이벤트 순서 | event ID·conversation item ID·response ID·tool call ID | 오디오·전사·응답·업무 결과의 연결과 순서 검증 |
| 실시간 조건 | 모델·버전·언어·전화망·코덱·VAD·동시성 | 조건별 p50/p95·오류·사람 연결률을 분리 |
```

Use `partial/delta` only where the selected API emits it. Do not define one
generic `final` event across Speech, Voice Live, and GPT Realtime.

- [ ] **Step 3: Add architecture-specific evaluation guidance**

Insert:

```markdown
**구조별 평가 경계**

- 네이티브 Realtime: 원음 처리, 선택 전사 이벤트, 모델 응답과 도구 실행을
  별도 기록으로 대조합니다.
- 분리형 파이프라인: STT 확정 결과, 텍스트 모델 입력, 모델 출력과 TTS
  출력을 단계별로 대조합니다.
- 통화 후 분석: 실시간 세션과 독립된 작업 ID, 입력 파일, 전사·PII·분석
  결과와 사본 보유기간을 확인합니다.
- 무발화 구간의 텍스트 생성은 시험 항목입니다. 현재 Azure 제품의 확정
  결함이나 발생률로 게시하려면 별도 1차 근거가 필요합니다.
```

Keep the existing PNAS, KEBAP, NIST, and ISO scope statements. Do not transfer
their historical measurements to current Azure models.

- [ ] **Step 4: Update the six-pattern summary**

Under pattern 6, add one concise line:

```markdown
- 구조별 검증: 보조 전사와 모델 해석 · 이벤트 순서와 확정 상태 · 무발화·저음량 시험
```

Do not add a seventh numbered pattern.

- [ ] **Step 5: Run the business page gates**

Run:

```bash
../../.venv/bin/python scripts/docs/validate_metadata.py
../../.venv/bin/python scripts/docs/validate_sources.py
../../.venv/bin/python scripts/docs/validate_links.py
../../.venv/bin/python scripts/docs/validate_public_safety.py
../../.venv/bin/python -m mkdocs build --strict
```

Expected: all commands exit 0; all existing explicit anchors remain in the
built HTML.

- [ ] **Step 6: Inspect the rendered case and quality sections**

At the local preview URL, verify:

- every detailed case has one `공개 시점` line;
- the comparison table remains readable and is not widened by a new date
  column;
- pattern 6 still appears as one numbered heading;
- quality tables do not present silence text as a proven current defect; and
- links to `#transcript-summary-quality` and
  `#voice-biometric-attacks` still open the correct details.

- [ ] **Step 7: Commit case timing and reliability**

```bash
git add docs/services/microsoft-foundry/voice-data-management/business-patterns/index.md
git commit -m "docs(foundry): add voice record reliability checks" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: one business-research commit with no Azure or diagram changes.

---

### Task 5: Complete validation, review, and pull-request update

**Files:**
- Verify: `docs/services/microsoft-foundry/voice-data-management/`
- Update after explicit publication approval: pull request `hellices/devguidesample#83`

**Interfaces:**
- Consumes: all deliverables from Tasks 1-4.
- Produces: verified local branch state, browser evidence, resolved review
  threads, and an updated PR after user authorization.

- [ ] **Step 1: Run the full documentation contract**

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
Validated metadata for 80 public documents.
Validated official sources for 80 public documents.
Validated links for 80 public documents.
Checked 459 public text files for environment-specific identifiers.
Documentation built
Validated search coverage for 80 public documents and 13 tags.
Audited ... all baseline documents mapped and preserved ...
```

Use the actual public-text-file count reported by the command; do not fail only
because adding one SVG changes that count.

- [ ] **Step 2: Run semantic source assertions**

Run:

```bash
topic=docs/services/microsoft-foundry/voice-data-management
for phrase in "관리형 API" "네이티브 Realtime" "분리형 파이프라인" "통화 후 분석"; do
  if ! rg -n -F -- "$phrase" "$topic/index.md"; then
    printf 'Missing overview boundary: %s\n' "$phrase" >&2
    exit 1
  fi
done
for phrase in "store=false" "destinationContainerUrl" "Conversation PII"; do
  if ! rg -n -F -- "$phrase" "$topic/azure-storage/index.md"; then
    printf 'Missing Azure document boundary: %s\n' "$phrase" >&2
    exit 1
  fi
done

rg -n -F -- "공식 문서를 기반으로 한 종합 구성 예시" \
  "$topic/images/azure-voice-agent-realtime-architectures.svg" || exit 1
rg -n -F -- "Microsoft 공식 참조를 작성자가 재도식화" \
  "$topic/images/azure-voice-agent-ms-reference-architecture.svg" || exit 1
```

Expected: every required boundary appears in its specified Markdown or SVG.
Any missing phrase must make the probe exit nonzero, even if all other
phrases are present. Task 2 Step 1 and this probe both use the exact source
label `공식 문서를 기반으로 한 종합 구성 예시`, as adopted in the
[final voice review](2026-10-19-final-voice-review.md). This wording supersedes
the earlier combined label; do not reintroduce that label during implementation.

- [ ] **Step 3: Perform desktop and narrow browser review**

Review:

```text
http://127.0.0.1:8124/devguidesample/services/microsoft-foundry/voice-data-management/
http://127.0.0.1:8124/devguidesample/services/microsoft-foundry/voice-data-management/azure-storage/
http://127.0.0.1:8124/devguidesample/services/microsoft-foundry/voice-data-management/business-patterns/
```

At this plan's execution point, the authored `business-patterns` child owns the
case timing lines from Task 4. Review that child at both viewport widths. A
later plan may promote its body into the topic root and remove the child.

At desktop and 390px viewport widths, verify:

- overview reading order;
- separate realtime and post-call figures;
- architecture-by-record and PII tables;
- supplementary details after core architecture;
- case timing lines;
- stable anchor navigation; and
- no clipped SVG labels or horizontal page overflow beyond table scroll
  containers.

- [ ] **Step 4: Review the branch diff**

Run:

```bash
git fetch origin
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
git status --short
test ! -e docs/services/microsoft-foundry/voice-data-management/samples/source-evidence
test -z "$(git diff --name-only origin/main...HEAD -- \
  docs/services/microsoft-foundry/voice-data-management/samples/source-evidence)"
```

Expected: no whitespace errors; the PR diff remains limited to the
`voice-data-management` topic package and its three SVG assets (the existing
architecture and lifecycle diagrams plus the new realtime comparison), this
design spec, and this plan; and the working tree is clean.
The evidence-ledger path is absent from the current branch, so no deletion task
is required.

- [ ] **Step 5: Inspect unresolved PR review threads**

Run a GitHub GraphQL review-thread query for PR 83 and inspect every unresolved
thread. Plan the required replies and source evidence, but do not reply or
resolve while the implementation commits remain local.

- [ ] **Step 6: Obtain publication authorization**

Present:

- the commit list;
- the local and browser verification results;
- any claims that remain `needs-review`; and
- the exact PR update to be pushed.

Do not push the implementation commits until the user explicitly authorizes
the PR update.

Authorization is a gate, not task completion. After approval, execute Steps 7
and 8 to push the branch, verify the exact pushed SHA, update the PR, and
resolve only evidenced review threads.

- [ ] **Step 7: Push and verify CI after authorization**

Run:

```bash
git fetch origin
git rev-list --left-right --count \
  HEAD...origin/docs/voice-data-research-2026-10-17
pushed_sha=$(git rev-parse HEAD)
git push origin HEAD

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

Expected before push: zero incoming commits. Expected after push: `validate`
for `pushed_sha` passes. If `gh` monitoring times out while that check run
remains in progress, poll the recorded `check_run_id`; do not report a CI
failure unless its conclusion fails.

- [ ] **Step 8: Reply to and resolve review threads**

After the push and passing CI, reply in each inline thread with the supporting
commit, source, built HTML, or validation evidence.

Resolve a thread only when both conditions are true:

- the concern is fixed in the pushed commit, or source/build evidence proves a
  partial-diff false positive; and
- the inline reply contains that commit or evidence.

Leave every other thread, including unresolved `needs-review` claims, open and
return to implementation before Step 9.

Expected: unresolved review thread count is 0.

- [ ] **Step 9: Confirm final state**

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

Requery unresolved review threads and require a final count of `0`.
