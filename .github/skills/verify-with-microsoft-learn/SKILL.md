---
name: verify-with-microsoft-learn
description: Use when creating, revising, or reviewing public technical documentation that contains Microsoft or Azure product claims.
---

# Verify with Microsoft Learn

## Core rule

Verify product behavior, support status, limits, versions, configuration steps, and CLI or API usage against current official text. A source URL alone is not evidence of a completed review.

## Workflow

1. Extract every checkable claim from the changed document. Separate product claims from incident-specific observations.
2. Confirm the `microsoft.docs.mcp` server is connected. Inspect its current tool descriptions through `tools/list`; tool names, parameters, and response shapes can change.
3. Search Microsoft Learn for each claim using the official product name, feature, version, error, or command. Use the discovered documentation search tool rather than general web search.
4. Fetch every selected article in full with the discovered article-fetch tool. Search snippets are only candidates.
5. Compare each claim with the fetched article's scope, prerequisites, supported versions, limitations, and current terminology.
6. Correct unsupported claims. For a historical case, preserve the observation but state its date and contrast it with current documented behavior.
7. For Kubernetes or CNCF behavior that Microsoft Learn does not define, also check the relevant `kubernetes.io` or `cncf.io` source. Microsoft Learn remains mandatory for this repository's Azure context.
8. Record the exact article title and canonical URL in `official_sources`, set `sources_checked_at` to the actual review date, and set `verification_status: verified` only after every material claim is covered.
9. Run `python scripts/docs/validate_metadata.py`, `python scripts/docs/validate_sources.py`, and `python scripts/docs/validate_links.py`.

If the server is unavailable, no relevant full article can be fetched, or a material conflict remains, set `verification_status: needs-review` and report the unresolved claim. Never use `last_verified` to imply a check that did not occur.

## Citing Learn in the body

The rules live in `docs/contributing/index.md#learn-citations`.

1. Link each Microsoft or Azure claim to the Learn section that supports it (`...#section-anchor`). `official_sources` alone does not count.
2. Before you explain a topology, request flow, or option comparison, look for a diagram, table, or screenshot in the fetched article. If one exists, build the explanation on it. When step 3 proves its license, reuse the original; do not redraw it or turn it into prose.
3. Copy an image only after you prove its license:
   - Read `<meta name="original_content_git_url">` from the Learn page HTML.
   - If the repository ends in `-pr`, open the same path in the public repository without `-pr`, such as `MicrosoftDocs/azure-docs`.
   - Confirm that the repository's `LICENSE` is CC BY 4.0. Download the file from `raw.githubusercontent.com`, because `gh api` can return a SAML 403.
4. If you cannot prove the license, link the section instead of copying the image. If the page still needs a figure, draw a new one, such as Mermaid, from the article's text: its components, flow, and conditions. Do not trace, crop, or recreate the official image's layout, shapes, or icons.
5. Never copy Microsoft or Azure logos or product icons on their own; trademarks are outside CC BY 4.0.
6. Save the image in the bundle's `images/` folder with Korean alt text that describes the figure.
7. Below the image, add a caption with:
   - the Learn article, section, and link
   - the public source file
   - the CC BY 4.0 license link
   - what you changed, or "원본을 수정하지 않았습니다"

## Evidence contract

```yaml
verification_status: verified
sources_checked_at: 2026-09-12
official_sources:
  - title: Azure Kubernetes Service documentation
    url: https://learn.microsoft.com/azure/aks/
```

Use at least one claim-relevant `https://learn.microsoft.com/` article. Add upstream official sources when they hold the authoritative implementation detail.

## Quick reference

| Claim | Verify |
|---|---|
| Supported feature or version | Availability, region, tier, preview/GA status |
| Configuration procedure | Prerequisites, command syntax, defaults, permissions |
| Limit or performance statement | Units, scope, exceptions, last-updated context |
| Historical incident | Observation date separately from current product behavior |
| Reused Learn figure | Public source file, CC BY 4.0 `LICENSE`, caption with section link and changes |

## Common mistakes

- Treating a search snippet as the full source
- Citing a product landing page that does not support the claim
- Using blogs, Q&A, or copied examples when an official article exists
- Marking a document verified while one material claim is unresolved
- Copying a Learn image because it appears on learn.microsoft.com, without finding its public CC BY 4.0 source
- Redrawing or paraphrasing an official diagram that could be reused with attribution
