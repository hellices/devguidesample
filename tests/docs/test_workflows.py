from pathlib import Path
import re


ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
REQUIRED_ACTIONS = {
    "actions/checkout": "v7",
    "actions/setup-python": "v7",
    "actions/configure-pages": "v6",
    "actions/upload-pages-artifact": "v5",
    "actions/deploy-pages": "v5",
}


def action_references() -> list[tuple[Path, str, str]]:
    references = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for owner_repo, version in re.findall(
            r"^\s*uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([^\s#]+)",
            path.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        ):
            references.append((path, owner_repo, version))
    return references


def test_official_actions_use_required_node_24_majors() -> None:
    references = action_references()
    for path, action, version in references:
        if action in REQUIRED_ACTIONS:
            assert version == REQUIRED_ACTIONS[action], (path, action, version)
    assert set(REQUIRED_ACTIONS) <= {action for _, action, _ in references}


def test_historical_audit_workflows_checkout_full_history() -> None:
    for name in ("docs-ci.yml", "pages.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        checkout = text.split("actions/checkout@v7", 1)[1].split("\n\n", 1)[0]
        assert "fetch-depth: 0" in checkout
