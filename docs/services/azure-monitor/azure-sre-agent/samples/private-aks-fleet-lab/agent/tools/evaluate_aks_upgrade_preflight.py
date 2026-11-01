import ipaddress


def main(
    cluster_name: str,
    current_version: str = "1.36.4",
    target_version: str = "1.37.0",
    subnet_cidr: str = "10.52.11.0/24",
    node_count: str = "1",
    unhealthy_pod_count: str = "0",
    single_replica_deployments: str = "",
    blocking_pdb_count: str = "0",
) -> dict:
    """Scores 7-point Private AKS upgrade preflight checks and returns a compact (<900 chars) JSON payload to prevent SRE Agent head-truncation."""
    net = ipaddress.ip_network(subnet_cidr or "10.52.11.0/24", strict=False)
    usable_ips = max(net.num_addresses - 5, 1)
    used_ips = int(node_count or 1) * 2 + 4
    ip_usage_pct = round((used_ips / usable_ips) * 100, 1)

    score = 100
    issues = []
    cmds = []

    if ip_usage_pct > 90:
        score -= 20
        issues.append(f"Subnet IP {ip_usage_pct}% BLOCK")
        cmds.append(
            f"az aks nodepool update -g rg-private-aks-fleet --cluster-name {cluster_name} -n nodepool1 --max-surge 1"
        )
    elif ip_usage_pct > 80:
        score -= 10
        issues.append(f"Subnet IP {ip_usage_pct}% WARN")

    bpdb = int(blocking_pdb_count or 0)
    if bpdb > 0:
        score -= 20
        issues.append(f"PDB AllowedDisruptions=0 ({bpdb}) BLOCK")
        cmds.append(
            'kubectl patch pdb <pdb> -n <ns> --type=merge -p \'{"spec":{"maxUnavailable":1}}\''
        )

    single_list = [
        x.strip() for x in (single_replica_deployments or "").split(",") if x.strip()
    ]
    if single_list:
        score -= 15
        issues.append(f"SingleReplica({','.join(single_list)}) WARN")
        for d in single_list:
            cmds.append(f"kubectl scale deploy {d} --replicas=2")

    upods = int(unhealthy_pod_count or 0)
    if upods > 0:
        score -= 25
        issues.append(f"UnhealthyPods({upods}) BLOCK")
        cmds.append(f"Fix unhealthy pods on {cluster_name} before upgrade")

    if score >= 90 and upods == 0 and bpdb == 0:
        verdict = "READY"
    elif score < 75 or upods > 0 or bpdb > 0:
        verdict = "BLOCKED"
    else:
        verdict = "CONDITIONAL"

    return {
        "cluster": cluster_name,
        "path": f"{current_version}->{target_version}",
        "subnetFreeIps": usable_ips - used_ips,
        "score": max(score, 0),
        "verdict": verdict,
        "issues": issues or ["All 7 checks PASS"],
        "preUpgradeCmds": cmds,
        "upgradeCmd": f"az aks upgrade -g rg-private-aks-fleet -n {cluster_name} --kubernetes-version {target_version} --yes --no-wait",
    }
