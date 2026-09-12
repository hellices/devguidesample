"""Build and deploy application stages only inside the already-owned lab group."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
from typing import Any

from cloud_lab import (
    SAMPLE_ROOT, assert_owned_group, az_json, load_state, private_path, save_state,
)
from entra_setup import AZURE_CLI_CLIENT_ID, VS_CODE_CLIENT_ID, verify_binding


def verify_scoped_preview(preview: dict, group_id: str) -> None:
    for change in preview.get("changes", []):
        if change["changeType"] not in {"Create", "Modify", "NoChange", "Ignore"}:
            raise ValueError("unsafe or unanalyzed deployment change")
        if not change["resourceId"].casefold().startswith(group_id.casefold() + "/"):
            raise ValueError("deployment change is outside the owned lab group")


class ApplicationStage:
    def __init__(self, state_path: Path):
        self.path = private_path(state_path)
        self.state = load_state(self.path)
        if not assert_owned_group(self.state, self.path):
            raise ValueError("deploy the isolated foundation resource group first")
        self.identities = load_state(self.path.with_name("identities.json"))
        verify_binding(self.identities, self.state)
        self.common = [
            "--resource-group", self.state["resource_group"],
            "--subscription", self.state["subscription_id"],
        ]
        self.group_id = (
            f"/subscriptions/{self.state['subscription_id']}"
            f"/resourceGroups/{self.state['resource_group']}"
        )

    def azure(self, args: list[str], timeout: int = 180) -> Any:
        return az_json(args, self.path, timeout=timeout)

    def environment(self) -> dict:
        environment = self.azure([
            "containerapp", "env", "show",
            "--name", "cae-mcplab-" + self.state["suffix"], *self.common,
        ])
        properties = environment["properties"]
        if (
            properties["provisioningState"] != "Succeeded"
            or properties["vnetConfiguration"]["internal"] is not True
        ):
            raise ValueError("the internal Container Apps environment is not ready")
        return environment

    def registry(self) -> dict:
        registry = self.azure([
            "acr", "show", "--name", "acrmcplab" + self.state["suffix"], *self.common,
        ])
        if registry["provisioningState"] != "Succeeded" or registry["adminUserEnabled"]:
            raise ValueError("the private-credential-free registry configuration is not ready")
        return registry

    def build(self) -> None:
        registry = self.registry()
        paths = [
            SAMPLE_ROOT / "Dockerfile",
            SAMPLE_ROOT / "requirements.txt",
            *sorted((SAMPLE_ROOT / "service").rglob("*.py")),
        ]
        digest = hashlib.sha256()
        for path in paths:
            digest.update(str(path.relative_to(SAMPLE_ROOT)).encode())
            digest.update(path.read_bytes())
        tag = "mcp-lab:" + digest.hexdigest()[:12]
        result = self.azure([
            "acr", "build", "--registry", registry["name"], *self.common,
            "--image", tag, "--file", str(SAMPLE_ROOT / "Dockerfile"),
            "--platform", "linux/amd64", "--timeout", "1800", "--no-logs",
            str(SAMPLE_ROOT),
        ], timeout=2400)
        save_state(self.path.with_name("build-run.json"), result)
        if result["status"] != "Succeeded":
            raise RuntimeError(f"container build did not succeed: {result['status']}")
        image_digest = self.azure([
            "acr", "repository", "show", "--name", registry["name"],
            "--subscription", self.state["subscription_id"],
            "--image", tag, "--query", "digest",
        ])
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest):
            raise ValueError("registry returned an invalid image digest")
        save_state(self.path.with_name("image.json"), {
            "image": f"{registry['loginServer']}/mcp-lab@{image_digest}",
            "tag": tag,
            "status": result["status"],
        })
        print("Dockerless ACR build succeeded; immutable image reference saved privately.")

    def deploy(self, template: str, name: str, parameters: dict) -> dict:
        parameter_file = self.path.with_name(name + ".parameters.json")
        save_state(parameter_file, {
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
            "contentVersion": "1.0.0.0",
            "parameters": {key: {"value": value} for key, value in parameters.items()},
        })
        arguments = [
            *self.common, "--name", name,
            "--template-file", str(SAMPLE_ROOT / "infra" / template),
            "--parameters", f"@{parameter_file}",
        ]
        self.azure(["deployment", "group", "validate", *arguments], timeout=900)
        preview = self.azure([
            "deployment", "group", "what-if", "--no-pretty-print", *arguments,
        ], timeout=900)
        save_state(self.path.with_name(name + ".what-if.json"), preview)
        verify_scoped_preview(preview, self.group_id)
        result = self.azure(
            ["deployment", "group", "create", *arguments], timeout=3600
        )
        if result["properties"]["provisioningState"] != "Succeeded":
            raise RuntimeError("application-stage deployment did not succeed")
        outputs = {
            key: value["value"]
            for key, value in result["properties"]["outputs"].items()
        }
        save_state(self.path.with_name(name + ".json"), outputs)
        print(name + ": Succeeded. Runtime verification is still required.")
        return outputs

    def apps(self) -> None:
        environment = self.environment()
        registry = self.registry()
        identity = self.azure([
            "identity", "show", "--name", "id-mcp-app-" + self.state["suffix"],
            *self.common,
        ])
        roles = self.azure([
            "role", "assignment", "list", "--assignee", identity["principalId"],
            "--scope", registry["id"], "--subscription", self.state["subscription_id"],
            "--query", "[].roleDefinitionName",
        ])
        if "AcrPull" not in roles:
            raise ValueError("AcrPull assignment is missing; do not deploy the image yet")
        image = load_state(self.path.with_name("image.json"))["image"]
        if not image.startswith(registry["loginServer"] + "/mcp-lab@sha256:"):
            raise ValueError("image does not belong to the new lab registry")
        custom = self.identities["custom_api"]
        azure = self.identities["azure_api"]
        if not azure.get("federation_configured"):
            raise ValueError("configure native Azure MCP confidential-client federation first")
        self.deploy("apps.bicep", "mcp-apps", {
            "location": self.state["location"],
            "suffix": self.state["suffix"],
            "environmentName": environment["name"],
            "environmentDomain": environment["properties"]["defaultDomain"],
            "environmentStaticIp": environment["properties"]["staticIp"],
            "vnetId": environment["properties"]["vnetConfiguration"]["infrastructureSubnetId"].rsplit("/subnets/", 1)[0],
            "appIdentityId": identity["id"],
            "appIdentityClientId": identity["clientId"],
            "registryHost": registry["loginServer"],
            "pythonImage": image,
            "tenantId": self.state["tenant_id"],
            "customApiClientId": custom["client_id"],
            "customApiClientSecret": custom["client_secret"],
            "azureApiClientId": azure["client_id"],
            "allowedClientIds": ",".join([
                AZURE_CLI_CLIENT_ID, self.identities["public_client"]["client_id"],
            ]),
            "nativeAllowedClientIds": [
                AZURE_CLI_CLIENT_ID, self.identities["public_client"]["client_id"], VS_CODE_CLIENT_ID,
            ],
        })

    def apim(self) -> None:
        service = self.azure([
            "apim", "show", "--name", "apim-mcplab-" + self.state["suffix"],
            *self.common,
        ])
        if (
            service["provisioningState"] != "Succeeded"
            or service["virtualNetworkType"] != "Internal"
        ):
            raise ValueError("the internal APIM lab service is not ready")
        apps = load_state(self.path.with_name("mcp-apps.json"))
        custom = self.identities["custom_api"]
        self.deploy("apim.bicep", "mcp-apim", {
            "serviceName": service["name"],
            "gatewayUrl": service["gatewayUrl"].rstrip("/"),
            "backendUrl": apps["pythonUrl"],
            "tenantId": self.state["tenant_id"],
            "apiClientId": custom["client_id"],
            "allowedClientIds": [
                AZURE_CLI_CLIENT_ID, self.identities["public_client"]["client_id"],
            ],
            "scopeUri": custom["identifier_uri"] + "/" + custom["scope_name"],
        })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("command", choices=["build", "deploy-apps", "deploy-apim"])
    args = parser.parse_args()
    stage = ApplicationStage(args.state)
    if args.command == "build":
        stage.build()
    elif args.command == "deploy-apps":
        stage.apps()
    else:
        stage.apim()


if __name__ == "__main__":
    main()
