from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
REQUIRED_ACTIONS = {
    "actions/checkout": "v7",
    "actions/setup-python": "v7",
    "actions/configure-pages": "v6",
    "actions/upload-pages-artifact": "v5",
    "actions/deploy-pages": "v5",
}


def write_workflow(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def iter_job_steps(node: object) -> Iterator[dict[str, object]]:
    if isinstance(node, dict):
        steps = node.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict):
                    yield step
        for value in node.values():
            yield from iter_job_steps(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_job_steps(item)


def workflow_steps(workflows_dir: Path = WORKFLOWS) -> list[tuple[Path, dict[str, object]]]:
    steps = []
    for path in sorted(workflows_dir.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(workflow, dict):
            continue
        jobs = workflow.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job in jobs.values():
            for step in iter_job_steps(job):
                steps.append((path, step))
    return steps


def action_references(workflows_dir: Path = WORKFLOWS) -> list[tuple[Path, str, str]]:
    references = []
    for path, step in workflow_steps(workflows_dir):
        uses = step.get("uses")
        if isinstance(uses, str) and "@" in uses:
            owner_repo, version = uses.rsplit("@", 1)
            references.append((path, owner_repo, version))
    return references


def checkout_inputs_by_workflow(
    workflows_dir: Path = WORKFLOWS,
) -> dict[str, list[dict[str, object] | None]]:
    checkout_inputs: dict[str, list[dict[str, object] | None]] = {}
    for path, step in workflow_steps(workflows_dir):
        if step.get("uses") != "actions/checkout@v7":
            continue
        with_block = step.get("with")
        parsed_with = with_block if isinstance(with_block, dict) else None
        checkout_inputs.setdefault(path.name, []).append(parsed_with)
    return checkout_inputs


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


def test_historical_audit_workflows_checkout_full_history() -> None:
    assert_checkout_history_contract()
