# Multi-Hub Private AKS upgrade preflight and diagnostics with Azure SRE Agent

This runnable sample connects an Azure SRE Agent in `AzureVNet` egress mode
across Multi-Hub Firewall UDR routes (or Azure Virtual WAN Secured Hub) to
multiple Private AKS clusters (`*.privatelink.<region>.azmk8s.io`). It includes
compact Python tools, a fast-execution skill (`private-aks-upgrade-preflight`),
a `PreToolUse` safety hook (`pre-kubectl-mutation-safety-gate`), and fault
seeding scripts so the agent completes multi-cluster version discovery, release
note impact analysis, 7-point upgrade preflight scoring, and pod failure
diagnostics in **20–96 seconds per turn**.

Settings, routing/DNS architecture, RBAC (`dataActions`), and the latency root
cause analysis (reducing turn times from 4–20 minutes to 20–96 seconds) are in
[CONFIGURATION.md](CONFIGURATION.md) (Korean).

Follow the lab guide at
[Multi-Hub Private AKS upgrade preflight](../../private-aks-multihub-preflight/index.md)
for the end-to-end walkthrough and verification screenshots.

## Layout

| Path | Purpose |
| --- | --- |
| `infra/main.bicep`, `infra/resources.bicep` | Resource group, SRE Agent VNet + `/24` delegated subnet (`Microsoft.App/environments`), route table to Hub #1 Firewall, Hub VNets, Log Analytics, Application Insights, UAMI, and VNet-integrated Azure SRE Agent |
| `agent/custom-instructions.md` | Fast-execution guardrails (single batched `az aks list` query, single combined `kubectl get pods,deploy,pdb`, no nested `Task` subagent spawning, `--no-wait` for long ARM operations) |
| `agent/knowledge/aks-upgrade-and-eol-policy.md` | Kubernetes minor version EOL schedule, `P0`/`P1`/`P2` priority matrix, and preflight scoring rubric |
| `agent/knowledge/aks-eol-notice-template-and-history.md` | 5-section customer upgrade notice template (`aks-upgrade-notice.md`), 1-click `/api/files/` download link contract, and notice history tracking |
| `agent/knowledge/aks-9point-upgrade-preflight-policy.md` | 9-point AKS upgrade preflight checklist combining ARM control plane and Private AKS Kubernetes REST API data plane checks |
| `agent/knowledge/aks-dataplane-inspection-sop.md` | SOP for branching between `RunKubectlReadCommand` (`<= 3` simple queries) and Python REST API (`>= 4` multi-value queries) over vWAN Firewall |
| `agent/tools/check_aks_eos_release_calendar.py` | Core Python Tool #1 scraping the MS Learn AKS release calendar and filtering live clusters by calendar-month EOS window (`months_ahead=4`) and `SupportPlan` (`Standard` vs `LTS`) |
| `agent/tools/evaluate_aks_upgrade_preflight.py` | Core Python Tool #2 (<900 chars) 9-point upgrade preflight evaluator supporting `check_items="ALL"` or selective re-verification (`"1,4,9"`, `"3,7,8"`) |
| `agent/tools/verify_multihub_firewall_route.py` | Fast (1.5s timeout) TCP 443 socket probe from the SRE Agent subnet across Multi-Hub Firewalls to Private AKS API server private IPs |
| `agent/skills/private-aks-upgrade-preflight.md` | Playbook binding batched CLI queries, MS Learn MCP release-note lookup, combined `kubectl` scan, and preflight scoring |
| `agent/skills/aks-eol-notice-and-history-workflow.md` | Full-cycle skill orchestrating EOS target selection, 9-point preflight, `mslearn-mcp` lookup, and `./aks-upgrade-notice.md` generation |
| `agent/hooks/pre_kubectl_mutation_guard.sh` | `PreToolUse` command hook blocking destructive `kubectl` commands (`delete node/namespace`, `drain`, `cordon`) |
| `monitoring/sre-aks-management-dashboard.json` | Azure Portal Shared Dashboard (`Dashboards with Grafana`) ARM template with 12-column ARG cluster inventory and Prometheus panels |
| `scripts/deploy.sh` | Deploys Bicep resources, grants `Azure Kubernetes Service Cluster User Role` and `Azure Kubernetes Service RBAC Reader`, and applies agent extensions |
| `scripts/apply-agent-config.sh` | Registers the Python tools, skill, custom instructions, and safety hook on the agent data plane |
| `scripts/seed-faults.sh` | Seeds (`seed`) or repairs (`reset`) `ImagePullBackOff`, `CrashLoopBackOff`, and single-replica test conditions on target Private AKS clusters |
| `scripts/cleanup.sh` | Deletes the lab resource group |
| `assets/*.svg` | Three architecture diagrams published to the lab page through `sample.yml` |
| `tests/test_preflight_tools.py` | Unit tests for tool output size (<900 chars), verdict scoring, payload rendering, and hook enforcement |

## Run

```bash
cd docs/services/azure-monitor/azure-sre-agent/samples/private-aks-fleet-lab
./scripts/deploy.sh rg-private-aks-fleet koreacentral australiaeast
./scripts/seed-faults.sh seed
```

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Clean up

```bash
./scripts/cleanup.sh
```
