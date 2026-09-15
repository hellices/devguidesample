# AGFC protocol acceptance results

This is a **result artifact**, not a deployment project or a performance
benchmark. The [research page](../../index.md) summarizes the product facts
and observations without the detailed test procedure.

## Recorded facts

[result.json](result.json) preserves the sanitized record from 2026-09-15:

- A disposable AKS 1.35 cluster and Application Gateway for Containers in
  Korea Central, using ALB Controller 1.10.30.
- Seven successful strict HTTP/2 requests and seven failed strict HTTP/3
  attempts across local and Azure sources. The HTTP/3 attempts timed out.
- An additional 15-second HTTP/3 timeout, successful external HTTP/3
  controls, an HTTP/2 fallback result, and final HTTP/2 liveness.
- Healthy HTTPS listener and route conditions, enabled certificate
  validation, and no customer NSG or route table on the AGFC subnet.
- Confirmed deletion of the temporary main and node resource groups.

A timeout is not an explicit protocol rejection. These observations do not
establish unsupported status for every region or preview, and they do not
measure mobile-device performance. A nonzero curl TLS verification field
on a connection timeout is not evidence of a certificate rejection.

## Use, validation, and cleanup

Read the JSON as evidence for the specific configuration and date. Its
14 main trial records were checked against the recorded counts, actual
protocols, errors, and backend responses before archiving. The additional
timeout, controls, and fallback are outside those main trial totals.

The artifact contains no cloud resource identifiers, actual AGFC addresses,
private keys, or kubeconfig. It creates no resources and requires no cleanup.
Do not combine it with the separate local performance dataset as if both
were measurements of the same deployment.
