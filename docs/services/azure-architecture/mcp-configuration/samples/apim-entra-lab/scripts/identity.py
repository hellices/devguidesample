"""Manage only the Entra objects belonging to the selected azd environment."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[1]
CLI_CLIENT = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
VSCODE_CLIENT = "aebc6443-996d-45c2-90f0-388ff96faa56"
ARM_APP = "797f4846-ba00-4fd7-ba43-dac1f8f63013"
GRAPH = "https://graph.microsoft.com/v1.0"


def command(arguments):
    result = subprocess.run(arguments, cwd=ROOT, text=True, capture_output=True, timeout=180)
    if result.returncode:
        # CLI errors can contain tenant/user IDs; keep the full diagnostic local.
        path = ROOT / ".azure" / "identity-error.txt"
        private_json(path, {"command": arguments[:3], "stderr": result.stderr})
        raise RuntimeError("Identity operation failed; see .azure/identity-error.txt")
    return json.loads(result.stdout) if result.stdout.strip() else None


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        temporary = Path(handle.name)
    os.replace(temporary, path)


class Identity:
    def __init__(self):
        self.env = command(["azd", "env", "get-values", "--output", "json"])
        name = self.env.get("AZURE_ENV_NAME", "")
        if not re.fullmatch(r"[a-z0-9]{6,10}", name):
            raise ValueError("Use an azd environment name of 6-10 lowercase letters/digits.")
        self.folder = ROOT / ".azure" / name
        self.path = self.folder / "identity.json"
        account = command([
            "az", "account", "show", "--subscription",
            self.env["AZURE_SUBSCRIPTION_ID"], "-o", "json",
        ])
        if account["user"]["type"] != "user":
            raise ValueError("Use an Azure CLI user login for delegated OBO.")
        binding = {"environment": name, "subscription": account["id"], "tenant": account["tenantId"]}
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {"context": binding}
        if self.state["context"] != binding:
            raise ValueError("The selected azd environment does not match its Entra state.")
        self.name = name
        self.tenant = account["tenantId"]
        self.subscription = account["id"]
        self.tags = ["mcp-entra-walkthrough", name]

    def save(self):
        private_json(self.path, self.state)

    def graph(self, method, path, body=None):
        arguments = [
            "az", "rest", "--method", method, "--url", GRAPH + path,
            "--subscription", self.subscription, "-o", "json",
        ]
        if body is not None:
            file = self.folder / "graph-request.json"
            private_json(file, body)
            arguments.extend(["--headers", "Content-Type=application/json", "--body", "@" + str(file)])
        return command(arguments)

    def app(self, key, manifest):
        if key not in self.state:
            created = self.graph("post", "/applications", {**manifest, "tags": self.tags})
            self.state[key] = {"id": created["id"], "appId": created["appId"]}
            self.save()
        record = self.state[key]
        app = self.graph("get", "/applications/" + record["id"])
        if app["appId"] != record["appId"] or not set(self.tags).issubset(app.get("tags", [])):
            raise ValueError("Application ownership does not match this azd environment.")
        if "spId" not in record:
            found = self.graph("get", "/servicePrincipals?$filter=appId eq '" + record["appId"] + "'")["value"]
            if len(found) > 1:
                raise ValueError("Service principal lookup is ambiguous.")
            principal = found[0] if found else self.graph("post", "/servicePrincipals", {"appId": record["appId"]})
            record["spId"] = principal["id"]
            self.save()
        return record

    def export(self, values):
        # Pass secrets through a private file, not command-line arguments or stdout.
        path = self.folder / "identity.env"
        text = "".join(key + "=" + json.dumps(value) + "\n" for key, value in values.items())
        with tempfile.NamedTemporaryFile(mode="w", dir=self.folder, delete=False) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        os.replace(temporary, path)
        command(["azd", "env", "set", "--file", str(path)])
        (self.folder / ".env").chmod(0o600)
        path.unlink()

    def prepare(self):
        exists = command([
            "az", "group", "exists", "--name", "rg-" + self.name,
            "--subscription", self.subscription, "-o", "json",
        ])
        if exists:
            group = command([
                "az", "group", "show", "--name", "rg-" + self.name,
                "--subscription", self.subscription, "-o", "json",
            ])
            if (
                not self.path.exists()
                or group.get("tags", {}).get("azd-env-name") != self.name
                or group.get("tags", {}).get("purpose") != "mcp-entra-walkthrough"
            ):
                raise ValueError("Choose a new environment; an existing RG is not owned by this project.")
        operator = self.graph("get", "/me?$select=id")["id"]
        if self.state.get("operatorId", operator) != operator:
            raise ValueError("Use the original operator for this environment's delegated consent.")
        self.state["operatorId"] = operator
        self.save()
        arm = self.graph("get", "/servicePrincipals?$filter=appId eq '" + ARM_APP + "'")["value"]
        if len(arm) != 1:
            raise ValueError("ARM service principal was not uniquely found.")
        scopes = [s for s in arm[0]["oauth2PermissionScopes"] if s["value"] == "user_impersonation" and s["isEnabled"]]
        if len(scopes) != 1:
            raise ValueError("ARM delegated scope was not uniquely found.")
        public = self.app("public", {
            "displayName": self.name + "-client", "signInAudience": "AzureADMyOrg",
            "publicClient": {"redirectUris": ["http://localhost"]},
            "isFallbackPublicClient": True,
        })
        accesses = []
        for key, scope in (("custom", "Mcp.Access"), ("azure", "Mcp.Tools.ReadWrite")):
            record = self.app(key, {"displayName": self.name + "-" + key, "signInAudience": "AzureADMyOrg"})
            record.setdefault("scopeId", str(uuid.uuid4()))
            record["scope"] = scope
            self.save()
            clients = [CLI_CLIENT, public["appId"]] + ([VSCODE_CLIENT] if key == "azure" else [])
            manifest = {
                "identifierUris": ["api://" + record["appId"]],
                "api": {
                    "requestedAccessTokenVersion": 2,
                    "oauth2PermissionScopes": [{
                        "id": record["scopeId"], "value": scope, "type": "User", "isEnabled": True,
                        "adminConsentDisplayName": "Access MCP walkthrough",
                        "adminConsentDescription": "Use this MCP API as the signed-in user.",
                        "userConsentDisplayName": "Access MCP walkthrough",
                        "userConsentDescription": "Use this MCP API with your own permissions.",
                    }],
                },
                "requiredResourceAccess": [{
                    "resourceAppId": ARM_APP,
                    "resourceAccess": [{"id": scopes[0]["id"], "type": "Scope"}],
                }],
            }
            self.graph("patch", "/applications/" + record["id"], manifest)
            manifest["api"]["preAuthorizedApplications"] = [
                {"appId": client, "delegatedPermissionIds": [record["scopeId"]]}
                for client in clients
            ]
            self.graph("patch", "/applications/" + record["id"], manifest)
            grants = self.graph("get", "/oauth2PermissionGrants?$filter=clientId eq '" + record["spId"] + "'")["value"]
            matches = [g for g in grants if g["resourceId"] == arm[0]["id"] and g["consentType"] == "Principal" and g.get("principalId") == operator]
            if not matches:
                self.graph("post", "/oauth2PermissionGrants", {
                    "clientId": record["spId"], "resourceId": arm[0]["id"],
                    "consentType": "Principal", "principalId": operator, "scope": "user_impersonation",
                })
            elif len(matches) != 1 or "user_impersonation" not in matches[0]["scope"].split():
                raise ValueError("The recorded user's downstream consent is inconsistent.")
            accesses.append({"resourceAppId": record["appId"], "resourceAccess": [{"id": record["scopeId"], "type": "Scope"}]})
        self.graph("patch", "/applications/" + public["id"], {"requiredResourceAccess": accesses})
        custom = self.state["custom"]
        if "secret" not in custom:
            expiry = datetime.now(timezone.utc) + timedelta(days=2)
            secret = self.graph("post", "/applications/" + custom["id"] + "/addPassword", {
                "passwordCredential": {"displayName": "walkthrough-only", "endDateTime": expiry.isoformat()}
            })
            custom["secret"] = secret["secretText"]
            custom["secretExpiresAt"] = secret["endDateTime"]
            self.save()
        if datetime.fromisoformat(custom["secretExpiresAt"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            raise ValueError("The walkthrough credential expired; rotate it explicitly before redeploying.")
        self.export({
            "MCP_OPERATOR_ID": operator, "AZURE_TENANT_ID": self.tenant,
            "MCP_CUSTOM_API_CLIENT_ID": custom["appId"], "MCP_CUSTOM_API_CLIENT_SECRET": custom["secret"],
            "MCP_AZURE_API_CLIENT_ID": self.state["azure"]["appId"],
            "MCP_PUBLIC_CLIENT_ID": public["appId"],
            "MCP_EXPIRES_ON": self.env.get("MCP_EXPIRES_ON") or (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat(),
        })
        print("Entra: three project apps and current-user delegated consent configured.")

    def federate(self):
        app = self.state["azure"]
        path = "/applications/" + app["id"] + "/federatedIdentityCredentials"
        body = {
            "name": "container-apps", "audiences": ["api://AzureADTokenExchange"],
            "issuer": "https://login.microsoftonline.com/" + self.tenant + "/v2.0",
            "subject": self.env["MCP_APP_IDENTITY_OBJECT_ID"],
        }
        existing = [x for x in self.graph("get", path)["value"] if x["name"] == body["name"]]
        if not existing:
            self.graph("post", path, body)
        elif len(existing) != 1 or any(existing[0][k] != body[k] for k in ("issuer", "subject", "audiences")):
            raise ValueError("The native MCP federation belongs to a different identity.")
        print("Entra: native Azure MCP confidential-client federation configured.")

    def remove(self, confirm):
        if confirm != self.name:
            raise ValueError("Confirm directory cleanup with the exact azd environment name.")
        for key in ("public", "custom", "azure"):
            record = self.state.get(key)
            if not record or record.get("deleted"):
                continue
            apps = self.graph("get", "/applications?$filter=appId eq '" + record["appId"] + "'")["value"]
            if apps and (len(apps) != 1 or apps[0]["id"] != record["id"] or not set(self.tags).issubset(apps[0].get("tags", []))):
                raise ValueError("Application ownership changed; cleanup refused.")
            principals = self.graph("get", "/servicePrincipals?$filter=appId eq '" + record["appId"] + "'")["value"]
            if principals:
                if len(principals) != 1 or principals[0]["id"] != record["spId"]:
                    raise ValueError("Service principal ownership changed; cleanup refused.")
                self.graph("delete", "/servicePrincipals/" + record["spId"])
            if apps:
                self.graph("delete", "/applications/" + record["id"])
            record["deleted"] = True
            record.pop("secret", None)
            self.save()
        print("Entra: recorded project apps and service principals removed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "federate", "remove"])
    parser.add_argument("--confirm")
    args = parser.parse_args()
    identity = Identity()
    if args.action == "prepare":
        identity.prepare()
    elif args.action == "federate":
        identity.federate()
    else:
        identity.remove(args.confirm)
