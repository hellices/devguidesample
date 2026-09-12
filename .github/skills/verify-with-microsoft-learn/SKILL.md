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

## Common mistakes

- Treating a search snippet as the full source
- Citing a product landing page that does not support the claim
- Using blogs, Q&A, or copied examples when an official article exists
- Marking a document verified while one material claim is unresolved
