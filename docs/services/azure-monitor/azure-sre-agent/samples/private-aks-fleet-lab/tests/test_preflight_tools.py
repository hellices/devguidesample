import json
import subprocess
import sys
import unittest
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SAMPLE_DIR / "agent" / "tools"))
sys.path.insert(0, str(SAMPLE_DIR / "scripts"))

import check_aks_eos_release_calendar as eos_tool  # noqa: E402
import evaluate_aks_upgrade_preflight as preflight_tool  # noqa: E402
import verify_multihub_firewall_route as route_tool  # noqa: E402
import render_agent_config  # noqa: E402


class TestPreflightToolsAndConfig(unittest.TestCase):
    def test_eos_calendar_month_window_and_lts_support_plan(self) -> None:
        # Reference month 2026-11, 4-month window -> up to end of 2027-03:
        # 1) aks-priv-01 (1.36.4, Standard, EOL 2027-06-30) -> 7 months left -> NOT target
        c1 = eos_tool.evaluate_cluster_eos(
            name="aks-priv-01",
            rg="rg-private-aks-fleet",
            location="eastus2",
            version="1.36.4",
            tier="Standard",
            support_plan="KubernetesOfficial",
            tags={"mgmtName": "ENT_Workloads_Prod", "ServiceCode": "ag001101"},
            ref_ym="2026-11",
            window=4,
        )
        self.assertFalse(c1["isUpgradeTarget"])
        self.assertEqual(c1["monthsRemaining"], 7)

        # 2) aks-priv-02 (1.35.9, Standard, EOL 2027-03-31) -> 4 months left -> TARGET
        c2 = eos_tool.evaluate_cluster_eos(
            name="aks-priv-02",
            rg="rg-private-aks-fleet",
            location="eastus2",
            version="1.35.9",
            tier="Standard",
            support_plan="KubernetesOfficial",
            tags={"mgmtName": "ENT_Workloads_Prod_PII", "ServiceCode": "ag002401"},
            ref_ym="2026-11",
            window=4,
        )
        self.assertTrue(c2["isUpgradeTarget"])
        self.assertEqual(c2["monthsRemaining"], 4)
        self.assertEqual(c2["recommendedTargetMinor"], "1.36")

        # 3) aks-priv-03 (1.34.12, Premium / AKSLongTermSupport, LTS EOL 2027-11-30) -> 12 months left -> NOT target
        c3 = eos_tool.evaluate_cluster_eos(
            name="aks-priv-03",
            rg="rg-private-aks-fleet",
            location="eastus2",
            version="1.34.12",
            tier="Premium",
            support_plan="AKSLongTermSupport",
            tags={"mgmtName": "ENT_Workloads_NonProd", "ServiceCode": "ag003501"},
            ref_ym="2026-11",
            window=4,
        )
        self.assertFalse(c3["isUpgradeTarget"])
        self.assertEqual(c3["supportPlan"], "LTS (Premium)")
        self.assertEqual(c3["effectiveEolDate"], "2027-11-30")
        self.assertEqual(c3["monthsRemaining"], 12)

    def test_preflight_all_9_checks_pass_and_compact_size(self) -> None:
        res = preflight_tool.main(
            cluster_name="aks-priv-01",
            current_version="1.36.4",
            target_version="1.37.0",
            subnet_cidr="10.52.11.0/24",
            node_count="2",
            unhealthy_pod_count="0",
            single_replica_deployments="",
            blocking_pdb_count="0",
        )
        encoded = json.dumps(res, ensure_ascii=False)
        self.assertEqual(res["overallStatus"], "PASS")
        self.assertEqual(res["verdict"], "PASS")
        self.assertEqual(res["passCount"], 9)
        self.assertEqual(res["failCount"], 0)
        self.assertTrue(all(v == "PASS" for v in res["checks"].values()))
        self.assertLess(len(encoded), 900, "Output must stay under 900 chars to avoid head-truncation")
        self.assertIn("--no-wait", res["upgradeCmd"])

    def test_preflight_all_9_checks_fail_and_compact_size(self) -> None:
        failed = preflight_tool.main(
            cluster_name="aks-priv-10",
            current_version="1.35.4",
            target_version="1.36.3",
            subnet_cidr="10.52.11.0/28",
            node_count="3",
            max_surge="2",
            cni_overlay="false",
            max_pods_per_node="30",
            naked_or_colocated_pods="payments-canary/naked-audit-shipper",
            local_storage_workloads="payments-canary/naked-audit-shipper(emptyDir),pv/local-pv-01",
            constrained_pods="payments-canary/naked-audit-shipper(nodeSelector:0node)",
            blocking_pdb_count="1",
            deprecated_apis="flowcontrol.apiserver.k8s.io/v1beta3",
            missing_graceful_shutdown="payments-canary/naked-audit-shipper/shipper",
            uami_subnet_role_missing="true",
            mdc_law_resource_id="/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/law-deleted",
            mdc_law_deleted="true",
        )
        encoded = json.dumps(failed, ensure_ascii=False)
        self.assertEqual(failed["overallStatus"], "FAIL")
        self.assertEqual(failed["verdict"], "FAIL")
        self.assertEqual(failed["failCount"], 9)
        self.assertTrue(all(v == "FAIL" for v in failed["checks"].values()))
        self.assertLess(len(encoded), 900, "Even when all 9 checks FAIL, output must stay under 900 chars")

    def test_evaluate_from_raw_k8s_and_arm_snapshots(self) -> None:
        nodes = [
            {"metadata": {"name": "node-1", "labels": {"agentpool": "userpool"}}},
            {"metadata": {"name": "node-2", "labels": {"agentpool": "userpool"}}},
        ]
        pods = [
            {
                "metadata": {
                    "name": "naked-pod",
                    "namespace": "app",
                    "annotations": {
                        "kubectl.kubernetes.io/last-applied-configuration": json.dumps(
                            {"apiVersion": "flowcontrol.apiserver.k8s.io/v1beta3", "kind": "FlowSchema"}
                        )
                    },
                },
                "spec": {
                    "nodeName": "node-1",
                    "nodeSelector": {"dedicated": "gpu-only"},
                    "volumes": [{"name": "cache", "emptyDir": {}}],
                    "containers": [{"name": "web", "image": "nginx:1.25"}],
                },
                "status": {"phase": "Running"},
            }
        ]
        pvs = [{"metadata": {"name": "pv-local-01"}, "spec": {"local": {"path": "/mnt/disks/ssd1"}}}]
        pdbs = [{"metadata": {"name": "web-pdb", "namespace": "app"}, "status": {"disruptionsAllowed": 0}}]

        res = preflight_tool.evaluate_from_snapshots(
            cluster_name="aks-priv-10",
            current_version="1.35.4",
            target_version="1.36.3",
            pods_items=pods,
            pv_items=pvs,
            pdb_items=pdbs,
            nodes_items=nodes,
            subnet_cidr="10.52.11.0/28",
            subnet_used_ips=10,
            node_count=2,
            max_surge=2,
            cni_overlay=True,
            uami_has_subnet_role=False,
            mdc_law_resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/deleted-law",
            mdc_law_exists=False,
        )
        self.assertEqual(res["overallStatus"], "FAIL")
        self.assertEqual(res["failCount"], 9)

        # Verify K8s 1.30+ preStop.sleep and healthy 2-node spread pass
        healthy_pods = [
            {
                "metadata": {
                    "name": f"api-{i}",
                    "namespace": "app",
                    "ownerReferences": [{"kind": "ReplicaSet", "name": "api-rs"}],
                },
                "spec": {
                    "nodeName": f"node-{i}",
                    "containers": [
                        {
                            "name": "api",
                            "livenessProbe": {"httpGet": {"path": "/healthz", "port": 8080}},
                            "readinessProbe": {"httpGet": {"path": "/readyz", "port": 8080}},
                            "lifecycle": {"preStop": {"sleep": {"seconds": 5}}},
                        }
                    ],
                },
                "status": {"phase": "Running"},
            }
            for i in (1, 2)
        ]
        pass_res = preflight_tool.evaluate_from_snapshots(
            cluster_name="aks-priv-08",
            current_version="1.36.3",
            target_version="1.37.0",
            pods_items=healthy_pods,
            pv_items=[],
            pdb_items=[{"metadata": {"name": "api-pdb", "namespace": "app"}, "status": {"disruptionsAllowed": 1}}],
            nodes_items=nodes,
            subnet_cidr="10.52.11.0/24",
            node_count=2,
            max_surge=1,
            cni_overlay=True,
            uami_has_subnet_role=True,
            mdc_law_resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/valid-law",
            mdc_law_exists=True,
        )
        self.assertEqual(pass_res["overallStatus"], "PASS")
        self.assertEqual(pass_res["passCount"], 9)

    def test_route_probe_fast_timeout_and_compact_output(self) -> None:
        res = route_tool.main(
            cluster_name="aks-priv-01",
            api_server_private_ip="203.0.113.254",
            hub_path="Hub1(10.51.250.4)->Hub2(10.52.250.4)",
        )
        encoded = json.dumps(res, ensure_ascii=False)
        self.assertIn("tcp443Reachable", res)
        self.assertLess(len(encoded), 400)

    def test_render_agent_config_modes(self) -> None:
        tools_payload = render_agent_config.render_tools()
        self.assertEqual(tools_payload["kind"], "ToolList")
        self.assertEqual(len(tools_payload["tools"]), 2)

        skill_payload = render_agent_config.render_skill()
        self.assertEqual(skill_payload["name"], "private-aks-upgrade-preflight")
        self.assertIn("kubectl get pods,deploy,pdb", skill_payload["properties"]["skillContent"])

    def test_pre_kubectl_mutation_guard_hook(self) -> None:
        hook_path = SAMPLE_DIR / "agent" / "hooks" / "pre_kubectl_mutation_guard.sh"
        deny_proc = subprocess.run(
            ["bash", str(hook_path)],
            input='{"command":"kubectl delete namespace banking"}',
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(json.loads(deny_proc.stdout)["decision"], "deny")

        allow_proc = subprocess.run(
            ["bash", str(hook_path)],
            input='{"command":"kubectl set image deploy/banking-fx-sync fx=nginx:1.25-alpine -n banking"}',
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(json.loads(allow_proc.stdout)["decision"], "allow")


if __name__ == "__main__":
    unittest.main()
