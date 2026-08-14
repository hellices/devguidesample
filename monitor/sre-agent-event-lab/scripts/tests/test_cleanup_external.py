"""Behaviour tests for `cleanup-external.sh`, the azd teardown hook.

`azd down` deletes the azd-owned resource group itself. The only lab
artifacts it cannot see are the subscription-scoped Monitoring Contributor
assignments the Azure SRE Agent setup recorded, so this hook removes those
-- and only those. Everything here is a behaviour test: the script runs as a
program, from a directory that is not the lab, against a fake `az` holding a
staged subscription, exactly as azd runs it.

Two lifecycle rules are covered as well:

* `predown` deletes the recorded external role assignments *before* azd
  destroys anything, and must never touch the azd environment values -- an
  operator who answers "no" at azd's delete prompt keeps a working
  environment.
* `postdown` clears the image values `azd-postprovision.sh` recorded, once
  the resources they point at are really gone.
"""
import os
import re
import subprocess

from cleanup_harness import (
    ABSENT_ASSIGNMENT_NAME,
    AGENT_ASSIGNMENT_NAME,
    AGENT_PRINCIPAL_ID,
    AGENT_UAMI_PRINCIPAL_ID,
    CLEANUP_EXTERNAL,
    LAB_ROOT,
    OTHER_SUBSCRIPTION_ID,
    READER_ROLE_ID,
    Staged,
    SUBSCRIPTION_ID,
    UAMI_ASSIGNMENT_NAME,
    agent_setup,
    assignment_document,
    assignment_id,
    run_cleanup,
    staged_assignments,
)


RECORDED_ASSIGNMENT_ID = assignment_id(AGENT_ASSIGNMENT_NAME)
RECORDED_UAMI_ASSIGNMENT_ID = assignment_id(UAMI_ASSIGNMENT_NAME)
# The one deliberately unpinned call: it reads whichever account is active
# so the hook can refuse to act on the wrong one.
ACTIVE_ACCOUNT_PROBE = "az account show --query id"
SUBSCRIPTION_PIN = '--subscription "${SUBSCRIPTION_ID}"'


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


def test_cleanup_external_exists_and_is_executable():
    assert CLEANUP_EXTERNAL.is_file()
    assert os.access(CLEANUP_EXTERNAL, os.X_OK)


def test_cleanup_never_deletes_broad_scopes():
    text = CLEANUP_EXTERNAL.read_text()

    assert "az group delete" not in text
    assert "az resource delete" not in text
    assert "--all" not in text
    assert "az role assignment delete" in text


def test_cleanup_pins_every_azure_call_except_the_active_account_probe():
    """The Azure CLI's active subscription is whatever the operator last
    selected; every call that reads or deletes must name the target one."""
    for command in _az_invocations(CLEANUP_EXTERNAL.read_text()):
        if command.startswith(ACTIVE_ACCOUNT_PROBE):
            continue
        assert SUBSCRIPTION_PIN in command, (
            f"cleanup-external.sh runs an unpinned Azure CLI command: {command}"
        )


def test_cleanup_refuses_assignment_from_other_subscription(tmp_path):
    """A hand-edited evidence file must never point cleanup at a role
    assignment that lives in somebody else's subscription."""
    run = run_cleanup(
        tmp_path,
        ["--yes"],
        evidence=agent_setup(
            monitoring_assignment_id=assignment_id(
                AGENT_ASSIGNMENT_NAME, OTHER_SUBSCRIPTION_ID
            )
        ),
    )

    assert run.returncode != 0
    assert "does not belong to current subscription" in run.stderr
    assert "role assignment delete" not in run.az_calls


def test_cleanup_dry_run_never_deletes(tmp_path):
    run = run_cleanup(tmp_path, [], evidence=agent_setup())

    assert run.returncode == 0, run.stderr
    assert "az role assignment delete" not in run.az_calls
    assert "role assignment delete" not in run.az_calls
    assert RECORDED_ASSIGNMENT_ID in run.stdout
    assert "Dry run only" in run.stdout


def test_cleanup_deletes_both_recorded_assignments_after_verifying_them(tmp_path):
    run = run_cleanup(tmp_path, ["--yes"], evidence=agent_setup())

    assert run.returncode == 0, run.stderr
    assert f"role assignment delete --ids {RECORDED_ASSIGNMENT_ID}" in run.az_calls
    assert f"role assignment delete --ids {RECORDED_UAMI_ASSIGNMENT_ID}" in run.az_calls
    assert f"--subscription {SUBSCRIPTION_ID}" in run.az_calls
    assert "group delete" not in run.az_calls
    # Each assignment is read back before it is deleted.
    assert run.az_calls.index("rest --only-show-errors --method get") < run.az_calls.index(
        "role assignment delete"
    )


def test_cleanup_refuses_an_assignment_held_by_another_principal(tmp_path):
    """The recorded ID names an assignment; only the principal proves it is
    the Agent's. A recycled ID belonging to anything else is left alone."""
    assignments = staged_assignments()
    assignments[AGENT_ASSIGNMENT_NAME] = assignment_document(
        "ffffffff-0000-4000-8000-ffffffffffff"
    )

    run = run_cleanup(
        tmp_path, ["--yes"], evidence=agent_setup(), assignments=assignments
    )

    assert run.returncode != 0
    assert AGENT_ASSIGNMENT_NAME in run.stderr
    assert "role assignment delete" not in run.az_calls, (
        "no assignment may be deleted once any recorded record failed validation"
    )


def test_cleanup_refuses_an_assignment_scoped_below_the_subscription(tmp_path):
    """Only the subscription-scoped assignment lives outside the azd resource
    group; anything narrower is azd's to delete, not this hook's."""
    assignments = staged_assignments()
    assignments[AGENT_ASSIGNMENT_NAME] = assignment_document(
        AGENT_PRINCIPAL_ID,
        scope=f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-sre-lab",
    )

    run = run_cleanup(
        tmp_path, ["--yes"], evidence=agent_setup(), assignments=assignments
    )

    assert run.returncode != 0
    assert "role assignment delete" not in run.az_calls


def test_cleanup_refuses_an_assignment_of_another_role(tmp_path):
    assignments = staged_assignments()
    assignments[AGENT_ASSIGNMENT_NAME] = assignment_document(
        AGENT_PRINCIPAL_ID,
        role_definition_id=(
            f"/subscriptions/{SUBSCRIPTION_ID}/providers/Microsoft.Authorization"
            f"/roleDefinitions/{READER_ROLE_ID}"
        ),
    )

    run = run_cleanup(
        tmp_path, ["--yes"], evidence=agent_setup(), assignments=assignments
    )

    assert run.returncode != 0
    assert "role assignment delete" not in run.az_calls


def test_cleanup_accepts_an_assignment_that_is_already_absent(tmp_path):
    """Re-running `azd down`, or an operator who removed the assignment by
    hand, must not fail the teardown."""
    run = run_cleanup(
        tmp_path,
        ["--yes"],
        evidence=agent_setup(
            monitoring_assignment_id=assignment_id(ABSENT_ASSIGNMENT_NAME)
        ),
    )

    assert run.returncode == 0, run.stderr
    assert "already absent" in run.stdout
    assert ABSENT_ASSIGNMENT_NAME not in run.az_calls.split("role assignment delete")[-1]
    assert f"role assignment delete --ids {RECORDED_UAMI_ASSIGNMENT_ID}" in run.az_calls


def test_cleanup_deletes_a_record_repeated_under_both_keys_once(tmp_path):
    """An Agent configured with a single identity records the same
    assignment under both keys; it must be removed once, not twice."""
    run = run_cleanup(
        tmp_path,
        ["--yes"],
        evidence=agent_setup(
            uami_assignment_id=RECORDED_ASSIGNMENT_ID,
            uami_principal_id=AGENT_PRINCIPAL_ID,
        ),
    )

    assert run.returncode == 0, run.stderr
    deletions = [
        line
        for line in run.az_calls.splitlines()
        if line.startswith("role assignment delete")
    ]
    assert deletions == [
        f"role assignment delete --ids {RECORDED_ASSIGNMENT_ID} "
        f"--subscription {SUBSCRIPTION_ID} --output none"
    ]


def test_cleanup_does_not_dedupe_a_second_id_that_is_only_a_suffix_of_the_first(
    tmp_path,
):
    """The "already verified" check must match a whole recorded ID, not any
    suffix of the newline-joined string it is held in. A UAMI-key record
    that merely *ends with* the same characters as the already-verified
    monitoring-key record is a different value and must still be validated
    on its own -- a suffix-only "match" would silently skip validating (and
    so deleting) whatever it actually names, exactly like the untrusted
    records this hook exists to stop."""
    monitoring_id = RECORDED_ASSIGNMENT_ID
    suffix_only_id = monitoring_id[-40:]
    assert not suffix_only_id.startswith("/subscriptions/"), (
        "the crafted ID must not independently pass the subscription-prefix "
        "check -- it must only ever be seen through the dedupe path"
    )

    run = run_cleanup(
        tmp_path,
        ["--yes"],
        evidence=agent_setup(
            uami_assignment_id=suffix_only_id,
            uami_principal_id=AGENT_UAMI_PRINCIPAL_ID,
        ),
    )

    assert run.returncode != 0, (
        "a suffix-only match let a second, distinct recorded ID go "
        f"unvalidated: stdout={run.stdout!r} stderr={run.stderr!r}"
    )
    assert "does not belong to current subscription" in run.stderr
    assert "role assignment delete" not in run.az_calls, (
        "a single untrusted record must leave the whole subscription untouched"
    )


def test_cleanup_tolerates_a_cli_warning_on_a_successful_verification_read(tmp_path):
    """A verified read that also emits an azure-cli warning on stderr (a
    preview notice, an extension-update nag) must still parse the ARM
    document from stdout and proceed -- merging the two streams (as a bare
    `2>&1` would) corrupts the JSON with the warning text and makes a
    legitimate, live assignment look unreadable."""
    assignments = staged_assignments()
    assignments[AGENT_ASSIGNMENT_NAME] = Staged(
        assignment_document(AGENT_PRINCIPAL_ID),
        stderr_extra="WARNING: This command is in preview and under development.\n",
    )

    run = run_cleanup(
        tmp_path, ["--yes"], evidence=agent_setup(), assignments=assignments
    )

    assert run.returncode == 0, run.stderr
    assert f"role assignment delete --ids {RECORDED_ASSIGNMENT_ID}" in run.az_calls
    assert f"role assignment delete --ids {RECORDED_UAMI_ASSIGNMENT_ID}" in run.az_calls


def test_cleanup_absent_detection_reads_stderr_alone_ignoring_stray_stdout(tmp_path):
    """The already-absent check inspects stderr alone. Unrelated content on
    stdout during a failing call (a real `az rest` failure never produces
    any, but a robust reader must not depend on that) must not stop the
    'already absent' no-op the RoleAssignmentNotFound text on stderr asks
    for."""
    assignments = staged_assignments()
    assignments[AGENT_ASSIGNMENT_NAME] = Staged(
        '@error:ERROR: Not Found({"error":{"code":"RoleAssignmentNotFound",'
        '"message":"The role assignment is not found."}})',
        stdout_noise='{"unexpected": "stdout noise"}\n',
    )

    run = run_cleanup(
        tmp_path, ["--yes"], evidence=agent_setup(), assignments=assignments
    )

    assert run.returncode == 0, run.stderr
    assert "already absent" in run.stdout
    assert (
        f"role assignment delete --ids {RECORDED_UAMI_ASSIGNMENT_ID}" in run.az_calls
    )
    assert AGENT_ASSIGNMENT_NAME not in run.az_calls.split("role assignment delete")[-1]


def test_cleanup_reports_the_real_error_unmixed_with_warning_noise(tmp_path):
    """A verification read that fails for a real reason (not
    RoleAssignmentNotFound) must surface that real error text -- unmixed
    with any warning also present on stderr -- and must never delete."""
    assignments = staged_assignments()
    assignments[AGENT_ASSIGNMENT_NAME] = Staged(
        '@error:ERROR: Forbidden({"error":{"code":"AuthorizationFailed"}})',
        stderr_extra="WARNING: This command is in preview and under development.\n",
    )

    run = run_cleanup(
        tmp_path, ["--yes"], evidence=agent_setup(), assignments=assignments
    )

    assert run.returncode != 0
    assert "Unable to verify recorded role assignment" in run.stderr
    assert "AuthorizationFailed" in run.stderr
    assert "already absent" not in run.stdout
    assert "role assignment delete" not in run.az_calls


def test_cleanup_verification_read_requests_only_show_errors():
    """`--only-show-errors` asks azure-cli itself to drop most warnings
    before they are ever written, on top of the script's own stream split."""
    text = CLEANUP_EXTERNAL.read_text()
    rest_calls = [
        command for command in _az_invocations(text) if command.startswith("az rest")
    ]
    assert rest_calls, "expected an `az rest` verification call"
    assert all("--only-show-errors" in command for command in rest_calls)


def test_cleanup_refuses_an_assignment_it_cannot_read(tmp_path):
    """A read that fails for any other reason (no permission, throttling)
    leaves the record unverified, and an unverified deletion is exactly
    what this hook must never do."""
    assignments = staged_assignments()
    assignments[AGENT_ASSIGNMENT_NAME] = (
        "@error:ERROR: Forbidden({\"error\":{\"code\":\"AuthorizationFailed\"}})"
    )

    run = run_cleanup(
        tmp_path, ["--yes"], evidence=agent_setup(), assignments=assignments
    )

    assert run.returncode != 0
    assert "Unable to verify recorded role assignment" in run.stderr
    assert "role assignment delete" not in run.az_calls


def test_cleanup_succeeds_without_agent_evidence(tmp_path):
    """`azd down` runs this hook with continueOnError: false, so a lab that
    never configured the Agent must still tear down cleanly -- without
    needing an Azure CLI session at all."""
    run = run_cleanup(tmp_path, ["--yes"])

    assert run.returncode == 0, run.stderr
    assert run.az_calls == "", f"nothing external exists, but the hook called: {run.az_calls}"


def test_cleanup_succeeds_when_the_evidence_records_no_assignment(tmp_path):
    run = run_cleanup(
        tmp_path,
        ["--yes"],
        evidence=agent_setup(
            monitoring_assignment_id="",
            agent_principal_id="",
            uami_assignment_id="",
            uami_principal_id="",
        ),
    )

    assert run.returncode == 0, run.stderr
    assert "role assignment delete" not in run.az_calls
    assert "no subscription role assignment" in run.stdout


def test_cleanup_refuses_an_assignment_recorded_without_its_principal(tmp_path):
    """Without the principal the record cannot be verified, and an
    unverifiable deletion is exactly what this hook must never do."""
    run = run_cleanup(
        tmp_path, ["--yes"], evidence=agent_setup(agent_principal_id="")
    )

    assert run.returncode != 0
    assert "Incomplete Agent setup evidence" in run.stderr
    assert "role assignment delete" not in run.az_calls


def test_cleanup_refuses_malformed_evidence(tmp_path):
    run = run_cleanup(tmp_path, ["--yes"], raw_evidence="{not json at all")

    assert run.returncode != 0
    assert "role assignment delete" not in run.az_calls


def test_cleanup_refuses_to_act_from_another_active_subscription(tmp_path):
    run = run_cleanup(
        tmp_path,
        ["--yes"],
        evidence=agent_setup(),
        active_subscription_id=OTHER_SUBSCRIPTION_ID,
    )

    assert run.returncode != 0
    assert "Refusing to continue in subscription" in run.stderr
    assert f"Expected {SUBSCRIPTION_ID}" in run.stderr
    assert "role assignment delete" not in run.az_calls
    assert "rest --method" not in run.az_calls


def test_cleanup_reports_a_signed_out_azure_cli(tmp_path):
    run = run_cleanup(tmp_path, ["--yes"], evidence=agent_setup(), signed_out=True)

    assert run.returncode != 0
    assert "az login" in run.stderr
    assert "Please run 'az login' to setup account." not in run.stderr
    assert "role assignment delete" not in run.az_calls


def test_cleanup_fails_closed_without_a_configured_subscription(tmp_path):
    run = run_cleanup(tmp_path, ["--yes"], evidence=agent_setup(), azd_values={})

    assert run.returncode != 0
    assert "azd env set AZURE_SUBSCRIPTION_ID" in run.stderr
    assert "role assignment delete" not in run.az_calls


def test_cleanup_fails_when_a_recorded_assignment_cannot_be_deleted(tmp_path):
    """Leaving a subscription-scoped assignment behind is the one outcome
    this hook exists to prevent, so a failed deletion stops `azd down`
    before it destroys the resource group."""
    run = run_cleanup(
        tmp_path, ["--yes"], evidence=agent_setup(), delete_fails=True
    )

    assert run.returncode != 0
    assert RECORDED_ASSIGNMENT_ID in run.stderr


def test_role_cleanup_leaves_the_azd_environment_untouched(tmp_path):
    """`predown` runs before azd asks the operator to confirm the deletion.
    Clearing the recorded image values there would break an environment
    whose owner answered "no", so the role-cleanup mode never writes to the
    azd environment."""
    run = run_cleanup(tmp_path, ["--yes"], evidence=agent_setup())

    assert run.returncode == 0, run.stderr
    assert "env set" not in run.azd_calls, (
        f"predown must not mutate the azd environment: {run.azd_calls!r}"
    )


def test_reset_image_env_clears_only_the_hook_set_image_values(tmp_path):
    """`azd down` deletes the ACR that `azd-postprovision.sh` recorded in
    SRE_CONTAINER_IMAGE/SRE_IMAGE_TAG. Reusing the environment afterwards
    would make `azd provision` redeploy an image tag that no longer exists,
    so `postdown` clears both once the resources are really gone."""
    run = run_cleanup(tmp_path, ["--reset-image-env", "--yes"], evidence=agent_setup())

    assert run.returncode == 0, run.stderr
    assert "env set SRE_CONTAINER_IMAGE ''" in run.azd_calls
    assert "env set SRE_IMAGE_TAG ''" in run.azd_calls
    assert run.az_calls == "", (
        f"the environment reset must not touch Azure: {run.az_calls!r}"
    )
    assert "role assignment delete" not in run.az_calls


def test_reset_image_env_writes_to_the_lab_project_from_any_directory(tmp_path):
    """Run by hand from the repository root, `azd env set` would otherwise
    resolve whatever project the working directory happens to hold."""
    run = run_cleanup(tmp_path, ["--reset-image-env", "--yes"])

    assert run.returncode == 0, run.stderr
    assert f"cwd={LAB_ROOT}" in run.azd_calls, (
        f"azd env writes were not pinned to the lab project: {run.azd_calls!r}"
    )
    assert "no project exists" not in run.azd_calls


def test_reset_image_env_dry_run_does_not_mutate_the_azd_environment(tmp_path):
    run = run_cleanup(tmp_path, ["--reset-image-env"])

    assert run.returncode == 0, run.stderr
    assert "env set" not in run.azd_calls, (
        f"a dry run (no --yes) must not mutate the azd environment: {run.azd_calls!r}"
    )


def test_cleanup_rejects_an_unknown_option(tmp_path):
    run = run_cleanup(tmp_path, ["--purge-everything"], evidence=agent_setup())

    assert run.returncode == 2
    assert "Usage" in run.stderr
    assert run.az_calls == ""


def test_cleanup_runs_under_bash_32(tmp_path):
    """macOS ships Bash 3.2, where `"${ARRAY[@]}"` on an empty array aborts
    under `set -u` and none of Bash 4's builtins exist. The script must run
    under the *system* `/bin/bash` specifically -- not whatever `bash`
    happens to resolve first on PATH, which on a developer machine with a
    newer Bash installed (Homebrew's, for example) would silently stop
    exercising Bash 3.2 at all despite this test's name and purpose."""
    system_bash = "/bin/bash"
    version = subprocess.run(
        [system_bash, "-c", "echo ${BASH_VERSINFO[0]}"],
        capture_output=True,
        text=True,
    ).stdout.strip()

    for arguments, evidence in (
        (["--yes"], None),
        (["--yes"], agent_setup()),
        (["--reset-image-env", "--yes"], None),
    ):
        run = run_cleanup(
            tmp_path / f"run-{len(arguments)}-{evidence is None}",
            arguments,
            evidence=evidence,
            bash=system_bash,
        )
        assert run.returncode == 0, (
            f"cleanup-external.sh must run on bash {version}: {run.stderr}"
        )
        assert "unbound variable" not in run.stderr
        assert "syntax error" not in run.stderr

    text = CLEANUP_EXTERNAL.read_text()
    for bash_4_only in ("mapfile", "readarray", "declare -A", "${_,,}"):
        assert bash_4_only not in text, (
            f"{bash_4_only} does not exist in the Bash 3.2 macOS ships"
        )


def test_azure_yaml_removes_roles_predown_and_resets_image_values_postdown():
    config = (LAB_ROOT / "azure.yaml").read_text()

    predown = config.split("predown:", 1)[1].split("postdown:", 1)[0]
    postdown = config.split("postdown:", 1)[1]

    assert "./scripts/cleanup-external.sh --yes" in predown
    assert "--reset-image-env" not in predown, (
        "predown runs before azd's delete confirmation: an operator who "
        "cancels must keep the recorded image values"
    )
    assert "./scripts/cleanup-external.sh --reset-image-env --yes" in postdown


def test_readme_documents_the_teardown_hooks_and_manual_recovery():
    readme = (LAB_ROOT / "README.md").read_text()
    section = readme.split("## 정리", 1)[1].split("\n## ", 1)[0]

    assert "predown" in section
    assert "postdown" in section
    assert "cleanup-external.sh" in section
    assert "--reset-image-env" in section
    # azd runs `predown` before its own delete confirmation prompt (the
    # prompt lives inside the same action the hook wraps), so canceling
    # that prompt does not undo a predown hook that already ran. The
    # recorded external role assignments are gone either way; only the
    # README's claim about what "cancel" leaves behind must not overstate
    # it as a fully working environment.
    assert "취소" in section, "the README must describe what canceling azd down leaves behind"
    assert "확인" in section, "the README must name azd's delete confirmation prompt"
    assert not re.search(r"완전히\s*(작동|동작)", section), (
        "the README must not claim canceling leaves a fully working environment "
        "-- predown already removed the recorded roles before the prompt"
    )
    assert "acknowledge agent-setup" in section, (
        "the README must name the recovery step (re-running Agent setup/role "
        "assignment) an operator needs after canceling"
    )
