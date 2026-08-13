"""Regression guards for personal/internal identifiers introduced by the
Azure SRE Agent Event Lab branch.

Scope is intentionally limited to files added or modified for this lab so
that pre-existing, unrelated history (e.g. the HDInsight Kafka lag test
docs) is left untouched.
"""
from pathlib import Path


REPO_ROOT = Path(__file__).parents[4]

SRE_LAB_TRACKED_FILES = (
    REPO_ROOT / ".azure" / "deployment-plan.md",
    REPO_ROOT / "monitor" / "sre-agent-event-lab" / "README.md",
    REPO_ROOT / "monitor" / "sre-agent-event-lab" / "scripts" / "common.sh",
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "reports"
    / "2026-08-12-azure-sre-agent-event-testing-results.md",
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-08-12-azure-sre-agent-event-testing-design.md",
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-08-12-azure-sre-agent-event-testing-execution.md",
)

FORBIDDEN_STRINGS = (
    "inhwanhwang",
    "ME-MngEnvMCAP310512-inhwanhwang-3",
)


def test_sre_lab_docs_do_not_contain_personal_identifier():
    for path in SRE_LAB_TRACKED_FILES:
        assert path.exists(), path
        text = path.read_text()
        for forbidden in FORBIDDEN_STRINGS:
            assert forbidden not in text, f"{forbidden!r} found in {path}"


def test_sre_lab_captures_do_not_expose_container_app_fqdn():
    captures_dir = (
        REPO_ROOT / "monitor" / "sre-agent-event-lab" / "assets" / "captures"
    )
    text_files = [
        *captures_dir.glob("**/*.md"),
        *captures_dir.glob("**/*.mmd"),
    ]
    assert text_files
    for path in text_files:
        text = path.read_text()
        assert ".azurecontainerapps.io" not in text, path
