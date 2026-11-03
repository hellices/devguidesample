---
name: writing-korean-docs
description: Use when writing, rewriting, or reviewing Korean prose in this repository's public docs, sample READMEs, or contributing pages, especially when text reads machine-written, translated, or "AI-like".
---

# Writing Korean docs

## Overview

Fix Korean technical prose so it reads as if written in Korean from the start, without changing what it claims. Explanation paragraphs and result sections need different treatment: flattening a scannable benchmark section into prose made it longer and harder to read in this repository.

The normative rules live in `docs/contributing/index.md` (`#content-first-headings`, `#korean-writing`, `#scan-format`). This skill is the working procedure.

## Workflow

1. Run the checker on the file and keep the output.

   ```bash
   python .github/skills/writing-korean-docs/scripts/check_korean_style.py <file>
   ```

2. Classify every section before editing it:
   - **Result section**: it holds a comparison table, measured numbers, option ratings, or recommended parameters. Keep its table, bullet findings, bold labels, bold winning numbers, ✅·△·❌ ratings, noun-ending fragments, scope blockquote, and `<details>`.
   - **Explanation section**: everything else. Write paragraphs.
3. Edit with the recipes below. In result sections, keep the table and list structure and change only wording inside cells and bullets; fix a result-section heading only as [Headings](#headings) allows. Never convert result sections to paragraphs.
4. Re-run the checker. Re-read every remaining finding; leave intended structure as is. Never edit just to reach zero.
5. Report content problems you noticed (missing source, unclear number) separately instead of fixing them silently.

## Invariants

Keep every number, unit, date, proper noun, code, link, quotation, claim, and hedge ("~할 수 있다", "추정", "본 측정 조건 기준"). Do not add a claim or make one more or less certain. Inflation and vague filler ("새로운 패러다임", "근본적으로", "다양한 요소", "핵심") are not claims: remove them, and if a sentence is left with nothing to say, remove it and list it in the step 5 report. Keep the document's existing ending style (`~다` or `~합니다`).

## Headings

Write the section's point as a noun phrase.

| Section says | Heading |
|---|---|
| 처음 1,024 토큰이 같아야 캐시가 적중한다 | 처음 1,024 토큰의 바이트 일치 조건 |
| 운영팀이 TTL을 정하고 사용량을 보며 확장한다 | 운영팀의 TTL 결정과 사용량 기반 확장 |

A heading ending in `~다`, `~합니다`, or `~요` is a sentence; shorten it to a noun phrase. `X: Y` subtitles are allowed only for report section titles in `document_type: research` or `lab` pages, such as `결과 2: 배치 처리량 — 500자 청크`. Keep result-section headings as they are when they already name the measurement.

## Explanation sentences

Apply the pairs in [rewrite-examples.md](rewrite-examples.md). The most frequent fixes:

- Put the actor first: "운영팀에 의해 결정되어진다" → "운영팀이 정한다".
- Drop padding verbs: "만료 작업을 수행한다" → "키를 만료시킨다".
- No comma after `-고`·`-며`·`-지만` or after 그리고·따라서.
- Delete summary openers and closers ("결론적으로", "크게 세 가지로 나눌 수 있다") and inflation ("새로운 패러다임", "핵심").
- One `**결론**:` box per document at most; turn others into a plain final sentence.

## Common mistakes

| Mistake | Fix |
|---|---|
| Rewriting a benchmark section as prose | Keep the table and bullet findings; fix wording only |
| Turning a heading into a sentence while removing a colon | Use a noun phrase |
| Removing "추정", "본 측정 조건 기준" while tightening | Hedges are content; keep them |
| Deleting a list but leaving an intro such as "다음 세 가지" | Remove the intro together with the list, or keep the list |
| Chasing checker zero | Findings are places to re-read, not targets |
