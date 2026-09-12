"""Preview cleanup by default. Delete only this lab after explicit confirmation."""

from __future__ import annotations

import argparse
from pathlib import Path

from cloud_lab import assert_owned_group, az_json, private_path
from entra_setup import Directory


APPLICATIONS = ("public_client", "custom_api", "azure_api")


def owned_application(record: dict, application: dict, suffix: str) -> bool:
    return (
        record["client_id"] == application.get("appId")
        and {"mcp-entra-lab", suffix}.issubset(application.get("tags", []))
    )


def confirm_deletion(suffix: str, confirmation: str) -> None:
    if confirmation != suffix:
        raise ValueError("confirmation must exactly match this lab's private-state suffix")


def run(state_path: Path, confirmation: str | None) -> None:
    directory = Directory(state_path)
    state = directory.state
    if confirmation is not None:
        confirm_deletion(state["suffix"], confirmation)
    group_exists = assert_owned_group(state, state_path)
    planned = []
    for name in APPLICATIONS:
        record = directory.identities.get(name)
        if record is None or record.get("cleanup_app_deleted"):
            continue
        application = directory.request("get", f"/applications/{record['object_id']}")
        if not owned_application(record, application, state["suffix"]):
            raise ValueError("an application is not owned by this lab; cleanup refused")
        if not record.get("cleanup_sp_deleted"):
            principal = directory.request(
                "get", f"/servicePrincipals/{record['service_principal_id']}"
            )
            if principal["appId"] != record["client_id"]:
                raise ValueError("service principal does not match its recorded lab application")
        planned.append(name)
    print(f"Owned cleanup scope: {len(planned)} applications; lab RG present: {group_exists}.")
    if confirmation is None:
        print("Preview only. No resources or identities were deleted.")
        return

    for name in planned:
        record = directory.identities[name]
        if not record.get("cleanup_sp_deleted"):
            directory.request("delete", f"/servicePrincipals/{record['service_principal_id']}")
            record["cleanup_sp_deleted"] = True
            directory.save()
        directory.request("delete", f"/applications/{record['object_id']}")
        record["cleanup_app_deleted"] = True
        directory.save()
    if group_exists:
        az_json([
            "group", "delete", "--name", state["resource_group"],
            "--subscription", state["subscription_id"], "--yes",
        ], state_path, timeout=7200)
    for suffix in ("-nodes", "-aca-managed"):
        exists = az_json([
            "group", "exists", "--name", state["resource_group"] + suffix,
            "--subscription", state["subscription_id"],
        ], state_path)
        if exists:
            raise RuntimeError(
                "A provider-managed lab group still exists. "
                "Inspect its deletion status; do not delete unrelated groups."
            )
    directory.identities["cleanup_complete"] = True
    directory.save()
    print("Recorded lab applications, service principals and Azure groups have been removed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--confirm-delete")
    args = parser.parse_args()
    run(private_path(args.state), args.confirm_delete)


if __name__ == "__main__":
    main()
