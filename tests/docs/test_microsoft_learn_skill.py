from __future__ import annotations

import json
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).parents[2]
SKILL = ROOT / ".github" / "skills" / "verify-with-microsoft-learn" / "SKILL.md"


def split_skill() -> tuple[dict, str]:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, front_matter, body = text.split("---", 2)
    return yaml.safe_load(front_matter), body


def test_workspace_mcp_exposes_official_learn_server() -> None:
    config = json.loads((ROOT / ".vscode" / "mcp.json").read_text(encoding="utf-8"))

    assert len(config["servers"]) == 1
    name, server = next(iter(config["servers"].items()))
    assert re.fullmatch(r"[a-zA-Z0-9_-]+", name), (
        "MCP server names must be accepted by the Codex agent host"
    )
    assert server == {
        "type": "http",
        "url": "https://learn.microsoft.com/api/mcp",
    }


def test_skill_is_discoverable_and_requires_semantic_verification() -> None:
    metadata, body = split_skill()

    assert metadata == {
        "name": "verify-with-microsoft-learn",
        "description": (
            "Use when creating, revising, or reviewing public technical documentation "
            "that contains Microsoft or Azure product claims."
        ),
    }
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
