from __future__ import annotations

import ipaddress
import json
from typing import Any

SYSTEM_NAMESPACES = {
    "kube-system",
    "kube-public",
    "kube-node-lease",
    "gatekeeper-system",
    "calico-system",
    "tigera-operator",
    "azuresre",
}

REMOVED_APIS_BY_MINOR = {
    (1, 25): {"batch/v1beta1", "policy/v1beta1", "autoscaling/v2beta1"},
    (1, 26): {"autoscaling/v2beta2", "flowcontrol.apiserver.k8s.io/v1beta1"},
    (1, 27): {"storage.k8s.io/v1beta1"},
    (1, 29): {"flowcontrol.apiserver.k8s.io/v1beta2"},
    (1, 32): {"flowcontrol.apiserver.k8s.io/v1beta3"},
}


def _parse_minor(version: str) -> tuple[int, int]:
    parts = [p for p in (version or "1.37.0").lstrip("v").split(".") if p.isdigit()]
    if len(parts) >= 2:
        return int(parts[0]), int(parts[1])
    return (1, 37)


def _removed_apis_up_to(target_version: str) -> set[str]:
    target_minor = _parse_minor(target_version)
    removed: set[str] = set()
    for minor, apis in REMOVED_APIS_BY_MINOR.items():
        if minor <= target_minor:
            removed |= apis
    return removed


def evaluate_from_snapshots(
    cluster_name: str,
    current_version: str = "1.36.4",
    target_version: str = "1.37.0",
    pods_items: list[dict[str, Any]] | None = None,
    pv_items: list[dict[str, Any]] | None = None,
    pdb_items: list[dict[str, Any]] | None = None,
    nodes_items: list[dict[str, Any]] | None = None,
    deprecated_apis_found: list[str] | None = None,
    subnet_cidr: str = "10.52.11.0/24",
    subnet_used_ips: int | None = None,
    node_count: int = 2,
    max_surge: int = 1,
    max_pods_per_node: int = 30,
    cni_overlay: bool = True,
    uami_has_subnet_role: bool = True,
    mdc_law_resource_id: str = "",
    mdc_law_exists: bool = True,
) -> dict[str, Any]:
    """Evaluates all 9 AKS upgrade preflight checks from raw K8s/ARM snapshots using strict PASS/FAIL criteria."""
    pods = pods_items or []
    pvs = pv_items or []
    pdbs = pdb_items or []
    nodes = nodes_items or []

    node_labels_map: dict[str, dict[str, str]] = {}
    for n in nodes:
        n_name = n.get("metadata", {}).get("name", "")
        if n_name:
            node_labels_map[n_name] = n.get("metadata", {}).get("labels", {}) or {}

    naked_pods: list[str] = []
    controller_nodes: dict[str, set[str]] = {}
    controller_counts: dict[str, int] = {}
    local_storage_Hits: list[str] = []
    scheduling_Hits: list[str] = []
    graceful_Hits: list[str] = []
    manifest_deprecated: list[str] = list(deprecated_apis_found or [])
    removed_set = _removed_apis_up_to(target_version)

    for pod in pods:
        meta = pod.get("metadata", {}) or {}
        ns = meta.get("namespace", "default")
        if ns in SYSTEM_NAMESPACES:
            continue
        p_name = f"{ns}/{meta.get('name', 'pod')}"
        spec = pod.get("spec", {}) or {}
        status = pod.get("status", {}) or {}
        if status.get("phase") in ("Succeeded", "Failed"):
            continue

        owners = meta.get("ownerReferences") or []
        owner_kinds = {o.get("kind") for o in owners}
        is_daemonset = "DaemonSet" in owner_kinds
        is_job = "Job" in owner_kinds

        # 1) Pod HA: naked pod or controller pods all on single node / single replica
        if not owners:
            naked_pods.append(p_name)
        elif not is_daemonset and not is_job:
            owner_key = f"{ns}/{owners[0].get('kind')}/{owners[0].get('name')}"
            controller_counts[owner_key] = controller_counts.get(owner_key, 0) + 1
            if spec.get("nodeName"):
                controller_nodes.setdefault(owner_key, set()).add(spec["nodeName"])

        # 2) HostPath / emptyDir on non-DaemonSet pods
        if not is_daemonset:
            for vol in spec.get("volumes") or []:
                if "hostPath" in vol or "emptyDir" in vol:
                    v_type = "hostPath" if "hostPath" in vol else "emptyDir"
                    local_storage_Hits.append(f"{p_name}({v_type})")
                    break

        # 3) Scheduling constraints (nodeSelector, required nodeAffinity)
        if not is_daemonset:
            node_sel = spec.get("nodeSelector") or {}
            affinity = (spec.get("affinity") or {}).get("nodeAffinity") or {}
            req_terms = (
                affinity.get("requiredDuringSchedulingIgnoredDuringExecution") or {}
            ).get("nodeSelectorTerms") or []
            if node_sel:
                if node_labels_map:
                    matching = [
                        n
                        for n, lbls in node_labels_map.items()
                        if all(lbls.get(k) == v for k, v in node_sel.items())
                    ]
                    if len(matching) < 2:
                        scheduling_Hits.append(f"{p_name}(nodeSelector:{len(matching)}node)")
                else:
                    scheduling_Hits.append(f"{p_name}(nodeSelector)")
            elif req_terms:
                scheduling_Hits.append(f"{p_name}(requiredNodeAffinity)")

        # 5) Deprecated API inside last-applied-configuration annotation
        last_cfg = (meta.get("annotations") or {}).get(
            "kubectl.kubernetes.io/last-applied-configuration"
        )
        if last_cfg:
            try:
                parsed_cfg = json.loads(last_cfg)
                api_ver = parsed_cfg.get("apiVersion", "")
                if api_ver in removed_set:
                    manifest_deprecated.append(f"{p_name}:{api_ver}")
            except ValueError:
                pass

        # 6) Graceful Shutdown: livenessProbe, readinessProbe, preStop (including K8s 1.29+ native sidecars)
        if not is_job:
            containers = list(spec.get("containers") or [])
            for ic in spec.get("initContainers") or []:
                if ic.get("restartPolicy") == "Always":
                    containers.append(ic)
            for c in containers:
                has_live = c.get("livenessProbe") is not None
                has_ready = c.get("readinessProbe") is not None
                has_prestop = bool((c.get("lifecycle") or {}).get("preStop"))
                if not (has_live and has_ready and has_prestop):
                    graceful_Hits.append(f"{p_name}/{c.get('name', 'c')}")
                    break

    for pv in pvs:
        pv_name = (pv.get("metadata") or {}).get("name", "pv")
        pv_spec = pv.get("spec") or {}
        if "local" in pv_spec or "hostPath" in pv_spec:
            local_storage_Hits.append(f"pv/{pv_name}")

    single_or_colocated = [
        k
        for k, cnt in controller_counts.items()
        if cnt < 2 or len(controller_nodes.get(k, set())) == 1
    ]

    pdb_Hits: list[str] = []
    for pdb in pdbs:
        meta = pdb.get("metadata") or {}
        st = pdb.get("status") or {}
        if int(st.get("disruptionsAllowed", 1)) == 0:
            pdb_Hits.append(f"{meta.get('namespace', 'default')}/{meta.get('name', 'pdb')}")

    return main(
        cluster_name=cluster_name,
        current_version=current_version,
        target_version=target_version,
        subnet_cidr=subnet_cidr,
        node_count=str(node_count),
        max_surge=str(max_surge),
        max_pods_per_node=str(max_pods_per_node),
        cni_overlay="true" if cni_overlay else "false",
        subnet_used_ips=str(subnet_used_ips) if subnet_used_ips is not None else "",
        naked_or_colocated_pods=",".join(naked_pods + single_or_colocated),
        local_storage_workloads=",".join(local_storage_Hits),
        constrained_pods=",".join(scheduling_Hits),
        blocking_pdb_count=str(len(pdb_Hits)),
        deprecated_apis=",".join(manifest_deprecated),
        missing_graceful_shutdown=",".join(graceful_Hits),
        uami_subnet_role_missing="false" if uami_has_subnet_role else "true",
        mdc_law_resource_id=mdc_law_resource_id,
        mdc_law_deleted="true" if (mdc_law_resource_id and not mdc_law_exists) else "false",
    )


def main(
    cluster_name: str,
    current_version: str = "1.36.4",
    target_version: str = "1.37.0",
    subnet_cidr: str = "10.52.11.0/24",
    node_count: str = "1",
    unhealthy_pod_count: str = "0",
    single_replica_deployments: str = "",
    blocking_pdb_count: str = "0",
    naked_or_colocated_pods: str = "",
    local_storage_workloads: str = "",
    constrained_pods: str = "",
    deprecated_apis: str = "",
    missing_graceful_shutdown: str = "",
    max_surge: str = "1",
    max_pods_per_node: str = "30",
    cni_overlay: str = "true",
    subnet_used_ips: str = "",
    uami_subnet_role_missing: str = "false",
    mdc_law_resource_id: str = "",
    mdc_law_deleted: str = "false",
) -> dict[str, Any]:
    """Evaluates the 9 AKS upgrade preflight checks with strict PASS/FAIL criteria and returns a compact (<900 chars) JSON payload."""
    net = ipaddress.ip_network(subnet_cidr or "10.52.11.0/24", strict=False)
    usable_ips = max(net.num_addresses - 5, 1)
    nodes = max(int(node_count or 1), 1)
    surge = max(int(max_surge or 1), 1)
    max_pods = max(int(max_pods_per_node or 30), 1)
    is_overlay = str(cni_overlay).lower() not in ("false", "0", "no")

    if subnet_used_ips != "":
        used_ips = int(subnet_used_ips)
    else:
        used_ips = nodes * 2 + 4 if is_overlay else nodes * (max_pods + 1)

    required_surge_ips = surge if is_overlay else surge * (max_pods + 1)
    free_ips = usable_ips - used_ips
    ip_usage_pct = round(((used_ips + required_surge_ips) / usable_ips) * 100, 1)

    def _split(val: str) -> list[str]:
        return [x.strip() for x in (val or "").split(",") if x.strip()]

    ha_list = _split(naked_or_colocated_pods) + _split(single_replica_deployments)
    upods = int(unhealthy_pod_count or 0)
    if upods > 0:
        ha_list.append(f"unhealthyPods:{upods}")
    storage_list = _split(local_storage_workloads)
    sched_list = _split(constrained_pods)
    bpdb = int(blocking_pdb_count or 0)
    dep_list = _split(deprecated_apis)
    grace_list = _split(missing_graceful_shutdown)
    uami_missing = str(uami_subnet_role_missing).lower() in ("true", "1", "yes")
    law_deleted = str(mdc_law_deleted).lower() in ("true", "1", "yes")

    checks = {
        "1_pod_ha": "FAIL" if ha_list else "PASS",
        "2_local_storage": "FAIL" if storage_list else "PASS",
        "3_scheduling_constraints": "FAIL" if sched_list else "PASS",
        "4_pdb_disruptions": "FAIL" if bpdb > 0 else "PASS",
        "5_api_deprecation": "FAIL" if dep_list else "PASS",
        "6_graceful_shutdown": "FAIL" if grace_list else "PASS",
        "7_subnet_ips": "FAIL" if (free_ips < required_surge_ips or ip_usage_pct > 90) else "PASS",
        "8_uami_permissions": "FAIL" if uami_missing else "PASS",
        "9_mdc_law_reference": "FAIL" if law_deleted else "PASS",
    }

    def _short(items: list[str]) -> str:
        return ",".join(x.split("/")[-1][:32] for x in items[:2])

    failed_details: list[str] = []
    if checks["1_pod_ha"] == "FAIL":
        failed_details.append(f"1_ha:{_short(ha_list)}")
    if checks["2_local_storage"] == "FAIL":
        failed_details.append(f"2_storage:{_short(storage_list)}")
    if checks["3_scheduling_constraints"] == "FAIL":
        failed_details.append(f"3_sched:{_short(sched_list)}")
    if checks["4_pdb_disruptions"] == "FAIL":
        failed_details.append(f"4_pdb:disruptions=0({bpdb})")
    if checks["5_api_deprecation"] == "FAIL":
        failed_details.append(f"5_api:{_short(dep_list)}")
    if checks["6_graceful_shutdown"] == "FAIL":
        failed_details.append(f"6_probe:{_short(grace_list)}")
    if checks["7_subnet_ips"] == "FAIL":
        failed_details.append(f"7_ip:free={free_ips}<need={required_surge_ips}")
    if checks["8_uami_permissions"] == "FAIL":
        failed_details.append("8_uami:MissingSubnetRole")
    if checks["9_mdc_law_reference"] == "FAIL":
        law_name = (mdc_law_resource_id.rsplit("/", 1)[-1] if mdc_law_resource_id else "deleted-law")[:24]
        failed_details.append(f"9_law:404({law_name})")

    fail_count = sum(1 for v in checks.values() if v == "FAIL")
    overall_status = "PASS" if fail_count == 0 else "FAIL"
    score = max(100 - fail_count * 15, 0)

    return {
        "cluster": cluster_name,
        "path": f"{current_version}->{target_version}",
        "overallStatus": overall_status,
        "verdict": overall_status,
        "passCount": 9 - fail_count,
        "failCount": fail_count,
        "score": score,
        "subnetFreeIps": free_ips,
        "checks": checks,
        "issues": failed_details or ["All 9 checks PASS"],
        "upgradeCmd": f"az aks upgrade -g rg-private-aks-fleet -n {cluster_name} --kubernetes-version {target_version} --yes --no-wait",
    }
