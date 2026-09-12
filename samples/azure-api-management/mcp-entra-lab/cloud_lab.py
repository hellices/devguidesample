"""Create and validate only an explicitly isolated MCP lab; keep state private."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
from typing import Any


SAMPLE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SAMPLE_ROOT.parents[2]
ENTRY = SAMPLE_ROOT / "infra" / "entry.bicep"


def private_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise ValueError("cloud state must be outside the public repository")
    return resolved


def write_private(path: Path, text: str) -> None:
    path = private_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.stat().st_mode & 0o077:
        raise ValueError("use a dedicated private state directory with mode 0700")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as temporary:
        temporary.write(text)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def save_state(path: Path, state: dict) -> None:
    write_private(path, json.dumps(state, indent=2) + "\n")


def load_state(path: Path) -> dict:
    return json.loads(private_path(path).read_text(encoding="utf-8"))


def new_state(account: dict, operator: str, location: str, suffix: str) -> dict:
    if not re.fullmatch(r"[a-z0-9]{6,10}", suffix):
        raise ValueError("invalid lab suffix")
    if not re.fullmatch(r"[a-z]+[0-9]?", location):
        raise ValueError("invalid Azure region")
    return {
        "subscription_id": account["id"],
        "tenant_id": account["tenantId"],
        "operator_id": operator,
        "location": location,
        "suffix": suffix,
        "resource_group": f"rg-mcplab-{suffix}",
        "deployment_name": f"mcp-lab-{suffix}",
        "expires_on": (
            datetime.now(timezone.utc) + timedelta(days=2)
        ).date().isoformat(),
        "stage": "planned",
        "foundation_outputs": {},
    }


def deployment_parameters(state: dict) -> dict:
    values = {
        "resourceGroupName": state["resource_group"],
        "location": state["location"],
        "suffix": state["suffix"],
        "operatorObjectId": state["operator_id"],
        "expiresOn": state["expires_on"],
    }
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {name: {"value": value} for name, value in values.items()},
    }


def verify_create_only(result: dict) -> None:
    changes = result.get("changes", [])
    kinds = {change["changeType"] for change in changes}
    if kinds - {"Create", "Ignore"}:
        raise ValueError(f"what-if is not create-only: {sorted(kinds)}")
    if "Create" not in kinds:
        raise ValueError("what-if contains no creates")


def az_json(arguments: list[str], state_path: Path, *, timeout: int = 180) -> Any:
    result = subprocess.run(
        ["az", *arguments, "--only-show-errors", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode:
        error_path = state_path.with_name("last-azure-error.txt")
        write_private(error_path, result.stderr)
        codes = sorted(set(re.findall(r"\b(?:AADSTS\d+|[A-Za-z]+Failed)\b", result.stderr)))
        raise RuntimeError(
            f"Azure command {' '.join(arguments[:3])} failed "
            f"(exit {result.returncode}, codes={codes}); "
            "inspect last-azure-error.txt in the private state directory"
        )
    return json.loads(result.stdout) if result.stdout.strip() else None


def create_plan(path: Path, location: str) -> None:
    if private_path(path).exists():
        raise ValueError("state already exists; resume it instead of replacing it")
    account = az_json(["account", "show"], path)
    if account["user"]["type"] != "user":
        raise ValueError("this delegated-user lab requires an Azure CLI user login")
    operator = az_json(["ad", "signed-in-user", "show", "--query", "id"], path)
    state = new_state(account, operator, location, secrets.token_hex(4))
    exists = az_json(
        ["group", "exists", "--name", state["resource_group"],
         "--subscription", state["subscription_id"]],
        path,
    )
    if exists:
        raise ValueError("refusing to adopt an existing resource group")
    save_state(path, state)
    print("Private plan saved. No Azure resources created.")


def validate_foundation(path: Path) -> None:
    state = load_state(path)
    if state["stage"] != "planned":
        raise ValueError("initial create-only validation requires a planned lab")
    parameter_file = path.with_name("foundation.parameters.json")
    save_state(parameter_file, deployment_parameters(state))
    common = [
        "--location", state["location"], "--name", state["deployment_name"],
        "--subscription", state["subscription_id"], "--template-file", str(ENTRY),
        "--parameters", f"@{parameter_file}",
    ]
    az_json(["deployment", "sub", "validate", *common], path, timeout=900)
    preview = az_json(
        ["deployment", "sub", "what-if", "--no-pretty-print", *common],
        path, timeout=900,
    )
    save_state(path.with_name("foundation.what-if.json"), preview)
    verify_create_only(preview)
    state["stage"] = "validated"
    save_state(path, state)
    print("ARM validation passed; what-if contains only new/ignored resources.")


def assert_owned_group(state: dict, path: Path) -> bool:
    exists = az_json(
        ["group", "exists", "--name", state["resource_group"],
         "--subscription", state["subscription_id"]], path
    )
    if not exists:
        return False
    group = az_json(
        ["group", "show", "--name", state["resource_group"],
         "--subscription", state["subscription_id"]], path
    )
    tags = group.get("tags", {})
    if (
        tags.get("labId") != state["suffix"]
        or tags.get("purpose") != "mcp-entra-validation"
        or state["resource_group"] != f"rg-mcplab-{state['suffix']}"
    ):
        raise ValueError("resource group is not owned by this lab state")
    return True


def deploy_foundation(path: Path) -> None:
    state = load_state(path)
    if state["stage"] not in {"validated", "deploying"}:
        raise ValueError("run validation before deployment")
    if assert_owned_group(state, path) and state["stage"] != "deploying":
        raise ValueError("resource group appeared after validation; refusing adoption")
    state["stage"] = "deploying"
    save_state(path, state)
    result = az_json(
        [
            "deployment", "sub", "create",
            "--location", state["location"], "--name", state["deployment_name"],
            "--subscription", state["subscription_id"],
            "--template-file", str(ENTRY),
            "--parameters", f"@{path.with_name('foundation.parameters.json')}",
        ],
        path,
        timeout=7200,
    )
    provisioning = result["properties"]["provisioningState"]
    if provisioning != "Succeeded":
        raise RuntimeError(f"foundation provisioning did not succeed: {provisioning}")
    state["foundation_outputs"] = result["properties"]["outputs"]["foundationOutputs"]["value"]
    state["stage"] = "foundation-ready"
    save_state(path, state)
    print("Foundation provisioning: Succeeded. Endpoints are in private state only.")


def status(path: Path) -> None:
    state = load_state(path)
    print(json.dumps({"stage": state["stage"]}))
    if state["stage"] == "deploying":
        result = az_json(
            ["deployment", "sub", "show", "--name", state["deployment_name"],
             "--subscription", state["subscription_id"],
             "--query", "properties.provisioningState"],
            path,
        )
        print(json.dumps({"azure_provisioning_state": result}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument(
        "command", choices=["plan", "validate", "deploy-foundation", "status"]
    )
    parser.add_argument("--location", default="koreacentral")
    args = parser.parse_args()
    path = private_path(args.state)
    if args.command == "plan":
        create_plan(path, args.location)
    elif args.command == "validate":
        validate_foundation(path)
    elif args.command == "deploy-foundation":
        deploy_foundation(path)
    else:
        status(path)


if __name__ == "__main__":
    main()
