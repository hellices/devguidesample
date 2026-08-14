"""Behaviour tests for `azd-deploy-app.sh`, the lab's `postdeploy` hook.

Why this hook exists at all, and why these tests are about *ordering*:

The lab runs on Container Apps pulling from ACR with a user-assigned
managed identity. Bicep creates the registry, the identity, the `AcrPull`
role assignment, and a Container App running a *public placeholder* image
-- it cannot deploy the lab image, because that image does not exist until
something builds it, and the identity's `AcrPull` grant is not usable the
instant the deployment returns. That makes the deployment inherently
two-phase, and the phases must not be collapsed:

    azd provision  -> infrastructure + placeholder image, nothing else
    azd deploy     -> wait for AcrPull, build in ACR, move the app onto it

The previous design did the second phase inside `postprovision`, which
starts the ACR build immediately after the ARM deployment returns -- no
role check at all. These tests pin the corrected contract: the hook must
observe the *exact* `AcrPull` assignment (this principal, this role
definition, this registry scope) before its first deploy action, and must
never build or update anything if that assignment never appears.

`azd deploy` and `azd up` both run this hook even though the project
declares no services -- verified against azd 1.29.0 on 2026-08-14, both by
running `azd deploy --all --no-prompt` / `azd deploy --no-prompt` against a
service-less project (project `predeploy`/`postdeploy` hooks ran; a
non-zero hook exit failed the command with
`ERROR: failed running post hooks: 'postdeploy' hook failed with exit
code: '3'`) and in azd's own source: `cli/azd/internal/cmd/up_graph.go`
builds `cmdhook-predeploy`/`cmdhook-postdeploy` steps unconditionally and
explicitly keeps them for "Zero-service projects", calling the same
`runProjectCommandHook` (`cli/azd/internal/cmd/project_hooks.go`) the
cobra hooks middleware uses for stand-alone `azd deploy`.
"""
import re

import pytest

from deploy_app_harness import (
    ACR_LOGIN_SERVER,
    ACR_NAME,
    ACR_PULL_ROLE_DEFINITION_ID,
    ACR_PUSH_ROLE_DEFINITION_ID,
    ACR_RESOURCE_ID,
    CONTAINER_APP_FQDN,
    DEPLOY_APP,
    LAB_ROOT,
    OTHER_SUBSCRIPTION_ID,
    RESOURCE_GROUP_SCOPE,
    WORKLOAD_IDENTITY_RESOURCE_ID,
    assignment,
    run_deploy_app,
)

SUBSCRIPTION_PIN = '--subscription "${AZURE_SUBSCRIPTION_ID}"'
ACTIVE_ACCOUNT_PROBE = "az account show --query id"

# Every call that changes the deployed application. None of them may run
# before the AcrPull poll succeeds.
DEPLOY_ACTIONS = (
    "acr build",
    "containerapp registry set",
    "containerapp ingress update",
    "containerapp update",
)


def _az_invocations(script_text):
    """Every `az ...` command in a script, with line continuations joined."""
    joined = re.sub(r"\\\n\s*", " ", script_text)
    commands = []
    for line in joined.splitlines():
        if line.strip().startswith("#"):
            continue
        for segment in re.split(r"\$\(|\|\||&&|\||;|`", line):
            stripped = re.sub(
                r"^(?:if\s+|until\s+|while\s+|then\s+|else\s+|do\s+|!\s*)+",
                "",
                segment.strip(),
            )
            if re.match(r"^az\s", stripped):
                commands.append(re.sub(r"\s+", " ", stripped).strip())
    return commands


# --- The script exists and is wired as a program ---------------------------


def test_deploy_hook_script_exists_and_is_executable():
    assert DEPLOY_APP.is_file(), (
        "the deploy phase needs its own hook script; the two-phase "
        "Container Apps + ACR managed-identity flow cannot live in postprovision"
    )
    assert DEPLOY_APP.stat().st_mode & 0o111, "azd runs the hook as a program"


# --- Static contract -------------------------------------------------------


def test_every_azure_cli_call_is_pinned_to_the_target_subscription():
    for command in _az_invocations(DEPLOY_APP.read_text()):
        if command.startswith(ACTIVE_ACCOUNT_PROBE):
            continue
        assert SUBSCRIPTION_PIN in command, (
            f"azd-deploy-app.sh runs an unpinned Azure CLI command: {command}"
        )


def test_requires_every_provision_output_it_consumes():
    text = DEPLOY_APP.read_text()

    for value in (
        "AZURE_SUBSCRIPTION_ID:?",
        "AZURE_RESOURCE_GROUP:?",
        "AZURE_ACR_NAME:?",
        "AZURE_CONTAINER_APP_NAME:?",
        "AZURE_CONTAINER_APP_FQDN:?",
        "AZURE_CONTAINER_APP_PRINCIPAL_ID:?",
        "AZURE_WORKLOAD_IDENTITY_RESOURCE_ID:?",
    ):
        assert value in text, f"the hook must fail fast without {value}"


def test_polls_the_exact_acr_pull_role_before_any_deploy_action():
    """The whole point of the gate, asserted on the source as well as on
    behaviour: the role poll has to come first, textually and in time."""
    text = DEPLOY_APP.read_text()

    assert ACR_PULL_ROLE_DEFINITION_ID in text, (
        "the poll must match AcrPull by role definition ID, not by a "
        "display name that any custom role could also carry"
    )
    poll_at = text.index("az role assignment list")
    for action in DEPLOY_ACTIONS:
        action_at = text.index(f"az {action}")
        assert poll_at < action_at, (
            f"az {action} appears before the AcrPull poll in the script"
        )


def test_role_poll_budget_is_five_minutes_by_default():
    text = DEPLOY_APP.read_text()

    assert re.search(
        r"SRE_ACR_PULL_TIMEOUT_SECONDS:-300", text
    ), "the documented AcrPull propagation budget is 5 minutes"
    assert re.search(
        r"SRE_ACR_PULL_POLL_INTERVAL_SECONDS:-10", text
    ), "the poll interval must default to 10s, not to a busy loop"


def test_never_builds_the_image_locally():
    """The lab has no local Docker requirement: the image is built in ACR."""
    text = DEPLOY_APP.read_text()

    assert "az acr build" in text
    assert not re.search(r"^\s*docker\s", text, flags=re.MULTILINE)
    assert "docker build" not in text


# --- Behaviour: the gate ---------------------------------------------------


def test_waits_for_acr_pull_to_propagate_before_building(tmp_path):
    """The assignment exists but is not visible yet on the first two polls
    -- exactly the propagation window the gate exists for. The hook must
    keep polling and only then start the build."""
    run = run_deploy_app(
        tmp_path,
        assignments=[assignment(available_after_attempts=2)],
    )

    assert run.returncode == 0, run.stdout + run.stderr
    poll_lines = [
        line for line in run.az_call_lines if line.startswith("role assignment list")
    ]
    assert len(poll_lines) == 3, (
        f"expected three polls before the grant became visible: {poll_lines!r}"
    )
    build_at = run.first_index("acr build")
    assert build_at is not None, "the hook never built the image"
    assert build_at > run.az_call_lines.index(poll_lines[-1]), (
        "the build must start only after the poll that saw the grant"
    )


def test_makes_no_deploy_call_at_all_until_the_grant_is_visible(tmp_path):
    run = run_deploy_app(
        tmp_path,
        assignments=[assignment(available_after_attempts=2)],
    )

    assert run.returncode == 0, run.stdout + run.stderr
    first_grant_seen = max(
        index
        for index, line in enumerate(run.az_call_lines)
        if line.startswith("role assignment list")
    )
    for action in DEPLOY_ACTIONS:
        action_at = run.first_index(action)
        assert action_at is not None, f"the hook never ran az {action}"
        assert action_at > first_grant_seen, (
            f"az {action} ran before the AcrPull grant was observed: "
            f"{run.az_call_lines!r}"
        )


def test_stops_without_building_when_acr_pull_never_appears(tmp_path):
    run = run_deploy_app(tmp_path, assignments=[])

    assert run.returncode != 0
    assert "AcrPull" in run.stderr
    assert ACR_RESOURCE_ID in run.stderr, (
        "the failure must name the exact scope that was polled"
    )
    assert run.first_index("acr build") is None, (
        f"the hook built the image without the grant: {run.az_call_lines!r}"
    )
    assert run.first_index("containerapp update") is None
    assert run.first_index("containerapp ingress update") is None
    assert "SRE_CONTAINER_IMAGE" not in run.azd_calls


def test_ignores_an_acr_pull_grant_at_a_wider_scope(tmp_path):
    """A resource-group-scoped AcrPull would let the app pull, but it is not
    the assignment this lab creates; accepting it would make the gate pass
    on an unrelated grant while the lab's own assignment is still
    propagating."""
    run = run_deploy_app(
        tmp_path,
        assignments=[assignment(scope=RESOURCE_GROUP_SCOPE)],
    )

    assert run.returncode != 0
    assert run.first_index("acr build") is None


def test_ignores_a_different_role_at_the_registry_scope(tmp_path):
    run = run_deploy_app(
        tmp_path,
        assignments=[assignment(role_guid=ACR_PUSH_ROLE_DEFINITION_ID)],
    )

    assert run.returncode != 0
    assert run.first_index("acr build") is None


def test_ignores_an_acr_pull_grant_for_a_different_principal(tmp_path):
    run = run_deploy_app(
        tmp_path,
        assignments=[assignment(principal_id="ffffffff-0000-4000-8000-ffffffffffff")],
    )

    assert run.returncode != 0
    assert run.first_index("acr build") is None


def test_accepts_the_grant_when_arm_returns_a_differently_cased_scope(tmp_path):
    """ARM echoes `resourcegroups` or `resourceGroups` depending on how the
    assignment was created. Resource IDs are case-insensitive, so a casing
    difference must not stall the deployment for the full five minutes."""
    run = run_deploy_app(
        tmp_path,
        assignments=[
            assignment(scope=ACR_RESOURCE_ID.replace("resourceGroups", "resourcegroups"))
        ],
    )

    assert run.returncode == 0, run.stdout + run.stderr
    assert run.first_index("acr build") is not None


# --- Behaviour: the deployment itself --------------------------------------


def test_builds_in_acr_and_moves_the_app_onto_the_built_image(tmp_path):
    run = run_deploy_app(tmp_path)

    assert run.returncode == 0, run.stdout + run.stderr
    build_line = run.az_call_lines[run.first_index("acr build")]
    assert f"--registry {ACR_NAME}" in build_line
    assert "sre-event-lab:" in build_line
    assert str(LAB_ROOT / "app") in build_line, (
        "the ACR build context must be the lab's app directory"
    )

    deployed_image = run.state["deployed_image"]
    assert deployed_image.startswith(f"{ACR_LOGIN_SERVER}/sre-event-lab:")


def test_configures_the_registry_with_the_workload_identity(tmp_path):
    run = run_deploy_app(tmp_path)

    assert run.returncode == 0, run.stdout + run.stderr
    assert run.state["registry_identity"] == WORKLOAD_IDENTITY_RESOURCE_ID
    assert run.state["registry_server"] == ACR_LOGIN_SERVER


def test_moves_ingress_to_the_app_port_before_the_image_update(tmp_path):
    """The placeholder serves 80 and the lab image serves 8000."""
    run = run_deploy_app(tmp_path)

    assert run.returncode == 0, run.stdout + run.stderr
    assert run.state["target_port"] == "8000"
    assert run.first_index("containerapp ingress update") < run.first_index(
        "containerapp update --"
    )


def test_waits_for_a_new_healthy_revision_and_a_healthy_endpoint(tmp_path):
    run = run_deploy_app(
        tmp_path, revision_healthy_after_polls=2, health_ready_after_probes=2
    )

    assert run.returncode == 0, run.stdout + run.stderr
    assert run.state["revision_polls"] > 2
    assert run.state["health_probes"] > 2
    assert f"https://{CONTAINER_APP_FQDN}/healthz" in run.curl_calls


def test_records_the_built_image_in_the_azd_environment(tmp_path):
    run = run_deploy_app(tmp_path)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "env set SRE_IMAGE_TAG run-" in run.azd_calls
    assert f"env set SRE_CONTAINER_IMAGE {ACR_LOGIN_SERVER}/sre-event-lab:" in run.azd_calls
    assert f"cwd={LAB_ROOT}" in run.azd_calls, (
        "the hook must pin `azd env set` to the lab project, not to the "
        "working directory azd happens to run it from"
    )


def test_does_not_record_an_image_that_never_became_healthy(tmp_path):
    run = run_deploy_app(tmp_path, health_never_ready=True)

    assert run.returncode != 0
    assert "SRE_CONTAINER_IMAGE" not in run.azd_calls, (
        "persisting an unhealthy image would make the next `azd provision` "
        "deploy it again as if it were known good"
    )


# --- Behaviour: preconditions ----------------------------------------------


def test_reports_a_clear_error_when_the_azure_cli_is_not_logged_in(tmp_path):
    run = run_deploy_app(tmp_path, signed_out=True)

    assert run.returncode != 0
    assert "az login" in run.stderr
    assert "Please run 'az login' to setup account." not in run.stderr
    assert run.az_calls.strip() == "account show --query id -o tsv", (
        f"the hook must stop at the failed login check: {run.az_calls!r}"
    )


def test_reports_the_mismatch_when_the_cli_targets_another_subscription(tmp_path):
    run = run_deploy_app(tmp_path, active_subscription_id=OTHER_SUBSCRIPTION_ID)

    assert run.returncode == 0, run.stdout + run.stderr
    assert OTHER_SUBSCRIPTION_ID in run.stderr


@pytest.mark.parametrize(
    "missing",
    [
        "AZURE_RESOURCE_GROUP",
        "AZURE_ACR_NAME",
        "AZURE_CONTAINER_APP_NAME",
        "AZURE_CONTAINER_APP_FQDN",
        "AZURE_CONTAINER_APP_PRINCIPAL_ID",
        "AZURE_WORKLOAD_IDENTITY_RESOURCE_ID",
    ],
)
def test_stops_before_any_azure_call_when_a_provision_output_is_missing(
    tmp_path, missing
):
    run = run_deploy_app(tmp_path, drop_env=(missing,))

    assert run.returncode != 0
    assert missing in run.stderr
    assert "azd provision" in run.stderr, (
        "a missing deployment output means provisioning has not run (or is "
        "stale); the message must say so"
    )
    assert run.az_calls.strip() == "", (
        f"the hook spent an Azure call before its own guards: {run.az_calls!r}"
    )


def test_fails_when_the_acr_build_fails(tmp_path):
    run = run_deploy_app(tmp_path, acr_build_fails=True)

    assert run.returncode != 0
    assert run.first_index("containerapp update") is None
    assert "SRE_CONTAINER_IMAGE" not in run.azd_calls
