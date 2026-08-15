import re
import shutil
import subprocess
from pathlib import Path

from azd_common_harness import run_common


COMMON_SH = Path(__file__).parents[1] / "common.sh"
DEPLOY_SH = Path(__file__).parents[1] / "deploy.sh"
CLEANUP_SH = Path(__file__).parents[1] / "cleanup.sh"
CLEANUP_EXTERNAL_SH = Path(__file__).parents[1] / "cleanup-external.sh"
QUERY_EVIDENCE_SH = Path(__file__).parents[1] / "query-evidence.sh"
RUN_SCENARIO_SH = Path(__file__).parents[1] / "run-scenario.sh"
CAPTURE_SCENARIO_SH = Path(__file__).parents[1] / "capture-scenario.sh"
BASELINE_SH = Path(__file__).parents[1] / "baseline.sh"

BASH = shutil.which("bash") or "/bin/bash"

UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b")

LEGACY_RESOURCE_GROUP_FLAG = "--legacy-delete-resource-group"

REQUIRED_ENV = {
    "AZURE_SUBSCRIPTION_ID": "11111111-2222-3333-4444-555555555555",
    "AZURE_RESOURCE_GROUP": "rg-sre-lab-test",
    "AZURE_ENV_NAME": "sre-lab-test",
}


def test_deployment_output_reads_the_current_azd_environment(tmp_path):
    """`deployment_output` used to look up a fixed subscription-scope
    deployment name; it must now return the values `load_lab_config`
    resolved from the current azd environment, so a fresh `azd up` in any
    environment works without editing common.sh.
    """
    azd_values = {
        **REQUIRED_ENV,
        "AZURE_CONTAINER_APP_NAME": "ca-current-env",
        "AZURE_CONTAINER_APP_FQDN": "ca-current-env.example.com",
        "workspaceCustomerId": "6f6f6f6f-1111-2222-3333-444444444444",
    }
    result = run_common(
        tmp_path,
        env={},
        azd_values=azd_values,
        command=(
            "load_lab_config; "
            'printf "%s|%s|%s" '
            '"$(deployment_output containerAppName)" '
            '"$(deployment_output containerAppFqdn)" '
            '"$(deployment_output workspaceCustomerId)"'
        ),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "ca-current-env|ca-current-env.example.com|"
        "6f6f6f6f-1111-2222-3333-444444444444"
    )


def test_deployment_output_refuses_an_unknown_output_name(tmp_path):
    result = run_common(
        tmp_path,
        env=dict(REQUIRED_ENV),
        azd_values=dict(REQUIRED_ENV),
        command="load_lab_config; deployment_output notAnOutput",
    )

    assert result.returncode == 2
    assert "Unknown deployment output: notAnOutput" in result.stderr


def test_common_no_longer_queries_a_fixed_subscription_deployment():
    """Regression guard for the removed lookup: nothing may reintroduce a
    deployment-name based read of the lab's outputs."""
    script = COMMON_SH.read_text()

    assert "FINAL_DEPLOYMENT_NAME" not in script
    assert "az deployment sub show" not in script
    assert "az deployment group show" not in script


def test_common_does_not_expose_personal_subscription_display_name():
    script = COMMON_SH.read_text()

    assert "SUBSCRIPTION_NAME" not in script
    assert "ME-MngEnvMCAP310512-inhwanhwang-3" not in script
    assert "inhwanhwang" not in script
    # common.sh must never hardcode *any* subscription ID again -- it
    # resolves one via load_lab_config (explicit env > azd env > default).
    # The shape is forbidden rather than the one value this task removed,
    # so the guard also catches the next person's subscription, and so the
    # test does not have to restate a real subscription ID to forbid it.
    assert UUID_PATTERN.search(script) is None, UUID_PATTERN.search(script).group()


def test_verify_subscription_reports_only_subscription_id_on_mismatch(tmp_path):
    """verify_subscription must not reference an undeclared SUBSCRIPTION_NAME.

    Regression guard for `set -u`: after removing SUBSCRIPTION_NAME, the
    mismatch message must only report the resolved SUBSCRIPTION_ID (now
    loaded via `load_lab_config`, not a hardcoded literal), or the function
    will crash under `set -u` when the variable no longer exists.
    """
    az_script = (
        'if [[ "$1 $2" == "account show" ]]; then\n'
        '  echo "wrong-subscription-id"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    result = run_common(
        tmp_path,
        env=dict(REQUIRED_ENV),
        azd_values=dict(REQUIRED_ENV),
        command="load_lab_config; verify_subscription",
        az_script=az_script,
    )

    assert result.returncode != 0
    assert "unbound variable" not in result.stderr
    assert "SUBSCRIPTION_NAME" not in result.stderr
    assert REQUIRED_ENV["AZURE_SUBSCRIPTION_ID"] in result.stderr


def test_deploy_delegates_to_azd_up():
    """The subscription-scope templates deploy.sh used to deploy were removed
    when the lab moved to azd, so deploy.sh must not reference them any more.
    It stays as a thin compatibility wrapper so the documented command keeps
    working.
    """
    script = DEPLOY_SH.read_text()

    assert "azd up" in script
    assert "subscription" + ".bicep" not in script
    assert "az deployment sub validate" not in script
    assert "az deployment sub create" not in script
    assert "az deployment group" not in script
    assert 'IMAGE_TAG="20260812.4"' not in script


def test_no_tracked_lab_file_references_the_deleted_subscription_templates():
    lab_root = Path(__file__).parents[2]
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=lab_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    needle = "subscription" + ".bicep"
    readable = {".sh", ".py", ".md", ".json", ".yaml", ".yml", ".bicep", ".bicepparam"}

    offenders = []
    for relative_path in tracked:
        path = lab_root / relative_path
        if path.suffix not in readable or not path.is_file():
            continue
        if needle in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(relative_path)

    assert offenders == [], f"tracked files still reference deleted templates: {offenders}"


def test_readme_documents_a_working_deployment_command():
    readme = (Path(__file__).parents[2] / "README.md").read_text()

    assert "azd up" in readme
    assert "az deployment sub show" not in readme
    assert "azd env get-value AZURE_CONTAINER_APP_FQDN" in readme


def test_readme_documents_scenario_scripts_read_the_current_azd_environment():
    """`run-scenario.sh` and `query-evidence.sh` now resolve deployment
    outputs through `common.sh`'s `load_lab_config` (explicit env > current
    `azd env get-value` > allowed default), so they work against whatever
    azd environment is currently selected -- not a fixed pre-azd resource
    group. The README's scenario-execution section must describe that
    mechanism instead of the old "legacy, not yet rewritten" caveat.
    """
    readme = (Path(__file__).parents[2] / "README.md").read_text()

    scenario_heading = "## 시나리오 실행"
    assert scenario_heading in readme
    section = readme.split(scenario_heading, 1)[1].split("##", 1)[0]

    assert "run-scenario.sh" in section
    assert "load_lab_config" in section
    assert "레거시" not in section, (
        "README's scenario-execution section must no longer describe "
        "run-scenario.sh/query-evidence.sh as reading a legacy, pre-azd "
        "deployment lookup -- load_lab_config now reads the current azd "
        "environment."
    )


def test_scenario_waits_for_new_revision_before_load():
    common = COMMON_SH.read_text()
    scenario = (Path(__file__).parents[1] / "run-scenario.sh").read_text()
    # Line continuations are formatting, not behaviour: the call is checked
    # with its own wrapping collapsed.
    collapsed = " ".join(scenario.replace("\\\n", " ").split())

    assert "wait_for_new_revision_ready()" in common
    assert 'OLD_REVISION="$(latest_revision_name "${APP_NAME}")"' in scenario
    assert 'wait_for_new_revision_ready "${APP_NAME}" "${OLD_REVISION}"' in collapsed


def test_cleanup_removes_both_subscription_monitoring_assignments():
    """The verified deletion of the two subscription-scoped assignments now
    lives in `cleanup-external.sh` -- the script `azd down`'s `predown` hook
    runs and the one `cleanup.sh` forwards to -- so both recorded records,
    their principals, the Monitoring Contributor role definition and the
    read-back that verifies them must be there. `test_cleanup_external.py`
    exercises the resulting behaviour against a staged subscription.
    """
    script = CLEANUP_EXTERNAL_SH.read_text()

    assert "monitoring_contributor_assignment_id" in script
    assert "uami_monitoring_contributor_assignment_id" in script
    assert "agent_principal_id" in script
    assert "agent_user_assigned_principal_id" in script
    assert "749f88d5-cbae-40b8-bcfc-e573ddc772fa" in script
    assert "az rest --only-show-errors --method get" in script
    assert "Incomplete Agent setup evidence" in script
    # A lab that never configured the Agent has no evidence file at all,
    # and `azd down` runs this hook with continueOnError: false -- so a
    # missing file is a no-op here, not the refusal the standalone script
    # used to report.
    assert "Agent setup evidence is required for cleanup" not in script
    assert "Nothing outside the azd resource group to clean up." in script


def test_s1_and_s2_record_injection_before_container_app_update():
    script = (Path(__file__).parents[1] / "run-scenario.sh").read_text()
    main_case = script.rsplit('case "${SCENARIO}" in', 1)[1]

    for branch, next_branch in (("  s1)", "  s2)"), ("  s2)", "  s3)")):
        section = main_case.split(branch, 1)[1].split(next_branch, 1)[0]
        assert section.index('INJECTED_AT="$(utc_now)"') < section.index(
            "az containerapp update"
        )
        assert 'REVISION_READY_AT="$(utc_now)"' in section


def test_s3_records_injection_before_role_deletion():
    script = (Path(__file__).parents[1] / "run-scenario.sh").read_text()
    main_case = script.rsplit('case "${SCENARIO}" in', 1)[1]
    section = main_case.split("  s3)", 1)[1].split("esac", 1)[0]

    assert section.index('INJECTED_AT="$(utc_now)"') < section.index(
        "az role assignment delete"
    )
    assert 'ROLE_DELETED_AT="$(utc_now)"' in section


def test_lab_state_runs_bound_to_the_resolved_configuration():
    """`lab_state.py` must never resolve the lab's identity itself.

    `common.sh` is the one place that decides which azd environment,
    subscription and resource group the caller verified, so its `lab_state`
    helper hands those exact values to every state command. A state file
    that belongs to another environment is then refused instead of quietly
    unlocking a run here.
    """
    script = COMMON_SH.read_text()
    state_helper = script.split("lab_state() {", 1)[1].split("\n}", 1)[0]
    tool_helper = script.split("lab_tool() {", 1)[1].split("\n}", 1)[0]

    assert "lab_tool lab_state.py" in state_helper
    assert '"${EVIDENCE_ROOT}/state.json"' in state_helper
    assert 'AZURE_ENV_NAME="${AZURE_ENV_NAME}"' in tool_helper
    assert 'AZURE_SUBSCRIPTION_ID="${SUBSCRIPTION_ID}"' in tool_helper
    assert 'AZURE_RESOURCE_GROUP="${RESOURCE_GROUP}"' in tool_helper


def test_run_scenario_checks_the_run_order_before_injecting_a_failure():
    """The gate is worthless after the fact: `require-run` has to run before
    the first `az` call that breaks the workload."""
    script = RUN_SCENARIO_SH.read_text()

    assert script.index('lab_state require-run "${SCENARIO}"') < script.index(
        "az containerapp update"
    )
    assert script.index('lab_state require-run "${SCENARIO}"') < script.index(
        "az role assignment delete"
    )


def test_run_scenario_records_recovery_only_after_health_and_alert_checks():
    script = RUN_SCENARIO_SH.read_text()

    assert "wait_for_app_ready" in script
    assert "wait_for_alert_resolved" in script
    assert script.index("wait_for_alert_resolved") < script.index(
        'lab_state mark-recovered'
    )
    assert "lab_state mark-failed" in script


def test_capture_scenario_records_the_terminal_state_from_the_timeline():
    """The capture status is derived from the normalized timeline, so a
    missing thread/investigation/conclusion is recorded as itself and can
    never be reported as a successful capture."""
    script = CAPTURE_SCENARIO_SH.read_text()

    assert 'lab_state record-capture "${SCENARIO}"' in script
    assert '--timeline "${NORMALIZED_FILE}"' in script
    assert 'lab_state evidence-dir "${SCENARIO}"' in script


def test_baseline_records_the_passing_baseline_stage():
    script = BASELINE_SH.read_text()

    assert "lab_state mark baseline_passed" in script
    assert script.index("lab_state mark baseline_passed") > script.index(
        "did not show both request types"
    )


def test_lab_state_and_score_are_exercised_as_programs():
    """`lab_state.py` and `score.py` decide whether a scenario may run and
    what the evidence is worth, so both are driven through their real API
    and their real command line, not read as text."""
    for module_name, test_name in (
        ("lab_state.py", "test_lab_state.py"),
        ("score.py", "test_score.py"),
    ):
        assert (Path(__file__).parents[1] / module_name).is_file()
        tests = (Path(__file__).parent / test_name).read_text()
        assert "subprocess.run" in tests, f"{module_name} has no command-line test"


def test_activity_log_export_projects_only_incident_fields():
    script = QUERY_EVIDENCE_SH.read_text()

    assert "operationName:" in script
    assert "correlationId:" in script
    assert "caller:" not in script
    assert "claims:" not in script


def test_cleanup_delegates_to_external_cleanup_and_keeps_recovery_deletion_behind_a_flag():
    """`cleanup.sh` used to delete the whole resource group itself, which is
    now `azd down`'s job. It stays as a compatibility wrapper: it names the
    supported command, forwards to `cleanup-external.sh`, and only deletes a
    resource group when an operator explicitly asks for the documented
    recovery path. `test_lab_scripts.py` runs both paths as programs.
    """
    script = CLEANUP_SH.read_text()
    readme = (Path(__file__).parents[2] / "README.md").read_text()

    assert "azd down --purge" in script
    assert "cleanup-external.sh" in script
    assert LEGACY_RESOURCE_GROUP_FLAG in script
    assert LEGACY_RESOURCE_GROUP_FLAG in readme, (
        "the legacy resource-group deletion must be documented for recovery"
    )
    # Nothing may delete a resource group before the legacy flag is parsed.
    assert script.index(LEGACY_RESOURCE_GROUP_FLAG) < script.index("az group delete")


def test_scenario_query_capture_cleanup_scripts_are_exercised_as_programs():
    """The four entry points are covered by execution tests, not by reading
    their text: `test_lab_scripts.py` runs each one against fake
    `az`/`azd`/`python` executables from a working directory outside the
    lab, which is the only way to catch a caller that reassigns a name
    `common.sh` already made readonly.
    """
    lab_script_tests = (Path(__file__).parent / "test_lab_scripts.py").read_text()

    for script_name in (
        "run-scenario.sh",
        "query-evidence.sh",
        "capture-scenario.sh",
        "cleanup.sh",
    ):
        assert f'"{script_name}"' in lab_script_tests, (
            f"{script_name} has no execution test"
        )



# --- The evidence directory is a name first, a directory second -------------


def run_in_throwaway_lab(tmp_path, command):
    """Source a copy of `common.sh` whose `EVIDENCE_ROOT` is disposable.

    `EVIDENCE_ROOT` is `readonly` and derived from the script's own
    location, so the only way to exercise the directory helpers without
    writing into the repository's real `evidence/` is to source a copy that
    lives somewhere else.
    """
    lab = tmp_path / "lab"
    (lab / "scripts").mkdir(parents=True, exist_ok=True)
    (lab / "evidence").mkdir(parents=True, exist_ok=True)
    shutil.copy(str(COMMON_SH), str(lab / "scripts" / "common.sh"))
    return subprocess.run(
        [BASH, "-c", 'source "{0}"\n{1}\n'.format(lab / "scripts" / "common.sh", command)],
        capture_output=True,
        text=True,
    ), lab / "evidence"


def test_evidence_dir_path_names_a_directory_without_creating_it(tmp_path):
    """`run-scenario.sh` needs the evidence path *before* it asks
    `lab_state.py` to admit the run, because the path is what it registers.
    Creating the directory at that point left an empty `sN-<timestamp>/`
    behind whenever the run was then refused -- litter an operator has to
    tell apart from a real attempt while reading `evidence/`. So naming and
    creating are separate steps: this one only names.
    """
    result, evidence_root = run_in_throwaway_lab(
        tmp_path, 'printf "%s" "$(evidence_dir_path s1)"'
    )

    assert result.returncode == 0, result.stderr
    named = Path(result.stdout.strip())
    assert named.parent == evidence_root
    assert re.fullmatch(r"s1-\d{8}T\d{6}Z", named.name), named.name
    assert not named.exists(), (
        "naming an evidence directory must not create it: {0}".format(named)
    )
    assert list(evidence_root.iterdir()) == [], (
        "a refused run must leave nothing behind in evidence/"
    )


def test_create_evidence_dir_still_creates_what_it_names(tmp_path):
    """`baseline.sh` writes into the directory immediately, so the eager
    helper must keep working -- the split adds a step, it does not move the
    responsibility."""
    result, evidence_root = run_in_throwaway_lab(
        tmp_path,
        'directory="$(create_evidence_dir baseline)"; '
        '[[ -d "${directory}" ]] || exit 1; '
        'printf "%s" "${directory}"',
    )

    assert result.returncode == 0, result.stderr
    created = Path(result.stdout.strip())
    assert created.is_dir()
    assert created.parent == evidence_root
    assert re.fullmatch(r"baseline-\d{8}T\d{6}Z", created.name), created.name
