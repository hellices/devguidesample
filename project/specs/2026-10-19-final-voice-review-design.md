# Final voice research review design

## Goal

Apply the remaining factual corrections and remove defensive or duplicated
wording without expanding the two-page research into another product survey.

## Product-policy corrections

### Siri and Dictation

Replace the obsolete sequential `6 months linked → identifier removed → two
years` description.

The current Apple policies dated 2026-09-14 state:

- the random device-generated identifier rotates multiple times per hour;
- request history can be retained and used for up to two years; and
- the small reviewed subset may be retained beyond two years.

Link both:

- `https://www.apple.com/legal/privacy/data/en/ask-siri-dictation/`; and
- `https://www.apple.com/legal/privacy/data/en/improve-siri-dictation/`.

Do not infer a six-month identifier-link period.

### Xbox voice reporting

Keep the console-side 24 online-hour rule from the linked feature design.
State that submission deletes or transfers the console evidence into Xbox's
moderation flow, but the linked official sources do not state a server-side
retention period for submitted voice-report evidence.

Do not add 90-day or two-year periods without a primary source that explicitly
applies them to submitted voice-report clips.

### HMRC Voice ID

State that the 3-year consent refresh and up-to-7-year retention apply to the
biometric voiceprint data described by the notice.

The cited notice says HMRC captures voice recordings and converts them to a
voiceprint, but it does not state a separate deletion time for the source
recording. Do not claim immediate source-audio deletion.

## Azure architecture corrections

### Voice Live model wording

Replace `비멀티모달 모델` with `이 경로에서 텍스트 입출력을 사용하는 모델`
in prose. Replace the SVG label with `Voice Live + 텍스트 입출력 모델 또는
애플리케이션 조합`.

The distinction is native audio input/output versus an STT/text/TTS path, not
multimodal versus nonmultimodal.

### GPT-Live boundary

Add one scope sentence near the Azure page header:

```markdown
이 문서는 Azure OpenAI Realtime과 Azure Voice Live를 다룹니다.
[OpenAI 직접 API인 GPT-Live](https://developers.openai.com/api/docs/guides/live)의
음성 대화·백엔드 위임 구조는 별도이며, Azure 지원 여부와 데이터 정책을
공유한다고 가정하지 않습니다.
```

Do not add GPT-Live to the Azure diagrams or product tables.

### Diagram wording

Use only:

```text
공식 문서를 기반으로 한 종합 구성 예시
```

Remove `Microsoft 제공 단일 그림 아님` from the realtime SVG and remove the
corresponding defensive sentence from the Azure prose. Keep the useful
statement that dotted storage and tracing paths are optional.

The post-call diagram can retain concise source attribution to the Microsoft
reference architecture.

### Mobile diagram readability

Keep one SVG source for each diagram. Wrap the three 1280-pixel voice diagrams
in the same scroll-region class while preserving their existing links where
present and all alt text. Desktop rendering continues to fit the content
column. At 760 pixels and below, give each diagram block a 900-pixel minimum
width and contain horizontal scrolling inside the labelled, keyboard-focusable
region. The page itself must not gain horizontal overflow. Derive each
region's accessible name from that diagram's alt text so multiple regions on
the Azure page have unique names.

Do not create mobile-only SVG copies or remove qualifiers to make the diagrams
fit. The treatment is CSS-only apart from the semantic wrappers, requires no
JavaScript, and falls back to the current scaled image if the extra stylesheet
does not load.

## Azure Storage conditions

### Lifecycle last-access rules

State that last-access conditions are usable only when account-level last
access time tracking has been enabled; it is not an automatic default.

### Cool and Cold minimum periods

State directly below the tier table:

- Cool 30 days and Cold 90 days are minimum storage durations used to
  calculate early-deletion charges for general-purpose v2 accounts;
- deletion, overwrite, or movement is possible inside the period, but the
  remaining period can still be billed;
- legacy Blob Storage accounts have no minimum duration for Cool; and
- Cold requires a general-purpose v2 account.

Keep the distinction between billing criteria and legal retention.

## Business-page duplication

### Front section

Rename `비즈니스가 먼저 결정할 기록` to `먼저 확인할 세 가지 질문`.
Remove the five-row decision table and keep only these short anchored
questions:

1. `어떤 기록인가?`
2. `왜·얼마나 보관하는가?`
3. `무엇을 함께 지우는가?`

Keep their existing explicit anchors.

### Later checklist

Rename `기록·삭제 결정 체크리스트` to
`기록별 담당·정책·삭제 증빙`.

Replace the question/answer table with:

| Record | Owner example | Values fixed in policy | Deletion evidence |
|---|---|---|---|
| Audio | service or recording owner | purpose, capture mode, store, region, trigger, period | object/version deletion, playback failure, processor confirmation, backup expiry |
| Transcript and summary | conversation or case-record owner | source audio link, correction version, search copies, period | database/ticket/index deletion and search non-return |
| Events and business result | product and business-system owner | event IDs, authoritative result, statutory record category | event/record deletion or justified separate retention |
| Voiceprint | authentication and security owner | consent, enrollment audio, template, last interaction, governing law | enrollment/template deletion and authentication failure |
| Trace, search, and export copies | operations, security, and data owners | captured fields, access, region, retention, downstream copies | expiry jobs, access evidence, index/cache/export deletion |

The front asks the questions; the later table assigns responsibility and
evidence. Do not repeat the same five decisions twice.

## Internal plan corrections

Update project plans so they are executable:

- start a dedicated `mkdocs serve` process from the current worktree on port
  8124, verify readiness, and stop that exact process after browser checks;
- push implementation commits and confirm remote CI before replying to and
  resolving GitHub review threads;
- align the Alexa assertion with the exact planned text;
- rename the two-page browser step so it no longer says it checks a redirect;
- optionally assert that the removed `samples/source-evidence` path is absent,
  but do not add a deletion task because the current branch already contains
  no such files.

## Review-thread handling

After pushing:

- reply to factual threads with the commit and source boundary;
- explain that Xbox 90-day/two-year and HMRC immediate-audio-deletion claims
  were not present in their cited sources, and document the narrower verified
  boundaries instead;
- show the current branch diff for the already-absent evidence ledger; and
- resolve only after the remote changes and CI evidence are available.

## Validation

Run:

- targeted source/link/build and both SVG self-checks;
- full documentation tests and repository validators;
- desktop and 390px browser checks, including readable diagram width, wrapper-
  only horizontal scrolling, and zero page overflow;
- GitHub CI; and
- final unresolved-thread, branch divergence, and clean-tree checks.
