from pathlib import Path
import re
import shlex

import pytest
import yaml


ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
AUDIT_COMMAND = "python scripts/docs/audit_pre_pages.py"
REQUIRED_ACTIONS = {
    "actions/checkout": "v7",
    "actions/setup-python": "v7",
    "actions/configure-pages": "v6",
    "actions/upload-pages-artifact": "v5",
    "actions/deploy-pages": "v5",
}


def write_workflow(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def workflow_jobs(
    workflows_dir: Path = WORKFLOWS,
) -> dict[str, dict[str, list[dict[str, object]]]]:
    jobs_by_workflow: dict[str, dict[str, list[dict[str, object]]]] = {}
    for path in sorted(workflows_dir.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(workflow, dict):
            continue
        jobs = workflow.get("jobs")
        if not isinstance(jobs, dict):
            continue
        parsed_jobs: dict[str, list[dict[str, object]]] = {}
        for job_name, job in jobs.items():
            if not isinstance(job_name, str) or not isinstance(job, dict):
                continue
            steps = job.get("steps")
            if not isinstance(steps, list):
                continue
            parsed_jobs[job_name] = [step for step in steps if isinstance(step, dict)]
        jobs_by_workflow[path.name] = parsed_jobs
    return jobs_by_workflow


def workflow_steps(workflows_dir: Path = WORKFLOWS) -> list[tuple[Path, str, dict[str, object]]]:
    steps = []
    for path_name, jobs in workflow_jobs(workflows_dir).items():
        path = workflows_dir / path_name
        for job_name, job_steps in jobs.items():
            for step in job_steps:
                steps.append((path, job_name, step))
    return steps


def action_references(workflows_dir: Path = WORKFLOWS) -> list[tuple[Path, str, str]]:
    references = []
    for path, _, step in workflow_steps(workflows_dir):
        uses = step.get("uses")
        if isinstance(uses, str) and "@" in uses:
            owner_repo, version = uses.rsplit("@", 1)
            references.append((path, owner_repo, version))
    return references


def checkout_inputs_by_workflow(
    workflows_dir: Path = WORKFLOWS,
) -> dict[str, list[dict[str, object] | None]]:
    checkout_inputs: dict[str, list[dict[str, object] | None]] = {}
    for path, _, step in workflow_steps(workflows_dir):
        if step.get("uses") != "actions/checkout@v7":
            continue
        with_block = step.get("with")
        parsed_with = with_block if isinstance(with_block, dict) else None
        checkout_inputs.setdefault(path.name, []).append(parsed_with)
    return checkout_inputs


def shell_command_arguments(run: str) -> list[list[str]]:
    segments = []
    current = []
    quote = ""
    word_start = True
    position = 0
    while position < len(run):
        char = run[position]
        if char == "\\" and quote != "'":
            if run[position + 1:position + 2] == "\n":
                position += 2
                continue
            current.append(run[position:position + 2])
            position += 2
            word_start = False
            continue
        if quote != "'" and (char == "`" or run.startswith("$(", position)):
            raise ValueError("command substitution is unsupported by the static workflow counter")
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
            current.append(char)
            word_start = False
        elif char == "#" and word_start:
            end = run.find("\n", position)
            position = len(run) if end < 0 else end
            continue
        elif char in ";&|()\n":
            segments.append("".join(current))
            current = []
            word_start = True
        else:
            current.append(char)
            word_start = char in " \t\r"
        position += 1
    segments.append("".join(current))
    return [arguments for segment in segments if (arguments := shlex.split(segment, comments=False))]


def count_shell_invocations(run: str, command: list[str]) -> int:
    count = 0
    for arguments in shell_command_arguments(run):
        while arguments:
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", arguments[0]) or arguments[0] in {"env", "command", "exec"}:
                arguments = arguments[1:]
            else:
                break
        if arguments[:len(command)] == command:
            count += 1
        elif len(arguments) >= 3 and arguments[0] in {"bash", "sh"} and arguments[1] == "-c":
            count += count_shell_invocations(arguments[2], command)
    return count


def count_run_command_occurrences(
    jobs: dict[str, list[dict[str, object]]],
    command: str,
) -> int:
    occurrences = 0
    for steps in jobs.values():
        for step in steps:
            run = step.get("run")
            if isinstance(run, str):
                occurrences += count_shell_invocations(run, shlex.split(command))
    return occurrences


def assert_required_action_versions(workflows_dir: Path = WORKFLOWS) -> None:
    references = action_references(workflows_dir)
    for path, action, version in references:
        if action in REQUIRED_ACTIONS:
            assert version == REQUIRED_ACTIONS[action], (path, action, version)
    assert set(REQUIRED_ACTIONS) <= {action for _, action, _ in references}


def assert_checkout_history_contract(workflows_dir: Path = WORKFLOWS) -> None:
    checkout_inputs = checkout_inputs_by_workflow(workflows_dir)
    assert checkout_inputs["docs-ci.yml"] == [{"fetch-depth": 0}]
    assert checkout_inputs["pages.yml"] == [{"fetch-depth": 0}]
    assert checkout_inputs["oryx-python-build-test.yml"] == [None]


def assert_pre_pages_audit_runs_after_search_validation(
    workflows_dir: Path = WORKFLOWS,
) -> None:
    jobs_by_workflow = workflow_jobs(workflows_dir)
    for workflow_name, job_name in (("docs-ci.yml", "validate"), ("pages.yml", "build")):
        jobs = jobs_by_workflow[workflow_name]
        assert job_name in jobs, workflow_name
        steps = jobs[job_name]
        search_positions = [
            index
            for index, step in enumerate(steps)
            if step.get("name") == "Validate search index"
            and step.get("run") == "python scripts/docs/validate_search_index.py"
        ]
        assert len(search_positions) == 1, workflow_name
        audit_position = search_positions[0] + 1
        assert audit_position < len(steps), workflow_name
        audit_step = steps[audit_position]
        assert audit_step.get("name") == "Audit pre-Pages content preservation"
        assert audit_step.get("run") == AUDIT_COMMAND
        assert count_run_command_occurrences(jobs, AUDIT_COMMAND) == 1, workflow_name

    assert count_run_command_occurrences(
        jobs_by_workflow["oryx-python-build-test.yml"], AUDIT_COMMAND,
    ) == 0


def test_quoted_uses_values_are_detected_and_rejected(tmp_path: Path) -> None:
    workflow = tmp_path / "quoted.yml"
    write_workflow(
        workflow,
        """\
name: Quoted action references
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: "actions/checkout@v4"
      - uses: actions/setup-python@v7
      - uses: actions/configure-pages@v6
      - uses: actions/upload-pages-artifact@v5
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/deploy-pages@v5
""",
    )

    assert (workflow, "actions/checkout", "v4") in action_references(tmp_path)
    with pytest.raises(AssertionError, match="actions/checkout"):
        assert_required_action_versions(tmp_path)


def test_checkout_history_contract_rejects_extra_checkout_inputs(tmp_path: Path) -> None:
    write_workflow(
        tmp_path / "docs-ci.yml",
        """\
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
          persist-credentials: false
""",
    )
    write_workflow(
        tmp_path / "pages.yml",
        """\
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
""",
    )
    write_workflow(
        tmp_path / "oryx-python-build-test.yml",
        """\
jobs:
  oryx-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
""",
    )

    with pytest.raises(AssertionError):
        assert_checkout_history_contract(tmp_path)


def test_checkout_history_contract_rejects_oryx_fetch_depth_override(
    tmp_path: Path,
) -> None:
    for name in ("docs-ci.yml", "pages.yml"):
        write_workflow(
            tmp_path / name,
            """\
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
""",
        )
    write_workflow(
        tmp_path / "oryx-python-build-test.yml",
        """\
jobs:
  oryx-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 1
""",
    )

    with pytest.raises(AssertionError):
        assert_checkout_history_contract(tmp_path)


def test_official_actions_use_required_node_24_majors() -> None:
    assert_required_action_versions()


def test_contributing_pages_artifact_reference_matches_workflow_version() -> None:
    action = "actions/upload-pages-artifact"
    workflow_versions = {
        version for _, referenced_action, version in action_references()
        if referenced_action == action
    }
    contributing = (ROOT / "docs/contributing/index.md").read_text(encoding="utf-8")
    documented_versions = set(re.findall(
        rf"https://github\.com/{re.escape(action)}/blob/([^/]+)/action\.yml",
        contributing,
    ))
    assert documented_versions == workflow_versions == {REQUIRED_ACTIONS[action]}


def test_historical_audit_workflows_checkout_full_history() -> None:
    assert_checkout_history_contract()


def test_historical_audit_workflows_run_pre_pages_audit_after_search_validation() -> None:
    assert_pre_pages_audit_runs_after_search_validation()


def test_historical_audit_workflows_reject_cross_job_audit_placement(tmp_path: Path) -> None:
    write_workflow(
        tmp_path / "docs-ci.yml",
        f"""\
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - name: Validate search index
        run: python scripts/docs/validate_search_index.py
  audit:
    runs-on: ubuntu-latest
    steps:
      - name: Audit pre-Pages content preservation
        run: {AUDIT_COMMAND}
""",
    )
    write_workflow(
        tmp_path / "pages.yml",
        f"""\
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Validate search index
        run: python scripts/docs/validate_search_index.py
      - name: Audit pre-Pages content preservation
        run: {AUDIT_COMMAND}
""",
    )
    write_workflow(
        tmp_path / "oryx-python-build-test.yml",
        """\
jobs:
  oryx-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
""",
    )

    with pytest.raises(AssertionError):
        assert_pre_pages_audit_runs_after_search_validation(tmp_path)


def test_historical_audit_workflows_reject_embedded_second_audit_invocation(
    tmp_path: Path,
) -> None:
    write_workflow(
        tmp_path / "docs-ci.yml",
        f"""\
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - name: Validate search index
        run: python scripts/docs/validate_search_index.py
      - name: Audit pre-Pages content preservation
        run: {AUDIT_COMMAND}
      - name: Hidden duplicate
        run: |
          echo before
          {AUDIT_COMMAND} && echo after
""",
    )
    write_workflow(
        tmp_path / "pages.yml",
        f"""\
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Validate search index
        run: python scripts/docs/validate_search_index.py
      - name: Audit pre-Pages content preservation
        run: {AUDIT_COMMAND}
""",
    )
    write_workflow(
        tmp_path / "oryx-python-build-test.yml",
        """\
jobs:
  oryx-build:
    runs-on: ubuntu-latest
    steps:
      - name: Build
        run: echo ok
""",
    )

    with pytest.raises(AssertionError):
        assert_pre_pages_audit_runs_after_search_validation(tmp_path)


def test_root_guidance_keeps_full_history_remediation_only_in_detailed_contract() -> None:
    for relative_path in ("AGENTS.md", "CONTRIBUTING.md", "README.md"):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert AUDIT_COMMAND in text, relative_path
        assert "docs/contributing/index.md" in text, relative_path
        assert "전체 Git 이력" in text, relative_path
        assert "a4e6801" not in text, relative_path
        assert "9ace9667" not in text, relative_path
        assert "git fetch --unshallow" not in text, relative_path

    detailed_contract = (ROOT / "docs/contributing/index.md").read_text(encoding="utf-8")
    assert "a4e6801" in detailed_contract
    assert "9ace9667" in detailed_contract
    assert "git fetch --unshallow" in detailed_contract


@pytest.mark.parametrize(("run", "expected"), [
    (AUDIT_COMMAND, 1),
    (f"# {AUDIT_COMMAND}\n", 0),
    (f'echo "{AUDIT_COMMAND}"', 0),
    (f"printf '%s\\n' '{AUDIT_COMMAND}'", 0),
    (f'"{AUDIT_COMMAND}"', 0),
    (f"'{AUDIT_COMMAND}'", 0),
    (f'printf "%s" "{AUDIT_COMMAND} && {AUDIT_COMMAND}"', 0),
    ('"python" "scripts/docs/audit_pre_pages.py"', 1),
    (f"DOCS_MODE=full {AUDIT_COMMAND}", 1),
    (f"env DOCS_MODE=full {AUDIT_COMMAND}", 1),
    (f"command {AUDIT_COMMAND}", 1),
    (f"{AUDIT_COMMAND} # {AUDIT_COMMAND}", 1),
    (f'{AUDIT_COMMAND}\n# {AUDIT_COMMAND}\nprintf "%s" "{AUDIT_COMMAND}"', 1),
    ("python \\\n  scripts/docs/audit_pre_pages.py", 1),
    ("py\\\nthon scripts/docs/audit_pre_pages.py", 1),
    ("'py\\\nthon' scripts/docs/audit_pre_pages.py", 0),
    (f"{AUDIT_COMMAND} \\\n  --content-only", 1),
    (f"{AUDIT_COMMAND}\n{AUDIT_COMMAND}", 2),
    (f"{AUDIT_COMMAND}; {AUDIT_COMMAND}", 2),
    (f"{AUDIT_COMMAND} && {AUDIT_COMMAND}", 2),
    (f"{AUDIT_COMMAND} || {AUDIT_COMMAND}", 2),
    (f"{AUDIT_COMMAND} # mention {AUDIT_COMMAND}\n{AUDIT_COMMAND}", 2),
    (f"echo value#not-a-comment; {AUDIT_COMMAND}", 1),
    (AUDIT_COMMAND + ".backup", 0),
    (f"bash -c '{AUDIT_COMMAND}'", 1),
    (f"""sh -c 'printf "%s" "{AUDIT_COMMAND}"'""", 0),
])
def test_audit_invocation_counter_uses_shell_command_positions(run, expected):
    assert count_run_command_occurrences({"validate": [{"run": run}]}, AUDIT_COMMAND) == expected


def mutate_extra_run(tmp_path, workflow_name, job_name, run):
    for path in WORKFLOWS.glob("*.yml"):
        write_workflow(tmp_path / path.name, path.read_text())
    path = tmp_path / workflow_name
    data = yaml.safe_load(path.read_text())
    data["jobs"][job_name]["steps"].append({"name": "Review mutation", "run": run})
    write_workflow(path, yaml.safe_dump(data))


@pytest.mark.parametrize(("workflow", "job"), [
    ("docs-ci.yml", "validate"), ("pages.yml", "build"), ("oryx-python-build-test.yml", "oryx-build"),
])
@pytest.mark.parametrize("mention", [
    f"# {AUDIT_COMMAND}",
    f'echo "{AUDIT_COMMAND}"',
    f"printf '%s\\n' '{AUDIT_COMMAND}'",
    f'"{AUDIT_COMMAND}"',
    f'echo before\n# {AUDIT_COMMAND}\nprintf "%s" "{AUDIT_COMMAND}"',
])
def test_historical_audit_workflows_allow_comment_and_output_mentions(tmp_path, workflow, job, mention):
    mutate_extra_run(tmp_path, workflow, job, mention)
    assert_pre_pages_audit_runs_after_search_validation(tmp_path)


@pytest.mark.parametrize(("workflow", "job"), [("docs-ci.yml", "validate"), ("pages.yml", "build")])
@pytest.mark.parametrize("second", [
    f"echo before\n{AUDIT_COMMAND}",
    f"echo before; {AUDIT_COMMAND}",
    f"echo before && {AUDIT_COMMAND}",
    f"echo before || {AUDIT_COMMAND}",
    "echo before && \\\npython \\\n scripts/docs/audit_pre_pages.py",
    '"python" "scripts/docs/audit_pre_pages.py"',
])
def test_historical_audit_workflows_reject_second_actual_shell_invocation(tmp_path, workflow, job, second):
    mutate_extra_run(tmp_path, workflow, job, second)
    with pytest.raises(AssertionError):
        assert_pre_pages_audit_runs_after_search_validation(tmp_path)


@pytest.mark.parametrize("run", [
    f'echo "$({AUDIT_COMMAND})"', f"echo `{AUDIT_COMMAND}`",
])
def test_dynamic_command_substitution_is_not_silently_counted_as_a_mention(run):
    with pytest.raises(ValueError, match="command substitution"):
        count_run_command_occurrences({"validate": [{"run": run}]}, AUDIT_COMMAND)
