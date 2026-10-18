# Two-page voice research topic design

## Goal

Remove the summary-only landing document and publish the voice-data research as
two substantive pages without violating the repository's required topic-entry
contract.

## Decision

Promote the business and policy research to the required topic root:

```text
docs/services/microsoft-foundry/voice-data-management/
├── index.md
├── azure-storage/
│   └── index.md
└── images/
```

The root page becomes `앱 음성 서비스 기록관리 사례와 정책`. The Azure
architecture and storage research remains the only child page.

This is preferable to:

- promoting the Azure document, which would make the broad topic entry start
  with one provider's implementation detail; or
- keeping the current summary, which repeats the two substantive pages without
  adding an independent research result.

## URL and navigation behavior

- `/services/microsoft-foundry/voice-data-management/` renders the promoted
  business and policy research.
- `/services/microsoft-foundry/voice-data-management/azure-storage/` remains
  unchanged.
- The promoted root has no `topic_order`.
- The Azure child changes from `topic_order: 2` to `topic_order: 1`.
- All explicit anchors inside the business document remain unchanged.

The old `/business-patterns/` path existed only on this unmerged pull-request
branch and was never a published Pages URL. Remove it rather than extending the
repository's legacy-collection redirect contract to support an unpublished
child path.

## Content movement

Move the complete business document into the root. Do not merge the old
summary prose into it. Its six patterns already provide the concise topic
orientation, and its existing Azure cross-link provides the second-page route.

Preserve:

- title, description, services, official sources, tags, dates, and
  `verification_status`;
- the six numbered patterns;
- all detailed cases, tables, legal boundaries, and reliability guidance; and
- every explicit anchor.

The old summary title `음성 AI 데이터 보관과 운영 패턴 리서치` is retired
rather than retained as another heading.

## Relative-link changes

After promotion:

- business root → Azure child:
  `azure-storage/index.md`;
- business root → lifecycle image:
  `images/voice-data-lifecycle.svg`;
- Azure child → business root:
  `../index.md`;
- Azure child → shared images remains:
  `../images/<file>.svg`.

No other content link should change.

## Topic metadata

Add `azure-architecture` to the promoted root's `services` so the topic entry
retains the service discovery coverage that the removed summary declared.

Keep:

```yaml
published_at: 2026-10-17
sources_checked_at: 2026-10-18
verification_status: needs-review
```

The structural move does not constitute a new research publication or source
reverification.

## Pull-request presentation

Update PR #83 so its review table has exactly two rows:

1. the business and policy research at the topic root; and
2. the Azure architecture and storage research child.

Keep both architecture SVG previews. Remove the obsolete overview review row
and the old direct business-child review URL.

## Validation

Run the complete documentation contract. In addition, verify:

- topic discovery reports one root and one child;
- the root has no `topic_order`;
- the Azure child has `topic_order: 1`;
- the unpublished business child path is absent from the built site;
- the root's Azure link and lifecycle image resolve;
- the Azure child's root link resolves;
- all existing explicit business anchors remain in the root HTML; and
- desktop and 390px pages have no layout regression.

No implementation commit is pushed until the local move, links, and complete
validation pass.
