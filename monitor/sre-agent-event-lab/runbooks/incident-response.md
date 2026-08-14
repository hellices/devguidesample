# Azure SRE Agent Event Lab Incident Runbook

## Scope and safety

This runbook applies only to the disposable lab resource group that `azd`
provisioned for the current environment: the group reported as
`AZURE_RESOURCE_GROUP` in the deployment outputs, tagged
`purpose=sre-agent-event-lab` together with the `azd-env-name` of that
environment. Any resource outside that group is out of scope, including
resources in other lab environments that carry the same purpose tag.

- Investigate automatically, but do not execute a mitigation without approval.
- Do not change resources, role assignments, alert rules, or traffic outside the lab resource group.
- Prefer the smallest reversible mitigation.
- Treat every hypothesis as unconfirmed until supported by a metric, log, trace, resource configuration, or Activity Log record.
- Do not expose connection strings, tokens, or secret values in the incident summary.

## Investigation order

### 1. Establish the incident boundary

Record:

- Azure Monitor alert name, severity, fired time, and affected resource.
- First and last abnormal telemetry timestamps in UTC.
- Affected endpoint, Container App revision, and dependency, if applicable.
- Whether the symptom is availability, latency, dependency failure, or a combination.

**The alert's own "affected resource" is not the workload.** Every alert
rule in this lab is scoped to the Log Analytics workspace (`scopes` and
`targetResourceTypes: Microsoft.OperationalInsights/workspaces` in
`infra/alerts.bicep`), because the rule queries the workspace schema. So
the "affected resource"/target Azure Monitor reports for the alert *is*
that Log Analytics workspace -- record it, but do not report the
workspace as the incident's impact scope. Do not report the workspace as
the workload either. Treat it only as the alert's own scope.

### 2. Validate the signal

Query workspace-based Application Insights for the alert window:

- `AppRequests`: result code, success, duration, operation ID, and operation name.
- `AppExceptions`: exception type, message, operation ID, and timestamp.
- `AppDependencies`: target, result code, success, duration, operation ID, and timestamp.

Confirm that the alert query result crosses its configured threshold. State when data is absent or delayed instead of inferring a cause.

**A telemetry row is not the workload either.** Every one of those rows
carries a `_ResourceId` column that resolves to the Application Insights
component, not the Log Analytics workspace and not the Container App --
it is Application Insights' own ingestion identity, one indirection
closer than the workspace but still not the workload. Identify the
actually affected Container App/service from the row content itself:
`AppRoleName` names the service, and `Name`/the requested path names the
endpoint (`/api/orders` for S1/S2, `/api/documents` for S3). The incident
boundary and the required summary's `Impact` field must name that
Container App/endpoint, not the alert's scope or the `_ResourceId` value.

### 3. Correlate resource state

Inspect:

- active and recently inactive Container App revisions;
- revision creation and traffic-change timestamps;
- non-secret environment variable names and values;
- image version and provisioning/health state;
- Container Apps console and system logs;
- resource health and current replica state.

Compare the beginning of the symptom with revision and configuration timestamps.

### 4. Correlate control-plane changes

Use Azure Activity Log for the same UTC interval. Look for:

- Container App writes and revision changes;
- role assignment writes or deletes;
- deployment operations;
- alert rule changes.

For an authorization symptom, identify the calling managed identity, exact target scope, required data-plane role, and current assignment. Do not recommend subscription-wide access when a resource or container scope is sufficient.

### 5. Form and test the root-cause statement

The conclusion must include:

1. the direct cause;
2. the affected component;
3. the causal chain from change to telemetry to alert;
4. at least two concrete evidence items;
5. known uncertainty or missing evidence.

Reject generic statements such as "resource pressure," "network issue," or "application bug" unless the evidence specifically supports them.

## Mitigation rules

- Prefer reverting the most recent lab-only configuration or revision change.
- For authorization failures, restore only the missing least-privilege role at the original scope.
- Do not disable monitoring to clear an alert.
- Do not delete the resource group or recreate the workload as an incident mitigation.
- After approval and mitigation, verify the original endpoint, telemetry, and alert resolution.

## Required incident summary

Return a structured summary with:

| Field | Required content |
|---|---|
| Alert | Name, severity, fired time, affected resource |
| Impact | Endpoint/operation, response code or latency, duration |
| Root cause | Direct, evidence-supported cause |
| Evidence | Queries, timestamps, revision/configuration/activity records |
| Proposed mitigation | Smallest reversible change and exact scope |
| Verification | Health check, normal telemetry, alert state |
| Uncertainty | Missing or inconclusive evidence |
| Status | Investigating, waiting for approval, mitigated, or resolved |
