from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
AUDIT_COMMAND = "python scripts/docs/audit_pre_pages.py"
AUDIT_PATH = "scripts/docs/audit_pre_pages.py"
AUDIT_REFERENCE = re.compile(
    rf"(?<![\w./-])(?:\./)?{re.escape(AUDIT_PATH)}(?![\w./-])"
)
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


def has_literal_audit_reference(run: str) -> bool:
    return bool(AUDIT_REFERENCE.search(run))


def count_run_blocks_with_audit_reference(
    jobs: dict[str, list[dict[str, object]]],
) -> int:
    references = 0
    for steps in jobs.values():
        for step in steps:
            run = step.get("run")
            if isinstance(run, str) and has_literal_audit_reference(run):
                references += 1
    return references


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
        audit_run = audit_step.get("run")
        assert isinstance(audit_run, str), workflow_name
        assert audit_run.strip() == AUDIT_COMMAND, workflow_name
        assert count_run_blocks_with_audit_reference(jobs) == 1, workflow_name

    assert count_run_blocks_with_audit_reference(
        jobs_by_workflow["oryx-python-build-test.yml"],
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
    ("python ./scripts/docs/audit_pre_pages.py", 1),
    (f"# {AUDIT_PATH}\n", 1),
    (f'printf "%s\\n" "{AUDIT_PATH}"', 1),
    (f'AUDIT_RESULT="$(python {AUDIT_PATH})"', 1),
    (f"echo before;python {AUDIT_PATH}", 1),
    (f"if true; then python {AUDIT_PATH}; fi", 1),
    (f"echo before && {{ python {AUDIT_PATH}; }}", 1),
    (f"if python {AUDIT_PATH}; then :; fi", 1),
    (f"(python {AUDIT_PATH})", 1),
    (f"sh -c 'python {AUDIT_PATH}'", 1),
    (f"echo `{AUDIT_COMMAND}`", 1),
    (f'echo "$({AUDIT_COMMAND})"', 1),
    (f"echo {AUDIT_PATH}.backup", 0),
    (f"echo {AUDIT_PATH}c", 0),
    (f"echo ./scripts/docs/audit_pre_pages.py.backup", 0),
])
def test_literal_audit_reference_matcher_respects_boundaries(run, expected):
    assert int(has_literal_audit_reference(run)) == expected


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
@pytest.mark.parametrize("second", [
    f"# {AUDIT_PATH}",
    f'printf "%s\\n" "{AUDIT_PATH}"',
    f'AUDIT_RESULT="$(python {AUDIT_PATH})"',
    f"echo before;python {AUDIT_PATH}",
    f"if true; then python {AUDIT_PATH}; fi",
    f"echo before && {{ python {AUDIT_PATH}; }}",
    f"if python {AUDIT_PATH}; then :; fi",
    f"(python {AUDIT_PATH})",
    f"sh -c 'python {AUDIT_PATH}'",
    f"echo `{AUDIT_COMMAND}`",
    f'echo "$({AUDIT_COMMAND})"',
])
def test_historical_audit_workflows_reject_extra_literal_audit_references(tmp_path, workflow, job, second):
    mutate_extra_run(tmp_path, workflow, job, second)
    with pytest.raises(AssertionError):
        assert_pre_pages_audit_runs_after_search_validation(tmp_path)


@pytest.mark.parametrize("suffix", [
    f"echo {AUDIT_PATH}.backup",
    f"echo {AUDIT_PATH}c",
    f"echo ./scripts/docs/audit_pre_pages.py.backup",
])
def test_historical_audit_workflows_ignore_suffix_nonmatches(tmp_path, suffix):
    mutate_extra_run(tmp_path, "docs-ci.yml", "validate", suffix)
    assert_pre_pages_audit_runs_after_search_validation(tmp_path)


@pytest.mark.parametrize(("workflow_name", "job_name"), [
    ("docs-ci.yml", "validate"),
    ("pages.yml", "build"),
])
def test_historical_audit_workflows_reject_dot_slash_dedicated_step(tmp_path, workflow_name, job_name):
    for path in WORKFLOWS.glob("*.yml"):
        write_workflow(tmp_path / path.name, path.read_text())
    path = tmp_path / workflow_name
    data = yaml.safe_load(path.read_text())
    for step in data["jobs"][job_name]["steps"]:
        if step.get("name") == "Audit pre-Pages content preservation":
            step["run"] = "python ./scripts/docs/audit_pre_pages.py"
            break
    write_workflow(path, yaml.safe_dump(data))

    with pytest.raises(AssertionError):
        assert_pre_pages_audit_runs_after_search_validation(tmp_path)


def test_run_block_reference_counter_counts_blocks_not_mentions() -> None:
    jobs = {
        "validate": [
            {"run": AUDIT_COMMAND},
            {"run": f"# {AUDIT_PATH}\nprintf '%s\\n' '{AUDIT_PATH}'"},
            {"run": f"python ./{AUDIT_PATH}"},
        ],
        "other": [
            {"run": f"echo {AUDIT_PATH}.backup"},
        ],
    }

    assert count_run_blocks_with_audit_reference(jobs) == 3
