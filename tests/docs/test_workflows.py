from pathlib import Path
import re

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


def assert_required_action_versions(workflows_dir: Path = WORKFLOWS) -> None:
    references = action_references(workflows_dir)
    for path, action, version in references:
        if action in REQUIRED_ACTIONS:
            assert version == REQUIRED_ACTIONS[action], (path, action, version)
    assert set(REQUIRED_ACTIONS) <= {action for _, action, _ in references}


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


def test_pages_deploy_checks_legacy_urls_for_direct_pushes() -> None:
    steps = workflow_jobs()["pages.yml"]["build"]
    runs = [step.get("run") for step in steps]
    assert "python -m pytest tests/docs/test_legacy_urls.py -q" in runs
    assert runs.index("python -m pytest tests/docs/test_legacy_urls.py -q") < runs.index("mkdocs build --strict")
