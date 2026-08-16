"""Contract tests for the repository-wide dev container.

One container serves the whole repository. VS Code's "Reopen in Container"
and Codespaces both read `.devcontainer/devcontainer.json` by default, so a
configuration stored there works from any directory without the operator
picking anything. A configuration filed under a lab's own name does not:
Codespaces offers it as one choice among several, and VS Code ignores it.

These tests keep the container general as labs are added: it supplies the
shared Azure toolchain and nothing that names a particular lab, and the
tools it supplies stay in step with the install instructions someone
working outside a container follows.
"""
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).parents[4]
DEVCONTAINER_DIR = REPO_ROOT / ".devcontainer"
DEVCONTAINER = DEVCONTAINER_DIR / "devcontainer.json"
TOOLCHAIN_DOC = DEVCONTAINER_DIR / "README.md"

# The command names every lab in this repository expects on PATH. The
# container supplies them and the toolchain document explains how to get
# each one without a container.
REQUIRED_TOOLS = ("az", "azd", "gh", "python3", "uv", "jq", "curl")

# The dev container features that install the tools not already in the base
# image.
REQUIRED_FEATURES = ("azure-cli", "azure-dev/azd", "github-cli", "python")


def config():
    assert DEVCONTAINER.is_file(), (
        "VS Code and Codespaces read .devcontainer/devcontainer.json by "
        f"default; expected {DEVCONTAINER}"
    )
    return json.loads(DEVCONTAINER.read_text())


def test_the_container_is_the_repository_default():
    """Anywhere in the repository, with no configuration picker."""
    assert DEVCONTAINER.is_file(), (
        "VS Code and Codespaces read .devcontainer/devcontainer.json by "
        f"default; expected {DEVCONTAINER}"
    )
    assert config()["name"]


def test_there_is_exactly_one_container_configuration():
    """A second configuration brings the Codespaces picker back, and the
    default stops being the only answer to 'which container am I in'."""
    found = sorted(
        path.relative_to(REPO_ROOT)
        for path in DEVCONTAINER_DIR.rglob("devcontainer.json")
    )
    assert found == [Path(".devcontainer/devcontainer.json")], found


def test_the_container_names_no_individual_lab():
    """The moment the container knows one lab's path, it stops being the
    repository's container: every new lab has to edit it, and one lab's
    setup failure breaks container creation for everyone."""
    raw = DEVCONTAINER.read_text()
    labs = [
        azure_yaml.relative_to(REPO_ROOT).parent
        for azure_yaml in REPO_ROOT.rglob("azure.yaml")
        if not {".git", ".worktrees", ".venv", "node_modules"}
        & set(azure_yaml.relative_to(REPO_ROOT).parts)
    ]
    assert labs, "no lab found; the discovery rule is wrong"
    for lab in labs:
        assert str(lab) not in raw, lab
        assert lab.name not in raw, lab.name


def test_the_container_supplies_the_shared_toolchain():
    features = " ".join(config().get("features", {}))
    for required in REQUIRED_FEATURES:
        assert required in features, required
    assert "uv" in DEVCONTAINER.read_text(), (
        "labs install Python dependencies through uv only"
    )


def test_the_container_carries_no_credential_and_no_subscription():
    raw = DEVCONTAINER.read_text()
    assert not re.search(
        r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b", raw
    ), "a GUID here would pin every user to whoever authored the file"
    for forbidden in ("PASSWORD", "SECRET", "TOKEN", "_KEY", "CONNECTION_STRING"):
        assert forbidden not in raw.upper(), forbidden


def test_the_container_never_logs_in_for_the_user():
    """`az login` is interactive and account-specific."""
    raw = DEVCONTAINER.read_text()
    assert "az login" not in raw
    assert "azd auth login" not in raw


def test_one_document_owns_the_install_instructions():
    """Someone working outside a container needs the same tools. Keeping
    that list in one place is what stops each lab from carrying its own
    copy and drifting."""
    assert TOOLCHAIN_DOC.is_file(), TOOLCHAIN_DOC
    text = TOOLCHAIN_DOC.read_text()
    for tool in REQUIRED_TOOLS:
        assert tool in text, tool


def test_the_lab_points_at_that_document_instead_of_repeating_it():
    lab_readme = REPO_ROOT / "monitor" / "sre-agent-event-lab" / "README.md"
    assert ".devcontainer/README.md" in lab_readme.read_text(), (
        "the lab must link the shared toolchain document, not restate it"
    )
