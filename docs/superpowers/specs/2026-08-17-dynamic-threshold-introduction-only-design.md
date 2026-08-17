# Dynamic Threshold Introduction-Only Design

## Goal

Return PR #54 to a customer-facing introduction only. The pull request should
contain one document and no runnable lab, Azure infrastructure, validation
workflow, or experiment-specific tests.

## Final Scope

Keep only:

- `monitor/azure-monitor-dynamic-thresholds-brief.md` at the content of commit
  `d35c219e7ba0e9724a488b9e9ab40aa0f17823e0`.

Remove every change made after that original brief:

- the hands-on case section and link;
- S2 Dynamic Threshold lab guidance;
- Standard availability test and Dynamic Threshold Bicep resources;
- lab wiring, environment outputs, and experiment tests;
- local chart asset added for the lab;
- deployment-plan, SRE Agent, README, and ignore-file changes;
- temporary workflow specifications and plans.

## Presentation

The remaining brief stays a concise English introduction covering:

- what Dynamic Thresholds change;
- the documented learning timeline;
- static-versus-dynamic selection;
- supported alert paths;
- safe shadow-mode adoption;
- operational boundaries;
- official Microsoft references.

The official Microsoft Dynamic Threshold chart remains embedded directly from
Microsoft Learn, as it was in the original one-file brief. No repository-
specific diagram or experiment result remains.

## Verification

The branch diff against `origin/main` must contain exactly one file:

`monitor/azure-monitor-dynamic-thresholds-brief.md`

Verification will confirm:

- the file matches commit `d35c219` byte for byte;
- no lab, Bicep, asset, test, or workflow-artifact change remains;
- Markdown diff checks pass;
- all official URLs in the brief respond successfully;
- the repository's relevant documentation tests pass;
- PR #54 title and body describe an introduction only.

