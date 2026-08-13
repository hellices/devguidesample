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

> Affected workload: `ca-sre-event-lab-vnet`
Telemetry source: `appi-sre-event-lab-95933ae5`
Root cause: revision `0000010` had `FAILURE_MODE=http500`
Impact: 120 `GET /api/orders` requests returned HTTP 500
Mitigation: a healthy revision with FAILURE_MODE=none restored service

## Current status

Resolved. A succeeding revision uses `FAILURE_MODE=none`, receives traffic, and returned no further 5xx responses in the verification window.

## Recommended follow-up

1. Add deployment validation that rejects fault-injection settings outside the lab.
2. Keep Review mode until response-plan accuracy is established across more incidents.
3. Preserve the incident timeline as Agent knowledge for recurrence detection.

## Tracking

- Agent thread ID: `6dd0e640-d969-46cb-a976-7c81b66fcadc`
- Detailed validation appendix: monitor/sre-agent-event-lab/validation-results.md
- Generated from actual Azure SRE Agent evidence; no resource change was executed by the Agent.
