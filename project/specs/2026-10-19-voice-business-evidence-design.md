# Voice business evidence redesign

## Goal

Make the business and policy page answer concrete retention questions from
public evidence instead of presenting broad legal and governance principles
that do not tell a reader which record has which period.

The page must lead with:

1. public product retention policies;
2. business-use comparisons;
3. statutes that state an exact period or immediate deletion rule; and
4. the actual allegations and ordered remedies in the Amazon Alexa case.

The document reports source text and scope. It does not decide legal
applicability for a reader.

## Page role and two-page topic

The business and policy page remains the promoted topic root from
`2026-10-19-two-page-voice-research-topic-design.md`. The Azure architecture
and storage research remains the only child.

The old `/business-patterns/` path existed only on the unmerged pull-request
branch. Do not extend the repository's legacy-collection redirect mechanism
for that unpublished path.

## Editorial order

Use this root-page order:

1. title, dates, scope, and reading boundary;
2. `주요 AI·음성 제품은 무엇을 저장하고 언제 지우는가?`;
3. a compact business decision table;
4. the business-use comparison table;
5. collapsed detailed case evidence;
6. `법령이 보존기간을 직접 정한 경우`;
7. `Amazon Alexa 사건에서 실제로 무엇이 문제였는가?`;
8. a short record and deletion checklist;
9. collapsed voice-quality, biometric, accessibility, vendor, and operational
   appendices.

Remove the current six numbered pattern headings. Their useful content belongs
in the product table, business decision table, exact-law table, or short
checklist.

## Product-policy comparison

Keep the existing heading and anchor exactly:

```markdown
## 주요 AI·음성 제품은 무엇을 저장하고 언제 지우는가? { #product-storage-comparison }
```

Move this section directly below the reading boundary. Render the
Bixby/Gemini/ChatGPT/Copilot/Siri comparison table without a `<details>`
wrapper. Add one sentence that identifies it as the page's primary
cross-product research result.

Preserve every existing product period and scope qualification. Do not merge:

- original audio with transcripts;
- service history with model-improvement copies;
- account deletion with archive;
- product defaults with organization policy; or
- policies from different regions or modes.

The Microsoft record-object table can remain collapsed beneath the open
cross-product table.

## Business decision table

Replace the six generic patterns with one table:

| Decision | Required evidence |
|---|---|
| Which record exists? | input/output audio, transcript, summary, event, tool call, business record, trace, or biometric template |
| Why is it kept? | product operation, user history, transaction evidence, dispute handling, statutory record, security, evaluation, or model improvement |
| What starts and ends retention? | request completion, contract or supply event, complaint closure, purpose expiry, last interaction, profile inactivity, or deletion request |
| Which source controls the period? | product policy, statute, court order, organization policy, or customer-selected setting |
| What must be deleted together? | audio, transcript, geolocation, derived copy, model-improvement input, processor copy, index, and backup |

Keep `#voice-record-types`, `#raw-audio-retention`, and
`#deletion-completion` as explicit anchors on the most closely corresponding
rows or short subsections so existing internal navigation remains valid.

## Business-use comparison

Show the existing `업무마다 무엇을 어디에 얼마나 저장하는가?` table before
the detailed case narratives.

Keep rows only where public sources identify a concrete processing mode,
record, setting, period, or explicit unknown. Do not turn the existence of
customer support, an AI bot, or a video call into evidence that audio is
recorded.

Keep all detailed case citations in one collapsed evidence section after the
comparison table. Repetitive provider descriptions and general policy prose
may be shortened, but source-specific unknowns and legal-entity boundaries
must remain.

## Exact-period statute table

Replace the broad Korea/EU/US legal overview with:

```markdown
## 법령이 보존기간을 직접 정한 경우 { #jurisdiction-rules }
```

The open table has these columns:

| Jurisdiction and source | Exact covered record | Period and trigger | Source phrase | Voice boundary |
|---|---|---|---|---|

Include only the following verified rules.

### Korea: electronic-commerce transaction records

Source:
`전자상거래 등에서의 소비자보호에 관한 법률 시행령 제6조`.

Display:

- display and advertising records: 6 months;
- contract or withdrawal records: 5 years;
- payment and supply records: 5 years; and
- consumer complaint or dispute-handling records: 3 years.

Boundary: these are transaction-record categories. The provision does not say
that every voice recording must be kept for those periods.

Official source:
`https://law.go.kr/LSW/lsLinkCommonInfo.do?lspttninfSeq=63460&chrClsCd=010202`.

### Korea: financial-consumer records

Sources:

- `금융소비자 보호에 관한 법률 제28조`; and
- its Enforcement Decree Article 26.

Display:

- the listed contract, performance, advertising, rights-exercise, outsourcing,
  and related materials: 10 years by default;
- a guaranteed product with a guarantee longer than 10 years: the guarantee
  period;
- a financial product contract longer than 10 years: the contract period; and
- separately delegated categories: the shorter or capped period stated in the
  decree or Financial Services Commission notice.

Boundary: the decree defines record categories, not a universal rule that
every financial call's raw audio is retained for 10 years. A recording is
included only when the applicable record rule treats it as the required
material.

Official sources:

- `https://www.law.go.kr/LSW/lsLinkCommonInfo.do?lsJoLnkSeq=1033002393`; and
- `https://law.go.kr/lsLinkCommonInfo.do?lspttninfSeq=166903&chrClsCd=010202`.

### EU: MiFID II telephone and electronic communications

Source: Directive 2014/65/EU, Article 16(7).

Display:

- calls and electronic communications relating to own-account transactions or
  client-order reception, transmission, and execution;
- intended transaction/order communications are included even when no
  transaction results;
- keep for 5 years; and
- keep up to 7 years when the competent authority requests it.

Source phrase:
`shall be kept for a period of five years and, where requested by the
competent authority, for a period of up to seven years`.

Official source:
`https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02014L0065-20240109`.

### EU: high-risk AI automatically generated logs

Source: Regulation (EU) 2024/1689, Articles 19(1) and 26(6).

Display:

- automatically generated high-risk AI logs under the provider's or deployer's
  control;
- period appropriate to the intended purpose; and
- at least 6 months unless Union or national law provides otherwise.

Boundary: this is a high-risk AI log rule, not a minimum six-month retention
rule for all voice audio or transcripts.

Official source:
`https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng`.

### United States: COPPA limited audio exception

Source: 16 CFR 312.5(c)(9), as amended in the 2025 final rule.

Display:

- an audio file containing a child's voice and no other personal information;
- collected only to respond to the child's specific request;
- no other use and no disclosure; and
- delete immediately after responding.

Source phrase:
`deletes it immediately after responding to the child's request`.

Add a separate note for 16 CFR 312.10: it has no universal day count; it
requires retention only as long as reasonably necessary, prohibits indefinite
retention, and requires a written deletion timeframe.

Official sources:

- `https://www.federalregister.gov/api/v1/documents/2025-05904.json`; and
- `https://www.federalregister.gov/documents/full_text/text/2025/04/22/2025-05904.txt`.

### United States: Illinois BIPA voiceprints

Source: 740 ILCS 14/15(a).

Display:

- biometric identifiers and biometric information, including a voiceprint;
- destroy when the initial collection purpose is satisfied or within 3 years
  of the individual's last interaction with the private entity; and
- use the earlier event.

Boundary: a voiceprint is not every ordinary voice recording.

Official source:
`https://www.ilga.gov/documents/legislation/ilcs/documents/074000140K15.htm`.

### United States: Texas biometric identifiers

Source: Texas Business & Commerce Code Section 503.001.

Display:

- a commercially captured biometric identifier, including a voiceprint;
- destroy within a reasonable time, no later than the first anniversary after
  the collection purpose expires;
- when tied to another legally required instrument or document, no later than
  the first anniversary after that legal maintenance duty ends.

Show the 2026 statutory boundary: the section excludes specified financial
institution voiceprints and specified AI development, security, and fraud
uses, subject to the statute's conditions.

Official source:
`https://tcss.legis.texas.gov/resources/BC/htm/BC.503.htm`.

## Rules without a universal day count

After the exact table, add one short paragraph:

- Korea PIPA, GDPR, and CCPA/CPRA generally require purpose, necessity,
  disclosed criteria, or deletion when no longer needed;
- they do not create one common number of days for all voice recordings; and
- therefore they are not presented as numeric retention rows.

Do not restore the current broad multi-row legal overview.

## Amazon Alexa enforcement case

Use this open heading and preserve the anchor:

```markdown
## Amazon Alexa 사건에서 실제로 무엇이 문제였는가? { #alexa-deletion-case }
```

Separate complaint allegations from ordered remedies.

### Complaint allegations

State that the 2023 complaint alleged:

- Alexa default settings retained voice recordings and transcripts
  indefinitely, including inactive child profiles;
- Amazon used recordings and transcripts to fulfill requests and to train and
  improve Alexa;
- some deletion requests removed recordings but not written transcripts; and
- voice and geolocation information were not deleted upon request and were
  retained for potential use.

Label every item as an allegation, not a final finding about current Alexa.

### Filed order

State that the filed stipulated order:

- imposed a USD 25 million civil penalty;
- required a process to identify inactive Alexa child profiles within 6 months
  of entry;
- required associated child personal information to be deleted within 90 days
  after identification unless the parent requested retention or the profile
  became active again;
- required deletion of Alexa voice and geolocation information when a consumer
  used Amazon's deletion mechanism;
- required deletion of child personal information when a parent used the
  deletion mechanism; and
- prohibited subsequent use of deleted information to create or improve a new
  data product, while not undoing products created before deletion processing.

Official sources:

- complaint:
  `https://search.ftc.gov/system/files/ftc_gov/pdf/Amazon-Complaint-%28Dkt.1%29.pdf`;
- filed order:
  `https://search.ftc.gov/system/files/ftc_gov/pdf/1923128amazonalexaorderfiled.pdf`;
- case page:
  `https://www.ftc.gov/legal-library/browse/cases-proceedings/192-3128-amazoncom-alexa-us-v`.

## Material to compress

Replace the long operational design material with one collapsed appendix:

```markdown
<details markdown="1">
<summary><strong>구현·품질·접근성 검토 부록</strong></summary>
```

The appendix may retain concise versions of:

- deletion propagation and evidence;
- legal hold and backup boundaries;
- transcript, summary, event-order, and biometric-attack evaluation;
- accessibility, bystanders, and shared-device controls;
- Microsoft record-object details; and
- additional contact-center and public-service cases.

Remove repeated generic statements, long implementation recipes, and
non-voice standards that do not change a business decision. Preserve direct
sources and any unique product period.

## Validation

Run the complete documentation contract and verify in the browser:

- the topic has exactly two authored pages;
- the product comparison is open and appears before the business cases;
- the exact-period table and Alexa case are open;
- the old broad legal table is absent;
- every numeric period has an official source and a record-type boundary;
- complaint allegations and order obligations are visually distinct;
- the remaining appendix is collapsed;
- stable anchors resolve in the promoted root; and
- desktop and 390px layouts remain readable.

Keep `verification_status: needs-review` because the repository's Microsoft
Learn verification workflow remains unavailable; legal-source verification is
separate and must not change that field.
