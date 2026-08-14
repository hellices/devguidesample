"""Regression guards for personal/internal identifiers introduced by the
Azure SRE Agent Event Lab branch.

Scope is intentionally limited to files added or modified for this lab so
that pre-existing, unrelated history (e.g. the HDInsight Kafka lag test
docs) is left untouched.
"""
import re
from pathlib import Path


REPO_ROOT = Path(__file__).parents[4]

SRE_LAB_TRACKED_FILES = (
    REPO_ROOT / ".azure" / "deployment-plan.md",
    REPO_ROOT / "monitor" / "sre-agent-event-lab" / "README.md",
    REPO_ROOT / "monitor" / "sre-agent-event-lab" / "scripts" / "common.sh",
    REPO_ROOT / "monitor" / "sre-agent-event-lab" / "validation-results.md",
    REPO_ROOT / "monitor" / "sre-agent-event-lab" / "dynamic-thresholds.md",
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


def test_repository_does_not_ship_agent_workflow_docs():
    assert not (REPO_ROOT / "docs" / "superpowers").exists()


def test_sre_lab_docs_do_not_link_removed_workflow_paths():
    checked = [
        REPO_ROOT / "monitor" / "azure-sre-agent.md",
        REPO_ROOT / "monitor" / "sre-agent-event-lab" / "README.md",
        REPO_ROOT / ".azure" / "deployment-plan.md",
        *(REPO_ROOT / "monitor" / "sre-agent-event-lab" / "assets" / "notifications").glob("*.md"),
        *(REPO_ROOT / "monitor" / "sre-agent-event-lab" / "assets" / "notifications").glob("*.html"),
    ]

    for path in checked:
        assert path.exists(), path
        assert "docs/superpowers" not in path.read_text(), path


def test_briefing_relative_links_resolve():
    briefing = REPO_ROOT / "monitor" / "azure-sre-agent.md"
    targets = re.findall(r"\]\((?!https?://)([^)#]+)", briefing.read_text())

    assert targets
    for target in targets:
        assert (briefing.parent / target).resolve().exists(), target


def test_relocated_lab_docs_drop_internal_workflow_directives():
    for name in ("validation-results.md", "dynamic-thresholds.md"):
        content = (
            REPO_ROOT / "monitor" / "sre-agent-event-lab" / name
        ).read_text()
        for marker in ("승인된 설계", "보고서 반영", "검증 부록"):
            assert marker not in content, (name, marker)


# --- The real subscription ID belongs in exactly one file -------------------

LAB_ROOT = REPO_ROOT / "monitor" / "sre-agent-event-lab"
VALIDATION_RESULTS = LAB_ROOT / "validation-results.md"
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b"
)


def recorded_subscription_id():
    """The subscription the historical validation run used.

    `validation-results.md` is the record of one real run on one real
    subscription, so that ID legitimately appears there -- and nowhere
    else. Reading it from that file is what lets every other guard below
    forbid it without restating it.
    """
    header = VALIDATION_RESULTS.read_text().split("\n## ", 1)[0]
    found = UUID_PATTERN.findall(header)
    assert found, "validation-results.md no longer records a subscription ID"
    return found[0]


def test_no_test_source_restates_the_real_subscription_id():
    """A test that proves a file does not leak the subscription by writing
    the subscription into the test is self-defeating: the value is in the
    repository either way, and every copy is one more place to miss when it
    has to change. The guards state the *shape* they forbid instead, and
    the fixtures use obvious dummies.
    """
    subscription_id = recorded_subscription_id()
    test_sources = sorted(
        [
            *(LAB_ROOT / "scripts" / "tests").glob("*.py"),
            *(LAB_ROOT / "infra" / "tests").glob("*.py"),
            *(LAB_ROOT / "app" / "tests").glob("*.py"),
        ]
    )
    assert test_sources

    offenders = [
        str(path.relative_to(LAB_ROOT))
        for path in test_sources
        if subscription_id in path.read_text()
    ]

    assert offenders == [], (
        "test sources still hardcode the real validation subscription ID; "
        f"forbid the UUID shape instead: {offenders}"
    )


def test_test_fixtures_never_reuse_the_real_subscription_id():
    """The dummy IDs the harnesses inject must be provably not the real
    one, so a fixture can never accidentally target a live subscription."""
    subscription_id = recorded_subscription_id()
    from lab_script_harness import SUBSCRIPTION_ID as harness_subscription_id
    from test_common import REQUIRED_ENV

    dummies = (harness_subscription_id, REQUIRED_ENV["AZURE_SUBSCRIPTION_ID"])
    for dummy in dummies:
        assert UUID_PATTERN.fullmatch(dummy), dummy
        assert dummy != subscription_id
