"""Register lab-owned applications and consent only the current user's delegation."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid
from typing import Any

from cloud_lab import az_json, load_state, private_path, save_state


AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
VS_CODE_CLIENT_ID = "aebc6443-996d-45c2-90f0-388ff96faa56"
ARM_APP_ID = "797f4846-ba00-4fd7-ba43-dac1f8f63013"
GRAPH = "https://graph.microsoft.com/v1.0"


def public_client_manifest(name: str) -> dict:
    return {
        "displayName": name,
        "signInAudience": "AzureADMyOrg",
        "publicClient": {"redirectUris": ["http://localhost"]},
        "isFallbackPublicClient": True,
    }


def api_manifest(
    name: str, scope_id: str, scope_name: str, public_client: str, arm_scope: str
) -> dict:
    return {
        "displayName": name,
        "signInAudience": "AzureADMyOrg",
        "api": {
            "requestedAccessTokenVersion": 2,
            "oauth2PermissionScopes": [{
                "id": scope_id, "value": scope_name, "type": "User", "isEnabled": True,
                "adminConsentDisplayName": "Use isolated MCP lab",
                "adminConsentDescription": "Use the isolated lab as the signed-in user.",
                "userConsentDisplayName": "Use isolated MCP lab",
                "userConsentDescription": "Use the isolated lab with your own permissions.",
            }],
            "preAuthorizedApplications": [
                {"appId": app_id, "delegatedPermissionIds": [scope_id]}
                for app_id in (AZURE_CLI_CLIENT_ID, public_client)
            ],
        },
        "requiredResourceAccess": [{
            "resourceAppId": ARM_APP_ID,
            "resourceAccess": [{"id": arm_scope, "type": "Scope"}],
        }],
    }


def delegated_grant(client_sp: str, resource_sp: str, operator: str) -> dict:
    return {
        "clientId": client_sp,
        "resourceId": resource_sp,
        "consentType": "Principal",
        "principalId": operator,
        "scope": "user_impersonation",
    }


def verify_binding(identities: dict, state: dict) -> None:
    expected = {
        name: state[name] for name in ("tenant_id", "subscription_id", "resource_group")
    }
    if identities.get("context") != expected:
        raise ValueError("identity state belongs to a different lab")


class Directory:
    def __init__(self, state_path: Path):
        self.path = private_path(state_path)
        self.state = load_state(self.path)
        self.identity_path = self.path.with_name("identities.json")
        if self.identity_path.exists():
            self.identities = load_state(self.identity_path)
            verify_binding(self.identities, self.state)
        else:
            self.identities = {
                "context": {
                    key: self.state[key]
                    for key in ("tenant_id", "subscription_id", "resource_group")
                },
                "stage": "planned",
            }

    def save(self) -> None:
        save_state(self.identity_path, self.identities)

    def request(self, method: str, path: str, body: dict | None = None) -> Any:
        arguments = [
            "rest", "--method", method, "--url", GRAPH + path,
            "--subscription", self.state["subscription_id"],
        ]
        if body is not None:
            request_path = self.path.with_name("graph-request.json")
            save_state(request_path, body)
            arguments.extend([
                "--headers", "Content-Type=application/json",
                "--body", f"@{request_path}",
            ])
        return az_json(arguments, self.path)

    def ensure_app(self, key: str, manifest: dict) -> dict:
        current = self.identities.get(key, {})
        tags = ["mcp-entra-lab", self.state["suffix"]]
        if current.get("object_id"):
            existing = self.request("get", f"/applications/{current['object_id']}")
            if not set(tags).issubset(existing.get("tags", [])):
                raise ValueError("refusing to modify an application without lab ownership tags")
        else:
            created = self.request("post", "/applications", {**manifest, "tags": tags})
            current.update(object_id=created["id"], client_id=created["appId"])
            self.identities[key] = current
            self.save()
        return current

    def ensure_sp(self, key: str) -> None:
        app = self.identities[key]
        if app.get("service_principal_id"):
            return
        result = self.request(
            "get", f"/servicePrincipals?$filter=appId eq '{app['client_id']}'"
        )["value"]
        if len(result) > 1:
            raise ValueError("ambiguous application service principal")
        sp = result[0] if result else self.request(
            "post", "/servicePrincipals", {"appId": app["client_id"]}
        )
        app["service_principal_id"] = sp["id"]
        self.save()

    def apps(self) -> None:
        arm = self.request(
            "get",
            f"/servicePrincipals?$filter=appId eq '{ARM_APP_ID}'"
            "&$select=id,appId,oauth2PermissionScopes",
        )["value"]
        if len(arm) != 1:
            raise ValueError("Azure Resource Manager service principal was not uniquely found")
        scopes = [
            scope for scope in arm[0]["oauth2PermissionScopes"]
            if scope["value"] == "user_impersonation" and scope["isEnabled"]
        ]
        if len(scopes) != 1:
            raise ValueError("ARM delegated user_impersonation scope was not uniquely found")
        self.identities["arm_resource"] = {
            "service_principal_id": arm[0]["id"], "scope_id": scopes[0]["id"]
        }
        prefix = "mcp-lab-" + self.state["suffix"]
        client = self.ensure_app("public_client", public_client_manifest(prefix + "-client"))
        self.ensure_sp("public_client")
        required_access = []
        for key, scope_name in (
            ("custom_api", "Mcp.Access"), ("azure_api", "Mcp.Tools.ReadWrite")
        ):
            current = self.identities.setdefault(key, {})
            current.setdefault("scope_id", str(uuid.uuid4()))
            current["scope_name"] = scope_name
            self.save()
            manifest = api_manifest(
                prefix + "-" + key.replace("_", "-"),
                current["scope_id"], scope_name, client["client_id"], scopes[0]["id"],
            )
            if key == "azure_api":
                manifest["api"]["preAuthorizedApplications"].append({
                    "appId": VS_CODE_CLIENT_ID,
                    "delegatedPermissionIds": [current["scope_id"]],
                })
            app = self.ensure_app(key, manifest)
            app["identifier_uri"] = "api://" + app["client_id"]
            manifest["identifierUris"] = [app["identifier_uri"]]
            manifest["api"]["knownClientApplications"] = [client["client_id"]]
            self.request("patch", f"/applications/{app['object_id']}", manifest)
            self.ensure_sp(key)
            required_access.append({
                "resourceAppId": app["client_id"],
                "resourceAccess": [{"id": app["scope_id"], "type": "Scope"}],
            })
            self.save()
        self.request(
            "patch", f"/applications/{client['object_id']}",
            {"requiredResourceAccess": required_access},
        )
        custom = self.identities["custom_api"]
        if "client_secret" not in custom:
            credential = self.request(
                "post", f"/applications/{custom['object_id']}/addPassword",
                {"passwordCredential": {
                    "displayName": "short-lived-isolated-lab",
                    "endDateTime": (
                        datetime.now(timezone.utc) + timedelta(days=2)
                    ).isoformat(),
                }},
            )
            custom["client_secret"] = credential["secretText"]
            custom["credential_key_id"] = credential["keyId"]
            custom["credential_expires_at"] = credential["endDateTime"]
        self.identities["stage"] = "apps-configured"
        self.save()
        print("Three lab-owned applications configured. No tenant-wide consent granted.")

    def grant_operator(self) -> None:
        for key in ("custom_api", "azure_api"):
            app = self.identities[key]
            body = delegated_grant(
                app["service_principal_id"],
                self.identities["arm_resource"]["service_principal_id"],
                self.state["operator_id"],
            )
            grants = self.request(
                "get", f"/oauth2PermissionGrants?$filter=clientId eq '{body['clientId']}'"
            )["value"]
            matching = [
                grant for grant in grants
                if all(grant.get(field) == body[field] for field in (
                    "clientId", "resourceId", "consentType", "principalId"
                ))
            ]
            if len(matching) > 1:
                raise ValueError("ambiguous delegated consent records")
            if matching:
                if "user_impersonation" not in matching[0]["scope"].split():
                    raise ValueError("existing consent does not include the required ARM scope")
                app["operator_grant_id"] = matching[0]["id"]
            else:
                created = self.request("post", "/oauth2PermissionGrants", body)
                app["operator_grant_id"] = created["id"]
            self.save()
        self.identities["stage"] = "operator-consented"
        self.save()
        print("ARM delegated consent recorded for this operator only (Principal).")

    def federate_azure_server(self) -> None:
        identity = az_json(
            [
                "identity", "show", "--resource-group", self.state["resource_group"],
                "--name", "id-mcp-app-" + self.state["suffix"],
                "--subscription", self.state["subscription_id"],
            ],
            self.path,
        )
        app = self.identities["azure_api"]
        credential_path = f"/applications/{app['object_id']}/federatedIdentityCredentials"
        body = {
            "name": "lab-managed-identity",
            "audiences": ["api://AzureADTokenExchange"],
            "issuer": f"https://login.microsoftonline.com/{self.state['tenant_id']}/v2.0",
            "subject": identity["principalId"],
            "description": "Authenticate the lab confidential client, not the downstream user.",
        }
        matches = [
            value for value in self.request("get", credential_path)["value"]
            if value["name"] == body["name"]
        ]
        if matches:
            if any(matches[0].get(field) != body[field] for field in (
                "audiences", "issuer", "subject"
            )):
                raise ValueError("existing federation does not match this lab identity")
        else:
            self.request("post", credential_path, body)
        app["managed_identity_client_id"] = identity["clientId"]
        app["federation_configured"] = True
        self.save()
        print("Native Azure MCP confidential-client federation configured.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("command", choices=["apps", "grant-operator", "federate-azure"])
    args = parser.parse_args()
    directory = Directory(args.state)
    if args.command == "apps":
        directory.apps()
    elif args.command == "grant-operator":
        directory.grant_operator()
    else:
        directory.federate_azure_server()


if __name__ == "__main__":
    main()
