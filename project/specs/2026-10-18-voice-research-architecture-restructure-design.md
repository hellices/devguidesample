# Voice research architecture restructure design

## Goal

Reframe the published voice-data research around the Azure voice architectures
that are current as of 2026-10-18, while preserving the existing case evidence,
retention boundaries, legal cautions, and stable section anchors.

The revised research must distinguish:

1. native speech-to-speech model processing;
2. cascaded speech-to-text, text-model, and text-to-speech processing; and
3. post-call batch analysis of recordings and transcripts.

Voice Live is a managed API that can expose native realtime models or a
cascaded path, not a fourth model architecture.

## Decision

Restructure the three existing documents in place. Do not split realtime and
post-call material into additional child pages.

This approach keeps one research topic and its existing URLs while correcting
the current emphasis. It is preferable to:

- adding a comparison table above the current combined diagram, which would
  leave the visual and reading-order ambiguity in place; or
- creating separate realtime and post-call pages, which would make the
  boundary clearer but fragment a topic whose storage, region, PII, and
  retention questions need to be compared together.

## Evidence boundaries

Every architecture or product statement must carry enough context to identify:

- the source's checked date;
- whether the source is a product document, product reference, Microsoft
  reference architecture, customer case, or this research's synthesis;
- the API or model version when the claim depends on one;
- the feature status that the cited source explicitly declares, such as
  preview or GA; and
- the applicable model, feature, region, or processing scope.

Do not infer a product-wide GA or preview status from an individual model or
feature. Do not describe the post-call reference architecture as obsolete.
Historical customer cases prove only the adoption or operation publicly
reported at that time; they do not prove that the customer currently uses a
Realtime architecture.

Keep `published_at: 2026-10-17` as the original publication date. Update
`sources_checked_at` and the visible architecture/product verification date to
2026-10-18. Retain the separate case-policy and legal-review dates already
shown in the business document.

## Reader journey

### Topic overview

The topic entry should establish this reading order:

1. current realtime voice architectures;
2. records and processing scopes created by each architecture;
3. post-call analysis as a separate purpose and execution time; and
4. historical customer cases and policy comparisons.

Replace the current Voice Live/Speech storage observation with a short
architecture matrix. The matrix should state that storage is a separate
application, agent, logging, or post-call path rather than an inherent
consequence of realtime processing.

### Azure storage research

Reorder the Azure document as follows:

1. **Basis and architecture map**
2. **Native and cascaded realtime processing**
3. **Records, persistence controls, and processing scopes**
4. **PII controls by processing stage**
5. **Microsoft post-call reference architecture**
6. **Storage lifecycle**
7. **Supplementary format, capacity, throughput, and latency details**

The current service-storage facts remain, but move under the architecture that
creates or consumes each record.

### Business and policy research

Keep the representative cases before the design checklists. Add a compact
`공개 시점` field to every detailed case. Record an adoption, announcement, or
policy-effective date only when a cited source states it; otherwise use
`미확인`. Do not derive a date from a web page or assume continued operation.

The shared policy-check date remains separate from each case's public
announcement or adoption date. Do not assign a native, cascaded, or post-call
architecture to a customer unless the cited case exposes enough implementation
detail.

## Architecture model

### Native realtime path

Show audio flowing from the channel to a realtime speech-to-speech model and
then to audio output, tools, and business systems.

An optional input-transcription deployment can emit transcription events. That
transcript is a separate record and must not be described as the text that the
native model necessarily used internally.

Examples:

- GPT Realtime API used directly; or
- Voice Live with a supported realtime model.

### Cascaded path

Show speech to text, a text model or agent, and text to speech as distinct
processing stages.

The same logical path can be:

- orchestrated behind the managed Voice Live API when a nonmultimodal model is
  selected; or
- assembled by an application from separate services.

The diagram and prose must not imply that an application can intercept or
redact an internal Voice Live transcript before model inference unless a
Microsoft source explicitly documents that control.

### Post-call path

Show recorded audio entering the Microsoft call-center batch architecture
after a call completes. Preserve its two official flows:

- Speech batch transcription, optional raw-transcript storage, Conversation
  PII, and Foundry model analysis; and
- Content Understanding followed by an application PII step when needed.

Treat storage, analytics, and downstream reporting as independent of the live
conversation's record policy.

## Diagrams

Use two separate diagrams:

1. **Realtime architecture comparison** — a new locally authored SVG labelled
   `공식 문서 기반 종합 구성 예시` at
   `images/azure-voice-agent-realtime-architectures.svg`. It compares native
   and cascaded paths. Optional persistence, tracing, and post-call copies use
   dotted side paths.
2. **Post-call analysis** — revise the existing local SVG to contain only the
   post-call architecture and label it as the research's restatement of the
   Microsoft reference. Keep its existing
   `images/azure-voice-agent-ms-reference-architecture.svg` path. Link the
   Microsoft-provided SVG and Visio as the official originals.

Do not copy or present a locally authored SVG as a Microsoft-provided figure.
Keeping the existing post-call SVG path prevents the pull-request overview
from breaking.

## Records and controls

Add a structure-by-record matrix with these rows:

| Record | Required distinction |
|---|---|
| Input and output audio | Processing component, optional recording owner, persistence control, and deletion policy |
| Transcript | Cascaded model input, optional native-path helper transcript, post-call transcript, or human-corrected record |
| Conversation and tool events | Source event, linked input/response, order identifier, and business action |
| Business result | Order, device action, ticket, claim, or other authoritative system record |
| Trace and support logs | Enablement control, connected telemetry resource, access, region, and retention |
| Post-call result and copy | Independent creation time, storage location, purpose, retention, and deletion |

Document these concrete controls without merging them:

- the Foundry voice agent's default `store=false` and per-session `store`
  override;
- batch transcription's `destinationContainerUrl`;
- optional Foundry tracing in connected Application Insights and Log
  Analytics; and
- the storage and abuse-monitoring policies of connected models and services.

## Region and processing scope

Separate five location questions:

1. where an application stores recordings and derived records;
2. where speech input and output features process data;
3. where the selected model performs inference; and
4. where optional provider support logs are stored; and
5. where connected telemetry stores traces.

A Blob Storage account in Korea does not prove that every speech feature,
model inference, support log, or trace is processed and stored only in Korea.
Voice Live speech features and LLMs have independent Global, Data Zone, or
Regional processing scopes, so the document must direct readers to both
current availability tables.

## PII controls

PII is a control at a processing boundary, not a standalone voice-agent
architecture.

For each path, identify whether data is redacted:

- before a text model receives a transcript;
- after audio has already reached a native realtime model;
- after Content Understanding returns extracted results; or
- before trace or application storage.

State explicitly that transcript redaction does not redact or delete the
original audio and cannot undo an earlier model transfer.

Use feature-specific language support. As checked on 2026-10-18, the Microsoft
language-support page lists Korean for Text PII but lists English, French,
German, and Spanish for Conversation PII `2024-11-01` GA. Do not transfer Text
PII's Korean support to Conversation PII.

The call-center reference currently labels Conversation PII as preview while
the language-support page lists a GA version. Preserve each source's wording,
date, and version rather than flattening them into one unqualified status.

## Record reliability evaluation

Extend the existing quality section without turning test cases into product
defect claims.

For each implementation, record:

- model, deployment version, language, telephony network, codec, VAD mode, and
  concurrency;
- whether text is partial, provider-completed, application-accepted, or
  human-confirmed;
- event and conversation-item identifiers used to preserve order and connect
  audio, transcripts, responses, and tool calls;
- failures on silence, low-volume audio, crosstalk, interruptions, dropped
  packets, and malformed audio; and
- differences between optional helper transcription and the model or
  application's resulting interpretation.

Treat text generated for silence or non-speech as an evaluation scenario.
Do not state that a current Azure model has this defect or publish a frequency
without a primary product or research source that supports the claim.

## Supplementary material

Keep the existing format, capacity, Blob request target, Data Lake, access-tier,
rehydration, and latency material, but move it after the architecture,
record-control, region, PII, and post-call sections.

These sections remain searchable reference material. They must continue to
identify simple calculations and general Azure guidance rather than voice-agent
requirements.

## Compatibility and non-goals

- Preserve existing public document URLs and stable explicit anchors.
- Keep the six-pattern overview and the representative business cases.
- Do not add a new runtime sample or prescribe one application architecture.
- Do not claim private customer settings, current customer migrations, or
  unpublished retention periods.
- Do not copy the Microsoft architecture asset into the repository unless its
  reuse terms and attribution are verified.
- Do not change legal conclusions beyond the architecture-specific data-flow
  distinctions required by this restructure.

## Verification

Before updating the pull request:

1. verify changed Microsoft claims with the repository's
   `verify-with-microsoft-learn` workflow when it is available;
2. keep `verification_status: needs-review` for any scope that cannot complete
   that workflow;
3. run the full documentation test and validator contract;
4. render both diagrams and inspect desktop and narrow layouts;
5. use a browser to verify the new reading order, stable anchors, tables, and
   diagram labels; and
6. confirm that all pull-request review threads are resolved or answered with
   evidence.
