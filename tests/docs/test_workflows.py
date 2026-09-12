from __future__ import annotations

import copy
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]


class GitHubLoader(yaml.SafeLoader):
    pass


GitHubLoader.yaml_implicit_resolvers = copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
for first_character, resolvers in list(GitHubLoader.yaml_implicit_resolvers.items()):
    GitHubLoader.yaml_implicit_resolvers[first_character] = [
        (tag, regexp)
        for tag, regexp in resolvers
        if tag != "tag:yaml.org,2002:bool"
    ]


def load_workflow(name: str) -> dict:
    path = ROOT / ".github" / "workflows" / name
    return yaml.load(path.read_text(encoding="utf-8"), Loader=GitHubLoader)


def commands(workflow: dict) -> list[str]:
    return [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "run" in step
    ]


def uses(workflow: dict) -> list[str]:
    return [
        step["uses"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "uses" in step
    ]


def test_docs_ci_is_read_only_and_runs_every_document_check() -> None:
    workflow = load_workflow("docs-ci.yml")

    assert "pull_request" in workflow["on"]
    assert workflow["permissions"] == {"contents": "read"}
    assert any(action.startswith("actions/checkout@") for action in uses(workflow))
    setup = next(
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/setup-python@")
    )
    assert setup["with"]["python-version"] == "3.13"

    script = "\n".join(commands(workflow))
    for required in (
        "pip install -r requirements-docs.txt",
        "python -m pytest tests/docs -q",
        "python scripts/docs/validate_metadata.py",
        "python scripts/docs/validate_sources.py",
        "python scripts/docs/validate_links.py",
        "python scripts/docs/validate_public_safety.py",
        "mkdocs build --strict",
        "python scripts/docs/validate_search_index.py",
    ):
        assert required in script
    assert script.index("mkdocs build --strict") < script.index(
        "python scripts/docs/validate_search_index.py"
    )


def test_pages_builds_on_main_and_deploys_an_artifact() -> None:
    workflow = load_workflow("pages.yml")

    assert workflow["on"]["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["deploy"]["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }
    assert workflow["concurrency"]["group"] == "pages"
    assert workflow["concurrency"]["cancel-in-progress"] == "false"

    actions = uses(workflow)
    for required in (
        "actions/configure-pages@v5",
        "actions/upload-pages-artifact@v4",
        "actions/deploy-pages@v4",
    ):
        assert required in actions
    upload = next(
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("uses") == "actions/upload-pages-artifact@v4"
    )
    assert upload["with"]["path"] == "site"
    deploy = workflow["jobs"]["deploy"]
    assert deploy["environment"]["name"] == "github-pages"
    assert deploy["needs"] == "build"
    script = "\n".join(commands(workflow))
    assert script.index("mkdocs build --strict") < script.index(
        "python scripts/docs/validate_search_index.py"
    )


def test_oryx_workflow_tracks_the_migrated_sample_path() -> None:
    workflow = load_workflow("oryx-python-build-test.yml")

    sample_path = "samples/app-service/oryx-test"
    assert f"{sample_path}/**" in workflow["on"]["push"]["paths"]
    script = "\n".join(commands(workflow))
    assert f"${{{{ github.workspace }}}}/{sample_path}:/app" in script
    assert f"./{sample_path}/" in script


def test_workflows_never_write_a_gh_pages_branch() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / ".github" / "workflows").glob("*.yml")
    )

    assert "contents: write" not in text
    assert "gh-pages" not in text


def test_pull_request_template_covers_public_document_contract() -> None:
    text = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")

    for phrase in (
        "문서 유형",
        "front matter",
        "Microsoft Learn MCP",
        "공개 안전성",
        "mkdocs build --strict",
    ):
        assert phrase in text


def test_document_dependencies_pin_mkdocs_core() -> None:
    requirements = (ROOT / "requirements-docs.txt").read_text(encoding="utf-8").splitlines()

    assert "mkdocs==1.6.1" in requirements
