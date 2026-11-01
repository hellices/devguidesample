#!/usr/bin/env python3
"""Renders SRE Agent data-plane payloads for tools, skills, hooks, and custom instructions."""
from pathlib import Path
import json
import sys

SAMPLE_DIR = Path(__file__).resolve().parent.parent
AGENT_DIR = SAMPLE_DIR / "agent"


def render_tools() -> dict:
    eval_code = (AGENT_DIR / "tools" / "evaluate_aks_upgrade_preflight.py").read_text(encoding="utf-8")
    route_code = (AGENT_DIR / "tools" / "verify_multihub_firewall_route.py").read_text(encoding="utf-8")
    return {
        "kind": "ToolList",
        "tools": [
            {
                "name": "evaluate-aks-upgrade-preflight",
                "type": "PythonFunctionTool",
                "description": "Fast(<200ms, <900 chars) 7-point Private AKS upgrade preflight scorer returning score (0-100), READY/CONDITIONAL/BLOCKED verdict, and remediation CLI.",
                "timeoutSeconds": 20,
                "toolMode": "Auto",
                "parameters": [
                    {"name": "cluster_name", "type": "string", "description": "AKS cluster name", "required": True},
                    {"name": "current_version", "type": "string", "description": "Current K8s version", "required": False},
                    {"name": "target_version", "type": "string", "description": "Target K8s version", "required": False},
                    {"name": "subnet_cidr", "type": "string", "description": "Node subnet CIDR", "required": False},
                    {"name": "node_count", "type": "string", "description": "Node count", "required": False},
                    {"name": "unhealthy_pod_count", "type": "string", "description": "Unhealthy pod count", "required": False},
                    {"name": "single_replica_deployments", "type": "string", "description": "Comma-separated single-replica deployments", "required": False},
                    {"name": "blocking_pdb_count", "type": "string", "description": "PDBs with AllowedDisruptions==0", "required": False},
                ],
                "functionCode": eval_code,
            },
            {
                "name": "verify-multihub-firewall-udr-route",
                "type": "PythonFunctionTool",
                "description": "Fast(1.5s timeout, <400 chars) TCP 443 socket probe from SRE Agent subnet (10.42.4.0/24) over Multi-Hub Firewall UDR to Private AKS API server.",
                "timeoutSeconds": 20,
                "toolMode": "Auto",
                "parameters": [
                    {"name": "cluster_name", "type": "string", "description": "AKS cluster name", "required": True},
                    {"name": "api_server_private_ip", "type": "string", "description": "Private IP of kube-apiserver PE", "required": True},
                    {"name": "hub_path", "type": "string", "description": "Firewall hop chain label", "required": False},
                ],
                "functionCode": route_code,
            },
        ],
    }


def render_skill() -> dict:
    skill_md = (AGENT_DIR / "skills" / "private-aks-upgrade-preflight.md").read_text(encoding="utf-8")
    return {
        "name": "private-aks-upgrade-preflight",
        "type": "Skill",
        "properties": {
            "description": "Fast 30-60s Private AKS version upgrade target identification, release-note analysis via MS Learn MCP, and 7-point preflight scoring.",
            "tools": [
                "evaluate-aks-upgrade-preflight",
                "verify-multihub-firewall-udr-route",
            ],
            "skillContent": skill_md,
            "additionalFiles": [],
        },
    }


def render_instructions() -> dict:
    text = (AGENT_DIR / "custom-instructions.md").read_text(encoding="utf-8")
    return {"customInstructions": text}


def render_hook() -> dict:
    script = (AGENT_DIR / "hooks" / "pre_kubectl_mutation_guard.sh").read_text(encoding="utf-8")
    return {
        "name": "pre-kubectl-mutation-safety-gate",
        "type": "GlobalHook",
        "properties": {
            "description": "Blocks destructive cluster-level kubectl operations (delete node/ns, drain, cordon).",
            "eventType": "PreToolUse",
            "activationMode": "always",
            "matcher": "RunKubectlWriteCommand",
            "hook": {
                "type": "command",
                "script": script,
                "timeoutSeconds": 10,
            },
        },
    }


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: render_agent_config.py [tools|skill|instructions|hook]")
    mode = sys.argv[1]
    dispatch = {
        "tools": render_tools,
        "skill": render_skill,
        "instructions": render_instructions,
        "hook": render_hook,
    }
    if mode not in dispatch:
        raise SystemExit(f"Unknown mode: {mode}")
    print(json.dumps(dispatch[mode](), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
