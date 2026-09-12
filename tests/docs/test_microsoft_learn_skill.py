from __future__ import annotations

import json
from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).parents[2]
SKILL = ROOT / ".github" / "skills" / "verify-with-microsoft-learn" / "SKILL.md"


def split_skill() -> tuple[dict, str]:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, front_matter, body = text.split("---", 2)
    return yaml.safe_load(front_matter), body


def test_workspace_mcp_registers_official_learn_endpoint() -> None:
    config = json.loads((ROOT / ".vscode" / "mcp.json").read_text(encoding="utf-8"))

    assert config == {
        "servers": {
            "microsoft.docs.mcp": {
                "type": "http",
                "url": "https://learn.microsoft.com/api/mcp",
            }
        }
    }


def test_skill_front_matter_is_discoverable_and_minimal() -> None:
    metadata, _ = split_skill()

    assert metadata == {
        "name": "verify-with-microsoft-learn",
        "description": (
            "Use when creating, revising, or reviewing public technical documentation "
            "that contains Microsoft or Azure product claims."
        ),
    }


def test_skill_requires_complete_semantic_verification_workflow() -> None:
    _, body = split_skill()
    required_phrases = [
        "tools/list",
        "Search Microsoft Learn",
        "Fetch every selected article in full",
        "Compare each claim",
        "official_sources",
        "sources_checked_at",
        "verification_status",
        "kubernetes.io",
        "cncf.io",
        "needs-review",
    ]

    for phrase in required_phrases:
        assert phrase in body


def test_repository_skill_is_not_ignored_by_git() -> None:
    completed = subprocess.run(
        ["git", "check-ignore", "-q", SKILL.relative_to(ROOT).as_posix()],
        cwd=ROOT,
        check=False,
    )

    assert completed.returncode == 1
