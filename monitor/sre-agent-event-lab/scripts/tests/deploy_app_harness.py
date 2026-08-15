"""Harness that runs `azd-deploy-app.sh` as a program.

The script is the `postdeploy` hook of `azd deploy` (and of `azd up`'s
deploy phase), so it is exercised the way azd runs it: as an executable,
from a working directory that is not the lab, with fake `az`/`azd`/`curl`
binaries on PATH and only the environment azd itself would export.

The whole point of this hook is an *ordering* guarantee that reading the
text cannot prove: the Container App's user-assigned identity must hold
`AcrPull` on exactly the lab registry before the first deploy action
(`az acr build`) runs. So the fake `az` here is not a "log and exit 0"
stub -- it models the tenant:

* role assignments are records (`principalId`, `roleDefinitionId`,
  `scope`), and `az role assignment list` applies the real CLI's filters
  to them: the assignee filter, the *exact* `--scope` match (azure-cli's
  `_search_role_assignments` compares `scope.lower()` and only widens to
  parents with `--include-inherited`, which this lab never passes), and
  the `--query` JMESPath `ends_with(roleDefinitionId, '<guid>')`
  projection. An assignment at the resource group, or a different role at
  the registry, is therefore invisible to the hook exactly as it would be
  against a real subscription.
* `az role assignment list` also rejects any flag its real parser does not
  recognise -- `--assignee-principal-type` included, an option that exists
  only on `az role assignment create` (verified against the installed
  Azure CLI 2.89.1: passing it to `list` fails with `ERROR: unrecognized
  arguments`, exit 2) -- so a hook that regresses to sending it fails the
  poll here exactly as it would against a real subscription, instead of
  the fake silently ignoring a flag it does not happen to read.
* `available_after_attempts` models RBAC propagation: the assignment
  exists but the first N `role assignment list` calls do not return it
  yet, which is the delay the whole poll exists for.
* `az containerapp update --image` rolls the app onto a new revision
  name, and `az containerapp revision list` reports that revision's
  health, so the "wait for a new healthy revision" loop is exercised
  rather than mocked away.

The fake `az` is Python, not Bash, because reproducing those filters
faithfully in a Bash stub would be less readable than the behaviour it is
supposed to prove.
"""
import json
import os
import subprocess
from pathlib import Path

from azd_fake import write_azd_stub, write_executable

SCRIPTS_DIR = Path(__file__).parents[1]
LAB_ROOT = Path(__file__).parents[2]
DEPLOY_APP = SCRIPTS_DIR / "azd-deploy-app.sh"

SUBSCRIPTION_ID = "11111111-2222-3333-4444-555555555555"
OTHER_SUBSCRIPTION_ID = "99999999-9999-9999-9999-999999999999"
RESOURCE_GROUP = "rg-sre-lab-hooktest"
ACR_NAME = "acrsrelabtest01"
ACR_LOGIN_SERVER = f"{ACR_NAME}.azurecr.io"
ACR_RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
    f"/providers/Microsoft.ContainerRegistry/registries/{ACR_NAME}"
)
RESOURCE_GROUP_SCOPE = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
)
CONTAINER_APP_NAME = "ca-sre-event-lab-vnet"
CONTAINER_APP_FQDN = "ca-sre-event-lab-vnet.koreacentral.azurecontainerapps.io"
WORKLOAD_PRINCIPAL_ID = "aaaaaaaa-0000-4000-8000-aaaaaaaaaaaa"
WORKLOAD_IDENTITY_RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
    "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-sre-event-lab-test"
)

ACR_PULL_ROLE_DEFINITION_ID = "7f951dda-4ed3-4680-a7ca-43fe172d538d"
ACR_PUSH_ROLE_DEFINITION_ID = "8311e382-0749-4cb8-b61a-304f252e45ec"

INITIAL_REVISION = "ca-sre-event-lab-vnet--placeholder1"
NEW_REVISION = "ca-sre-event-lab-vnet--labimage1"


def role_definition_id(guid, subscription_id=SUBSCRIPTION_ID):
    return (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization"
        f"/roleDefinitions/{guid}"
    )


def assignment(
    principal_id=WORKLOAD_PRINCIPAL_ID,
    role_guid=ACR_PULL_ROLE_DEFINITION_ID,
    scope=ACR_RESOURCE_ID,
    available_after_attempts=0,
):
    """One role assignment as the tenant holds it.

    `available_after_attempts` is how many `az role assignment list` calls
    must happen before this assignment becomes visible -- RBAC propagation
    delay, the reason the hook polls at all.
    """
    return {
        "principalId": principal_id,
        "roleDefinitionId": role_definition_id(role_guid),
        "scope": scope,
        "available_after_attempts": available_after_attempts,
    }


ACR_PULL_GRANTED = [assignment()]


_AZ_STUB = r'''#!/usr/bin/env python3
"""A fake `az` that models the lab's subscription (see deploy_app_harness)."""
import json
import re
import sys
from pathlib import Path

STATE = Path(r"{state_file}")
LOG = Path(r"{log_path}")


def load():
    return json.loads(STATE.read_text())


def save(state):
    STATE.write_text(json.dumps(state))


def flag(argv, name, default=None):
    if name in argv:
        index = argv.index(name)
        if index + 1 < len(argv):
            return argv[index + 1]
    return default


def fail(message):
    sys.stderr.write(message + "\n")
    raise SystemExit(1)


def main():
    argv = sys.argv[1:]
    with LOG.open("a") as log:
        log.write(" ".join(argv) + "\n")
    state = load()
    joined = " ".join(argv)

    if argv[:2] == ["account", "show"]:
        if state.get("signed_out"):
            fail("ERROR: Please run 'az login' to setup account.")
        print(state["active_subscription"])
        return

    if argv[:2] == ["acr", "show"]:
        query = flag(argv, "--query")
        if query == "id":
            print(state["acr_resource_id"])
            return
        if query == "loginServer":
            print(state["acr_login_server"])
            return
        fail(f"ERROR: fake az: unsupported acr show query: {{query}}")

    if argv[:2] == ["acr", "build"]:
        if state.get("acr_build_fails"):
            fail("ERROR: failed to build image")
        state["acr_build_count"] = state.get("acr_build_count", 0) + 1
        save(state)
        print("Run ID: ca1 was successful after 30s")
        return

    if argv[:3] == ["role", "assignment", "list"]:
        # Reject anything the real `az role assignment list` parser would
        # reject (verified against the installed Azure CLI 2.89.1), so a
        # hook that regresses to an unsupported flag -- `--assignee-
        # principal-type` included, which exists only on `role assignment
        # create` -- fails here exactly as it would against a real
        # subscription, instead of silently succeeding against a fake that
        # only reads the flags it happens to recognise.
        value_flags = {{
            "--assignee", "--assignee-object-id", "--resource-group", "-g",
            "--role", "--scope", "--subscription", "--query", "--output", "-o",
            "--fill-principal-name", "--fill-role-definition-name",
        }}
        flag_only_flags = {{
            "--all", "--include-groups", "--include-inherited",
            "--debug", "--only-show-errors", "--verbose",
        }}
        rest = argv[3:]
        unrecognized = []
        index = 0
        while index < len(rest):
            token = rest[index]
            if token in value_flags:
                index += 2
                continue
            if token in flag_only_flags:
                index += 1
                continue
            unrecognized.append(token)
            index += 1
        if unrecognized:
            fail(f"ERROR: unrecognized arguments: {{' '.join(unrecognized)}}")

        state["role_list_attempts"] = state.get("role_list_attempts", 0) + 1
        attempt = state["role_list_attempts"]
        save(state)
        assignee = flag(argv, "--assignee-object-id")
        scope = flag(argv, "--scope")
        query = flag(argv, "--query", "")
        wanted = re.search(r"ends_with\(\s*roleDefinitionId\s*,\s*'([^']+)'", query)
        if not wanted:
            fail(f"ERROR: fake az: unsupported role assignment list query: {{query}}")
        wanted_role = wanted.group(1)
        if "--include-inherited" in argv:
            fail("ERROR: fake az: the lab must never widen the scope with --include-inherited")
        for record in state["assignments"]:
            if attempt <= record.get("available_after_attempts", 0):
                continue
            if assignee is not None and record["principalId"] != assignee:
                continue
            # azure-cli's own exact-scope filter (case-insensitive) when
            # --include-inherited is not passed.
            if scope is not None and record["scope"].lower() != scope.lower():
                continue
            if not record["roleDefinitionId"].endswith(wanted_role):
                continue
            print(record["scope"])
        return

    if argv[:2] == ["containerapp", "show"]:
        query = flag(argv, "--query")
        if query == "properties.latestRevisionName":
            print(state["latest_revision"])
            return
        fail(f"ERROR: fake az: unsupported containerapp show query: {{query}}")

    if argv[:3] == ["containerapp", "revision", "list"]:
        query = flag(argv, "--query", "")
        revision = re.search(r"name=='([^']+)'", query)
        revision_name = revision.group(1) if revision else ""
        state["revision_polls"] = state.get("revision_polls", 0) + 1
        polls = state["revision_polls"]
        save(state)
        healthy_after = state.get("revision_healthy_after_polls", 0)
        if revision_name != state["latest_revision"] or polls <= healthy_after:
            print("Unhealthy" if "healthState" in query else "false")
            return
        print("Healthy" if "healthState" in query else "true")
        return

    if argv[:3] == ["containerapp", "ingress", "update"]:
        state["target_port"] = flag(argv, "--target-port")
        save(state)
        return

    if argv[:3] == ["containerapp", "registry", "set"]:
        state["registry_identity"] = flag(argv, "--identity")
        state["registry_server"] = flag(argv, "--server")
        save(state)
        return

    if argv[:2] == ["containerapp", "update"]:
        if state.get("containerapp_update_fails"):
            fail("ERROR: failed to update the container app")
        state["deployed_image"] = flag(argv, "--image")
        state["latest_revision"] = state["new_revision"]
        save(state)
        return

    fail(f"ERROR: fake az: unsupported invocation: {{joined}}")


main()
'''


_CURL_STUB = r'''#!/usr/bin/env python3
import json
import sys
from pathlib import Path

STATE = Path(r"{state_file}")
LOG = Path(r"{log_path}")

argv = sys.argv[1:]
with LOG.open("a") as log:
    log.write(" ".join(argv) + "\n")

state = json.loads(STATE.read_text())
url = argv[-1]
state["health_probes"] = state.get("health_probes", 0) + 1
probes = state["health_probes"]
STATE.write_text(json.dumps(state))

if state.get("health_never_ready"):
    sys.stderr.write("curl: (22) The requested URL returned error: 404\n")
    raise SystemExit(22)
if state.get("deployed_image") is None:
    sys.stderr.write("curl: (7) Failed to connect\n")
    raise SystemExit(7)
if probes <= state.get("health_ready_after_probes", 0):
    sys.stderr.write("curl: (22) The requested URL returned error: 503\n")
    raise SystemExit(22)
print(f"ok {{url}}")
'''


class DeployRun:
    def __init__(self, result, az_log, azd_log, curl_log, state_file):
        self.result = result
        self._az_log = az_log
        self._azd_log = azd_log
        self._curl_log = curl_log
        self._state_file = state_file

    @property
    def returncode(self):
        return self.result.returncode

    @property
    def stdout(self):
        return self.result.stdout

    @property
    def stderr(self):
        return self.result.stderr

    @property
    def az_calls(self):
        return self._az_log.read_text() if self._az_log.exists() else ""

    @property
    def az_call_lines(self):
        return [line for line in self.az_calls.splitlines() if line.strip()]

    @property
    def azd_calls(self):
        return self._azd_log.read_text() if self._azd_log.exists() else ""

    @property
    def curl_calls(self):
        return self._curl_log.read_text() if self._curl_log.exists() else ""

    @property
    def state(self):
        return json.loads(self._state_file.read_text())

    def first_index(self, needle):
        """Index of the first az call containing `needle`, or None."""
        for index, line in enumerate(self.az_call_lines):
            if needle in line:
                return index
        return None


def run_deploy_app(
    tmp_path,
    assignments=None,
    active_subscription_id=None,
    signed_out=False,
    acr_build_fails=False,
    containerapp_update_fails=False,
    revision_healthy_after_polls=0,
    health_ready_after_probes=0,
    health_never_ready=False,
    env=None,
    drop_env=(),
    azd_values=None,
    script=DEPLOY_APP,
):
    """Run `azd-deploy-app.sh` against a staged fake subscription.

    Every timeout the script owns is shortened through its own documented
    environment overrides so a five-minute production budget does not become
    a five-minute test.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    state_file = tmp_path / "tenant.json"
    state_file.write_text(
        json.dumps(
            {
                "active_subscription": active_subscription_id or SUBSCRIPTION_ID,
                "signed_out": signed_out,
                "acr_resource_id": ACR_RESOURCE_ID,
                "acr_login_server": ACR_LOGIN_SERVER,
                "assignments": list(
                    ACR_PULL_GRANTED if assignments is None else assignments
                ),
                "latest_revision": INITIAL_REVISION,
                "new_revision": NEW_REVISION,
                "revision_healthy_after_polls": revision_healthy_after_polls,
                "health_ready_after_probes": health_ready_after_probes,
                "health_never_ready": health_never_ready,
                "acr_build_fails": acr_build_fails,
                "containerapp_update_fails": containerapp_update_fails,
                "deployed_image": None,
            }
        )
    )

    az_log = tmp_path / "az-calls.log"
    azd_log = tmp_path / "azd-calls.log"
    curl_log = tmp_path / "curl-calls.log"
    write_executable(
        bin_dir / "az", _AZ_STUB.format(state_file=state_file, log_path=az_log)
    )
    write_executable(
        bin_dir / "curl", _CURL_STUB.format(state_file=state_file, log_path=curl_log)
    )
    write_azd_stub(
        bin_dir,
        {"AZURE_SUBSCRIPTION_ID": SUBSCRIPTION_ID}
        if azd_values is None
        else azd_values,
        "azd_1_29",
        azd_log,
    )

    workdir = tmp_path / "elsewhere"
    workdir.mkdir(parents=True, exist_ok=True)

    process_env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": os.environ.get("HOME", str(tmp_path)),
        "AZURE_SUBSCRIPTION_ID": SUBSCRIPTION_ID,
        "AZURE_RESOURCE_GROUP": RESOURCE_GROUP,
        "AZURE_ACR_NAME": ACR_NAME,
        "AZURE_CONTAINER_APP_NAME": CONTAINER_APP_NAME,
        "AZURE_CONTAINER_APP_FQDN": CONTAINER_APP_FQDN,
        "AZURE_CONTAINER_APP_PRINCIPAL_ID": WORKLOAD_PRINCIPAL_ID,
        "AZURE_WORKLOAD_IDENTITY_RESOURCE_ID": WORKLOAD_IDENTITY_RESOURCE_ID,
        "SRE_ACR_PULL_TIMEOUT_SECONDS": "2",
        "SRE_ACR_PULL_POLL_INTERVAL_SECONDS": "0.2",
        "SRE_REVISION_READY_TIMEOUT_SECONDS": "2",
        "SRE_HEALTH_TIMEOUT_SECONDS": "2",
        "SRE_DEPLOY_POLL_INTERVAL_SECONDS": "0.2",
    }
    for name in drop_env:
        process_env.pop(name, None)
    process_env.update(env or {})

    result = subprocess.run(
        [str(script)],
        capture_output=True,
        text=True,
        env=process_env,
        cwd=str(workdir),
    )
    return DeployRun(result, az_log, azd_log, curl_log, state_file)
