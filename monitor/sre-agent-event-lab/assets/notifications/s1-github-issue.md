## Impact

- Service: `ca-sre-event-lab-vnet`
- Operation: `GET /api/orders`
- Customer impact: 120 requests returned HTTP 500
- Alert fired: 2026-08-12T08:07:56.261581Z
- Agent conclusion: 2026-08-12T08:10:21.971535Z

## Detection

- Azure Monitor rule: `alert-sre-lab-s1-http500`
- Severity: Sev2
- Alert fired: 2026-08-12T08:07:56.261581Z
- SRE Agent thread created: 2026-08-12T08:07:58.694652Z

## Root cause

Container App revision `0000010` was deployed with `FAILURE_MODE=http500`.

## Evidence

- Application Insights recorded 120 failed `GET /api/orders` requests.
- The active failing revision exposed `FAILURE_MODE=http500`.
- Activity Log and revision timing matched the first failed request.
- Agent conclusion:

> **Root cause confirmed:** Container App `ca-sre-event-lab-vnet` deployed revision `0000010` at 08:06:16 UTC with `FAILURE_MODE=http500`.

- **Affected resource:** Application Insights `appi-sre-event-lab-95933ae5`
- **Exact onset:** 2026-08-12 08:06:52.147 UTC
- **Impact:** 120 HTTP 500s on `GET /api/orders` through 08:06:53.382 UTC. The alert fired at 08:07:56 UTC.
- **Evidence:** Activity Log shows the Container App update began at 08:06:08.954 UTC; the active failing revision had `FAILURE_MODE=http500`. Trace evidence shows a 500 response without an external dependency timeout pattern.
- **Mitigation:** Already applied externally: revision `0000011` is provisioned, receives 100% traffic, and has `FAILURE_MODE=none`. A post-change telemetry sample contained no 5xx responses.

No resource changes were made by this investigation.

## Current status

Resolved. A succeeding revision uses `FAILURE_MODE=none`, receives traffic, and returned no further 5xx responses in the verification window.

## Recommended follow-up

1. Add deployment validation that rejects fault-injection settings outside the lab.
2. Keep Review mode until response-plan accuracy is established across more incidents.
3. Preserve the incident timeline as Agent knowledge for recurrence detection.

## Tracking

- Agent thread ID: `6dd0e640-d969-46cb-a976-7c81b66fcadc`
- Detailed validation appendix: https://github.com/hellices/devguidesample/blob/main/docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md
- Generated from actual Azure SRE Agent evidence; no resource change was executed by the Agent.
