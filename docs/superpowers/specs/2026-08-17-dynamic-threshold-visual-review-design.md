# Dynamic Threshold Visual Review Design

## Goal

Resolve the current PR visual-review feedback without reintroducing the
hands-on experiment or expanding the brief with a redundant custom diagram.

## Review Findings

### Official chart

The chart renders successfully on GitHub through GitHub's image proxy. Browser
verification reports a complete 1000x598 image and the rendered preview shows
the documented allowed range and alert states.

The review concern is still valid: the Markdown embeds a Microsoft Learn
`media/` URL directly, so a Learn content move could break the repository
document. The repository already stores official Microsoft visuals locally.

### Source label

No content change is required for the source title. The linked page currently
publishes the title `Create a Log Search alert rule with dynamic threshold`,
which is the exact label used by the brief. The same page documents the
five-minute minimum for Log Search Dynamic Threshold rules.

### Additional diagram

No Mermaid or custom diagram will be added. The official chart already
communicates the learned allowed range, anomaly points, active state, and
resolution. A second conceptual diagram would repeat the same material and
work against the one-page introduction goal.

## Changes

- Download the official chart without modification to
  `monitor/assets/official/dynamic-threshold-preview-chart.png`.
- Change the Markdown image source to the relative local asset.
- Keep the image link and source caption pointed at the official Microsoft
  Learn article, not at the raw media file.
- Add focused repository tests that verify the local PNG exists, has a valid
  PNG signature, is used by the brief, and retains the official attribution.
- Reply to the hotlink review thread with the implemented fix.
- Reply to the source-title review thread with the verified page title and
  location of the five-minute constraint; do not make an unsupported wording
  change.

## Final Scope

PR #54 will contain only:

- `monitor/azure-monitor-dynamic-thresholds-brief.md`
- `monitor/assets/official/dynamic-threshold-preview-chart.png`
- the smallest focused documentation test needed to protect the asset
  contract

It will contain no experiment, Bicep, workload changes, hands-on guide, or
custom diagram.

## Verification

- The local file must be byte-identical to the current official PNG.
- The PNG signature and dimensions must be 1000x598.
- GitHub Markdown must render the local image.
- The image click target and attribution must resolve to the Microsoft Learn
  article.
- All links and focused documentation tests must pass.
- PR review replies must be attached to their existing inline threads.

