import json
import subprocess
import sys
import unittest
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SAMPLE_DIR / "agent" / "tools"))
sys.path.insert(0, str(SAMPLE_DIR / "scripts"))

import evaluate_aks_upgrade_preflight as preflight_tool  # noqa: E402
import verify_multihub_firewall_route as route_tool  # noqa: E402
import render_agent_config  # noqa: E402


class TestPreflightToolsAndConfig(unittest.TestCase):
    def test_preflight_ready_verdict_and_compact_size(self) -> None:
        res = preflight_tool.main(
            cluster_name="aks-priv-01",
            current_version="1.36.4",
            target_version="1.37.0",
            subnet_cidr="10.52.11.0/24",
            node_count="1",
            unhealthy_pod_count="0",
            single_replica_deployments="",
            blocking_pdb_count="0",
        )
        encoded = json.dumps(res, ensure_ascii=False)
        self.assertEqual(res["verdict"], "READY")
        self.assertEqual(res["score"], 100)
        self.assertLess(len(encoded), 900, "Output must stay under 900 chars to avoid head-truncation")
        self.assertIn("--no-wait", res["upgradeCmd"])

    def test_preflight_conditional_and_blocked_verdicts(self) -> None:
        cond = preflight_tool.main(
            cluster_name="aks-priv-06",
            single_replica_deployments="sms-gateway-single",
            unhealthy_pod_count="0",
            blocking_pdb_count="0",
        )
        self.assertEqual(cond["verdict"], "CONDITIONAL")
        self.assertEqual(cond["score"], 85)

        blocked = preflight_tool.main(
            cluster_name="aks-priv-10",
            unhealthy_pod_count="2",
            blocking_pdb_count="1",
        )
        self.assertEqual(blocked["verdict"], "BLOCKED")
        self.assertLessEqual(blocked["score"], 55)

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
