from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from scripts.docs import validate_public_safety


COMPLETED_PLAN_PATHS = (
    "project/plans/2026-09-12-public-github-pages.md",
    "project/specs/2026-09-12-public-github-pages-design.md",
)


def test_git_ignores_local_state_without_hiding_shared_inputs(tmp_path: Path) -> None:
    root = Path(__file__).parents[2]
    (tmp_path / ".gitignore").write_bytes((root / ".gitignore").read_bytes())
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    local_paths = {
        ".azure/deployment-plan.md",
        ".azure/validate-status.json",
        "samples/example/.azure/environment.json",
        ".claude/settings.local.json",
        ".DS_Store",
        "docs/guides/example/.DS_Store",
        "sim-env.json",
        "samples/example/sim-env.json",
        "samples/azure-monitor/source-material/sre-agent-event-lab/evidence/run.json",
        *COMPLETED_PLAN_PATHS,
    }
    shared_paths = {
        ".vscode/mcp.json",
        ".devcontainer/devcontainer.json",
        "samples/example/.env.example",
        "samples/example/infra/main.parameters.json",
        "samples/example/assets/captures/report.md",
        "project/specs/maintained-design.md",
    }
    result = subprocess.run(
        ["git", "-c", f"core.excludesFile={os.devnull}", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=tmp_path,
        input="\0".join(sorted(local_paths | shared_paths)) + "\0",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode in (0, 1), result.stderr
    assert set(filter(None, result.stdout.split("\0"))) == local_paths


def test_repository_does_not_track_local_artifacts() -> None:
    root = Path(__file__).parents[2]
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", ".azure", "**/.azure/**", *COMPLETED_PLAN_PATHS],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == "", result.stdout.split("\0")


def make_repository(tmp_path: Path) -> Path:
    (tmp_path / "docs" / "guides" / "aks" / "example").mkdir(parents=True)
    (tmp_path / "samples" / "aks" / "example").mkdir(parents=True)
    return tmp_path


def test_public_safety_accepts_placeholders_and_example_hosts(
    tmp_path: Path,
) -> None:
    root = make_repository(tmp_path)
    (root / "docs" / "guides" / "aks" / "example" / "index.md").write_text(
        """\
# Safe example

- Subscription: `<subscription-id>`
- Resource group: `rg-example-koreacentral`
- Agent thread: `<agent-thread-id>`
- Search: https://search-example-koreacentral-01.search.windows.net
- Registry: myregistry.azurecr.io/image:latest
- Container Apps: https://ca-api.example.koreacentral.azurecontainerapps.io
""",
        encoding="utf-8",
    )

    result = validate_public_safety.validate_repository(root)

    assert result.errors == []


def test_public_safety_scans_supported_text_and_detects_sensitive_values(
    tmp_path: Path,
) -> None:
    root = make_repository(tmp_path)
    docs = root / "docs" / "guides" / "aks" / "example"
    samples = root / "samples" / "aks" / "example"
    (docs / "index.md").write_text(
        """\
# Unsafe example

- Subscription: /subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-private
- Agent thread ID: 22222222-2222-4222-8222-222222222222
- Endpoint: https://service.203.0.113.10.nip.io
""",
        encoding="utf-8",
    )
    (samples / ".env.example").write_text(
        "SEARCH_ENDPOINT=https://private-search-123.search.windows.net\n",
        encoding="utf-8",
    )
    (samples / "Dockerfile").write_text(
        "ENV REGISTRY=private-registry.azurecr.io\n",
        encoding="utf-8",
    )
    (samples / "diagram.svg").write_text(
        "<svg><text>law-sre-event-lab-deadbeef</text></svg>\n",
        encoding="utf-8",
    )
    (samples / "incident.eml").write_text(
        "Agent thread ID: 33333333-3333-4333-8333-333333333333\n",
        encoding="utf-8",
    )
    (samples / "capture.png").write_bytes(b"\x89PNG\r\n")
    (samples / "settings.xml").write_bytes(b"<settings>\xff</settings>\n")

    result = validate_public_safety.validate_repository(root)

    assert result.file_count == 6
    assert any("Azure subscription ID" in error for error in result.errors)
    assert any("agent thread ID" in error for error in result.errors)
    assert any("IP-based nip.io endpoint" in error for error in result.errors)
    assert any("non-example Azure service hostname" in error for error in result.errors)
    assert any("deployment-specific lab suffix" in error for error in result.errors)
    assert any("file is not valid UTF-8" in error for error in result.errors)


def test_public_safety_fails_closed_for_missing_or_empty_scan_roots(
    tmp_path: Path,
) -> None:
    missing_samples = tmp_path / "missing-samples"
    (missing_samples / "docs").mkdir(parents=True)
    empty = tmp_path / "empty"
    (empty / "docs").mkdir(parents=True)
    (empty / "samples").mkdir()

    missing_result = validate_public_safety.validate_repository(missing_samples)
    empty_result = validate_public_safety.validate_repository(empty)

    assert any(
        "samples" in error and "missing" in error
        for error in missing_result.errors
    )
    assert any("no public text files" in error for error in missing_result.errors)
    assert any("no public text files" in error for error in empty_result.errors)


@pytest.mark.parametrize("name", [".env", ".ENV"])
def test_public_safety_scans_bare_dotenv_files(tmp_path: Path, name: str) -> None:
    root = make_repository(tmp_path)
    (root / "docs" / "guides" / "aks" / "example" / "index.md").write_text(
        "# Safe example\n", encoding="utf-8"
    )
    environment = root / "samples" / name
    environment.write_text(
        "SEARCH_ENDPOINT=https://private-search-123.search.windows.net\n",
        encoding="utf-8",
    )

    result = validate_public_safety.validate_repository(root)

    assert result.file_count == 2
    assert any(
        f"samples/{name}:1:" in error and "non-example Azure service hostname" in error
        for error in result.errors
    )

    environment.write_text(
        "SEARCH_ENDPOINT=https://search-example-koreacentral-01.search.windows.net\n",
        encoding="utf-8",
    )
    safe_result = validate_public_safety.validate_repository(root)
    assert safe_result.file_count == 2
    assert safe_result.errors == []
