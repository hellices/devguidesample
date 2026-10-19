# Final Voice Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the last factual and clarity corrections, close all review threads with remote evidence, and request final human review from daeun go.

**Architecture:** Keep the two-page topic unchanged. Correct product and Azure wording in place, separate the roles of the front questions and later responsibility table, repair internal implementation plans, then run local review, push, CI, GitHub review rounds, and human reviewer assignment.

**Tech Stack:** Markdown, SVG, MkDocs Material, Python 3.13, pytest, GitHub CLI, GitHub GraphQL API

## Global Constraints

- Do not add GPT-Live to the Azure diagrams or product comparison.
- Do not infer Xbox 90-day/two-year voice-report retention without a direct primary source.
- Do not state that HMRC deletes source audio immediately when its cited notice does not state that timing.
- Keep product, law, and Alexa tables open.
- Keep detailed cases and secondary product material collapsed.
- Preserve every stable public anchor.
- Keep `verification_status: needs-review`.
- Resolve GitHub threads only after the supporting commit is pushed and CI/diff evidence is available.
- Request daeun go as reviewer only after CI passes and unresolved thread count is zero.
- Include `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` in every implementation commit.

---

### Task 1: Correct public facts and simplify wording

**Files:**
- Modify: `docs/services/microsoft-foundry/voice-data-management/index.md`
- Modify: `docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md`
- Modify: `docs/services/microsoft-foundry/voice-data-management/images/azure-voice-agent-realtime-architectures.svg`

**Interfaces:**
- Consumes: current Apple, Azure Storage, Voice Live, OpenAI GPT-Live, Xbox, and HMRC official pages.
- Produces: corrected public prose and one simplified SVG label used by Task 3.

- [ ] **Step 1: Correct the Siri row**

Use:

```markdown
| **Siri·Dictation / Apple 정책, 2026-09-14** | 지원 구성은 단말 처리; 개선 미동의 시 Apple 오디오 미저장 | 요청 이력은 시간당 여러 번 바뀌는 임의의 기기 생성 식별자와 연결되며 최대 2년 보유·이용 가능. 검토된 일부 자료는 2년 초과 보유 예외. [일반 정책](https://www.apple.com/legal/privacy/data/en/ask-siri-dictation/) · [개선 참여 정책](https://www.apple.com/legal/privacy/data/en/improve-siri-dictation/) |
```

Remove every `6개월 연결` or sequential identifier-separation statement.

- [ ] **Step 2: Correct Voice Live model terminology**

Replace the Azure prose with:

```markdown
Realtime 모델을 선택하면 네이티브 경로를, GPT-4.1·GPT-5 계열처럼
이 경로에서 텍스트 입력·출력을 사용하는 모델을 선택하면 Azure 음성
인식과 음성 합성을 결합한 분리형 경로를 사용할 수 있습니다.
```

In the realtime SVG, replace:

```text
분리형 PIPELINE · Voice Live + 비멀티모달 모델 또는 애플리케이션 조합
```

with:

```text
분리형 PIPELINE · Voice Live + 텍스트 입출력 모델 또는 애플리케이션 조합
```

- [ ] **Step 3: Add the GPT-Live boundary**

Near the Azure page's header scope, add:

```markdown
> - API 경계: 이 문서는 Azure OpenAI Realtime과 Azure Voice Live를 다룹니다. [OpenAI 직접 API인 GPT-Live](https://developers.openai.com/api/docs/guides/live)의 음성 대화·백엔드 위임 구조는 별도이며, Azure 지원 여부와 데이터 정책을 공유한다고 가정하지 않습니다.
```

- [ ] **Step 4: Simplify realtime diagram attribution**

In the SVG, use exactly:

```text
공식 문서를 기반으로 한 종합 구성 예시
```

In Azure prose, use:

```markdown
> **그림 성격:** 공식 문서를 기반으로 한 종합 구성 예시입니다.
> 점선은 저장·추적을 정책과 설정으로 선택하는 별도 경로입니다.
```

Remove `Microsoft 제공 단일 그림 아님` and the equivalent defensive sentence.

- [ ] **Step 5: Add Blob lifecycle prerequisites**

In the lifecycle section, change the opening to:

```markdown
[Blob 수명주기 관리](https://learn.microsoft.com/en-us/azure/storage/blobs/lifecycle-management-overview)는
생성·수정 시각, 경로 prefix와 blob tag를 기준으로 계층 이동·삭제 규칙을
정의할 수 있다고 설명합니다. 마지막 접근 시각 조건을 사용하려면 storage
account에서 last access time tracking을 먼저 켜야 하며, 기본 활성화로
가정하지 않습니다.
```

- [ ] **Step 6: Add access-tier account conditions**

Immediately below the access-tier table, add:

```markdown
Cool 30일·Cold 90일은 **general-purpose v2(GPv2) 계정**에서 조기 삭제
과금을 계산하는 최소 보관기간입니다. legacy Blob Storage 계정의 Cool에는
최소 보관기간이 없습니다. Cold는 GPv2 계정에서만 지원됩니다. 이 값은
과금 기준이며 법정 보유기간이 아닙니다.
```

Keep the Archive 180-day explanation and existing legal/billing boundary.

- [ ] **Step 7: Separate the two business tables**

Rename:

```markdown
## 비즈니스가 먼저 결정할 기록
```

to:

```markdown
<a id="비즈니스가-먼저-결정할-기록"></a>

## 먼저 확인할 세 가지 질문
```

Delete its five-row decision table. Keep only the three anchored H3 questions
and their one-sentence answers. The empty anchor preserves the former generated
fragment after the heading changes.

Rename:

```markdown
## 기록·삭제 결정 체크리스트
```

to:

```markdown
<a id="기록-삭제-결정-체크리스트"></a>

## 기록별 담당·정책·삭제 증빙
```

Keep the lifecycle SVG and replace the later table with:

```markdown
| 기록 | 담당자 예시 | 정책에 고정할 값 | 삭제 확인 자료 |
|---|---|---|---|
| **입력·출력 오디오** | 서비스·녹음 담당 | 목적, 캡처 방식, 저장소·지역, 기산점, 기간 | 객체·버전 삭제 로그, 처리자 삭제 확인, 백업 만료 기록 |
| **전사문·요약** | 상담기록·사건 담당 | 원음 연결, 정정 버전, 검색 사본, 기산점·기간 | DB·티켓·색인 삭제, 키워드·의미 검색 미반환 |
| **이벤트·업무 결과** | 제품·업무 시스템 담당 | 이벤트 ID, 권위 있는 결과, 법정 기록 분류 | 이벤트·업무 기록 삭제 또는 별도 보존 근거 |
| **voiceprint** | 인증·보안 담당 | 동의, 등록 원음, 템플릿, 마지막 상호작용, 적용 법령 | 등록 원음·템플릿 삭제 감사 로그 |
| **trace·검색·반출 사본** | 운영·보안·데이터 담당 | 수집 필드, 접근권한, 지역, 기간, 하류 사본 | 만료 작업, 접근 기록, 색인·캐시·반출본 삭제 |
```

Add below the table:

```markdown
재생 불가·인증 불가는 기능 검증 결과일 뿐 단독 삭제 증빙이 아닙니다.
삭제 완료는 객체·버전·등록 원음·템플릿 삭제 로그처럼 저장소 상태를 직접
확인하는 자료로 입증합니다.
```

- [ ] **Step 8: Narrow Xbox and HMRC evidence**

For Xbox, keep the 24 online-hour console rule and add:

```markdown
제출하면 콘솔 사본은 조사 증거로 전달되며, 인용한 공식 자료는 제출 뒤
Xbox 서버의 원음 보유기간을 명시하지 않습니다.
```

Do not add 90 days or two years.

For HMRC, state:

```markdown
가입 음성을 voiceprint로 변환합니다. 인용 고지는 원음 녹음의 별도 삭제
시점을 명시하지 않습니다.
```

Limit the 3-year consent refresh, up-to-7-year retention, UK data-center
storage, and consent-withdrawal deletion statements to `voiceprint`.

- [ ] **Step 9: Verify public corrections**

Run:

```bash
../../.venv/bin/python - <<'PY'
from pathlib import Path
import re

root = Path(
    "docs/services/microsoft-foundry/voice-data-management/index.md"
).read_text(encoding="utf-8")
azure = Path(
    "docs/services/microsoft-foundry/voice-data-management/azure-storage/index.md"
).read_text(encoding="utf-8")
svg = Path(
    "docs/services/microsoft-foundry/voice-data-management/images/azure-voice-agent-realtime-architectures.svg"
).read_text(encoding="utf-8")
root_text = re.sub(r"\s+", " ", root)
azure_text = re.sub(r"\s+", " ", azure)
siri_start = root.index("| **Siri·Dictation")
siri_end = root.index("\n\n", siri_start)
siri_row = root[siri_start:siri_end]
xbox_start = root.index("| **Xbox 음성 신고")
xbox_end = root.index("\n| **HMRC Voice ID", xbox_start)
xbox_row = root[xbox_start:xbox_end]
hmrc_start = xbox_end + 1
hmrc_end = root.index("\n\n", hmrc_start)
hmrc_row = root[hmrc_start:hmrc_end]
hmrc_cells = [cell.strip() for cell in hmrc_row.split("|")[1:-1]]
assert len(hmrc_cells) == 4
hmrc_processing = hmrc_cells[1]
hmrc_retention = hmrc_cells[2]
questions_start = root.index("## 먼저 확인할 세 가지 질문")
questions_end = root.index("## 업무별 저장 방식", questions_start)
questions_section = root[questions_start:questions_end]
owners_start = root.index("## 기록별 담당·정책·삭제 증빙")
owners_end = root.index("## 추가 검증·제품 자료", owners_start)
owners_section = root[owners_start:owners_end]
owners_table_start = owners_section.index("| 기록 |")
owners_table_end = owners_section.index("\n\n", owners_table_start)
owners_table = owners_section[owners_table_start:owners_table_end]

assert "6개월 연결" not in siri_row
assert "식별자 분리" not in siri_row
assert "시간당 여러 번 바뀌는" in siri_row
assert "서버의 원음 보유기간을 명시하지 않습니다" in xbox_row
assert "원음 녹음의 별도 삭제 시점을 명시하지 않습니다" in root_text
assert "90일" not in xbox_row
assert "2년" not in xbox_row
assert "원음 녹음의 별도 삭제 시점을 명시하지 않습니다" in hmrc_processing
for phrase in ["3년", "7년", "영국 데이터센터", "동의 철회"]:
    assert phrase not in hmrc_processing
assert hmrc_retention.startswith("**voiceprint**는 영국 데이터센터에 저장.")
for phrase in ["3년", "최대 7년", "동의 철회", "생체정보 삭제"]:
    assert phrase in hmrc_retention
assert "비멀티모달" not in azure + svg
assert "텍스트 입력·출력을 사용하는 모델" in azure_text
assert "OpenAI 직접 API인 GPT-Live" in azure
assert "last access time tracking" in azure
assert "general-purpose v2(GPv2)" in azure
assert "legacy Blob Storage" in azure
assert "Microsoft 제공 단일 그림 아님" not in azure + svg
assert "Microsoft가 제공한 단일 그림이 아니며" not in azure
assert "공식 문서를 기반으로 한 종합 구성 예시" in svg
assert "공식 문서를 기반으로 한 종합 구성 예시입니다." in azure_text
assert "점선은 저장·추적을 정책과 설정으로 선택하는 별도 경로입니다." in azure_text
assert "## 먼저 확인할 세 가지 질문" in root
assert "## 기록별 담당·정책·삭제 증빙" in root
assert '<a id="비즈니스가-먼저-결정할-기록"></a>' in root
assert '<a id="기록-삭제-결정-체크리스트"></a>' in root
assert "| 결정 | 필요한 근거 |" not in questions_section
assert questions_section.count("### ") == 3
for heading in ["어떤 기록인가?", "왜·얼마나 보관하는가?", "무엇을 함께 지우는가?"]:
    assert heading in questions_section
assert "| 기록 | 담당자 예시 | 정책에 고정할 값 | 삭제 확인 자료 |" in owners_section
for record in ["입력·출력 오디오", "전사문·요약", "이벤트·업무 결과", "voiceprint", "trace·검색·반출 사본"]:
    assert f"| **{record}** |" in owners_section
assert "재생 불가" not in owners_table
assert "인증 불가" not in owners_table
assert "기능 검증 결과일 뿐 단독 삭제 증빙이 아닙니다" in owners_section
PY
```

- [ ] **Step 10: Run focused gates and commit**

Run:

```bash
python3 ~/.agents/skills/diagram-design/scripts/self_check.py \
  docs/services/microsoft-foundry/voice-data-management/images/azure-voice-agent-realtime-architectures.svg
xmllint --noout \
  docs/services/microsoft-foundry/voice-data-management/images/azure-voice-agent-realtime-architectures.svg
../../.venv/bin/python scripts/docs/validate_links.py
../../.venv/bin/python -m mkdocs build --strict
```

Commit:

```bash
git add docs/services/microsoft-foundry/voice-data-management
git commit -m "docs(foundry): clarify final voice evidence" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Repair internal plans and review sequencing

**Files:**
- Modify: `project/plans/2026-10-18-voice-research-architecture-restructure.md`
- Modify: `project/plans/2026-10-19-two-page-voice-research-topic.md`
- Modify: `project/plans/2026-10-19-voice-business-evidence.md`

**Interfaces:**
- Consumes: the current branch and review-thread evidence.
- Produces: self-contained execution plans and no contradictory review/push order.

- [ ] **Step 1: Add preview-server lifecycle**

Before the first browser review in the 2026-10-18 plan, add the server command
and require it to be started in async mode through the execution harness:

```bash
../../.venv/bin/mkdocs serve --dev-addr 127.0.0.1:8124
```

Then add this separate readiness probe:

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

State that the server command runs as a separate bounded async process. Record
both its shell ID and exact PID, export the PID as `preview_pid` before the
probe, and stop the process through its recorded shell ID or exact PID after
the last browser check. Do not use `pkill` or `killall`.

- [ ] **Step 2: Move review-thread resolution after push**

In the 2026-10-18 plan's final task, order the steps:

1. complete local validation;
2. obtain publication authorization;
3. push commits;
4. wait for CI and inspect the remote diff;
5. reply to and resolve review threads with commit/build evidence; and
6. confirm final state.

Remove any instruction to resolve remote threads before push.

- [ ] **Step 3: Correct the Alexa assertion**

In `2026-10-19-voice-business-evidence.md`, require the actual table string:

```python
"명령 입력 후 **6개월 이내** 구축"
```

Do not require the absent string `**6개월 이내** 식별 절차`.

- [ ] **Step 4: Correct the two-page browser-step title**

Rename:

```text
Browser-check both pages and the redirect
```

to:

```text
Browser-check both pages
```

Keep the no-redirect contract.

- [ ] **Step 5: Document absent evidence artifacts**

Add this final assertion to the 2026-10-18 plan:

```bash
test ! -e docs/services/microsoft-foundry/voice-data-management/samples/source-evidence
```

State that no deletion task is needed because the path is absent from the
current branch and `origin/main...HEAD` diff.

- [ ] **Step 6: Commit plan repairs**

```bash
git add project/plans
git commit -m "docs(foundry): repair voice review plans" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Validate, review, publish, and request daeun go

**Files:**
- Verify: `docs/services/microsoft-foundry/voice-data-management/`
- Update: pull request `hellices/devguidesample#83`

**Interfaces:**
- Consumes: public and internal-plan commits from Tasks 1-2.
- Produces: passing local/remote validation, resolved bot feedback, and a
  human-review request.

- [ ] **Step 1: Run complete validation**

Run the repository's full documentation contract:

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

Verify the two former generated fragments in the built root:

```bash
../../.venv/bin/python - <<'PY'
from pathlib import Path

html = Path(
    "site/services/microsoft-foundry/voice-data-management/index.html"
).read_text(encoding="utf-8")
for legacy_anchor in [
    "비즈니스가-먼저-결정할-기록",
    "기록-삭제-결정-체크리스트",
]:
    assert f'id="{legacy_anchor}"' in html
PY
```

- [ ] **Step 2: Browser-check desktop and 390px**

Always start `../../.venv/bin/mkdocs serve --dev-addr 127.0.0.1:8124` from the
current worktree as a separate bounded async process through the execution
harness. Record both its shell ID and exact PID, export the PID as
`preview_pid`, and verify readiness from a separate probe shell:

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

Verify:

- simplified realtime label;
- GPT-Live boundary text;
- Siri row;
- GPv2/legacy tier condition;
- front three questions;
- later responsibility/evidence table;
- Xbox/HMRC scope; and
- no horizontal page overflow.

Use the dedicated `http://127.0.0.1:8124/devguidesample/` URLs for browser
checks, then stop the process through its recorded shell ID or exact PID. Do
not use `pkill` or `killall`.

- [ ] **Step 3: Run read-only review round**

Request one review over the commit range starting at `7fc5e22`. Fix all
Critical or Important findings. Repeat only when the first review finds such a
finding; do not relaunch when the review is clean.

After each fix, rerun the affected tests and document probes. If Markdown,
SVG, styles, or rendering changed, rebuild the preview and repeat Step 2 at
desktop and 390px before continuing the review.

After the final review fix, rerun all of Step 1, then repeat Step 2 on the
final working tree. Any later edit invalidates these results and requires the
same final validation and browser checks again. Stop before Step 4 if either
gate fails; remote CI is additional evidence, not a replacement for local
validation or browser review.

If review fixes changed files, commit them before Step 4:

```bash
git add -A
git commit -m "docs(foundry): address final voice review" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Require a clean working tree and record the exact reviewed revision:

```bash
test -z "$(git status --porcelain=v1)"
verified_sha=$(git rev-parse HEAD)
```

- [ ] **Step 4: Push and wait for CI**

Require fresh Step 1 and Step 2 results for the exact final revision. Fetch
the PR branch, require zero incoming commits, push, and require the workflow
conclusion `success`.

Before push:

```bash
test -z "$(git status --porcelain=v1)"
test "$(git rev-parse HEAD)" = "$verified_sha"
```

- [ ] **Step 5: Reply to GitHub threads**

After push and CI:

- reply to factual threads with the commit and source;
- push back on Xbox 90-day/two-year and HMRC immediate-audio-deletion claims
  with the linked-source text and the narrower replacement wording;
- show `git diff --name-status origin/main...HEAD` evidence that
  `samples/source-evidence` is absent;
- reply to plan fixes with their commit; and
- resolve each addressed thread.

Require unresolved thread count `0`.

- [ ] **Step 6: Discover daeun go's GitHub login**

Query repository collaborators and GitHub users:

```bash
GH_PAGER=cat gh api repos/hellices/devguidesample/collaborators --paginate
GH_PAGER=cat gh api -X GET search/users -f q='\"Daeun Go\" in:fullname'
```

Select a reviewer only when one unique account matches the requested person
and has repository review access. If no unique match exists, stop and request
the login instead of guessing.

- [ ] **Step 7: Request human review**

Run:

```bash
search_candidates=$(GH_PAGER=cat gh api -X GET search/users \
  -f q='"Daeun Go" in:fullname' \
  --jq '[.items[].login] | unique | .[]')
collaborators=$(GH_PAGER=cat gh api \
  repos/hellices/devguidesample/collaborators \
  --paginate --jq '.[].login')
review_candidates=""
for login in $search_candidates; do
  if printf '%s\n' "$collaborators" | grep -Fxq "$login"; then
    review_candidates="${review_candidates}${review_candidates:+
}$login"
  fi
done
candidate_count=$(printf '%s\n' "$review_candidates" | sed '/^$/d' | wc -l | tr -d ' ')
test "$candidate_count" -eq 1
reviewer_login="$review_candidates"
GH_PAGER=cat gh api \
  "repos/hellices/devguidesample/collaborators/$reviewer_login" \
  --silent
permission=$(GH_PAGER=cat gh api \
  "repos/hellices/devguidesample/collaborators/$reviewer_login/permission" \
  --jq '.permission')
case "$permission" in
  admin|maintain|write|triage|read) ;;
  *) echo "Reviewer lacks repository access" >&2; exit 1 ;;
esac
GH_PAGER=cat gh pr edit 83 --add-reviewer "$reviewer_login"
```

Verify the requested reviewer through the PR API.

- [ ] **Step 8: Confirm final state**

Require:

- clean worktree;
- branch divergence `0 0`;
- PR `validate` pass;
- unresolved review threads `0`; and
- daeun go present in requested reviewers.
