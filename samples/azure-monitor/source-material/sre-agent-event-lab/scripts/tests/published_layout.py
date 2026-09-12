"""Canonical repository paths for the SRE lab's published documentation."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).parents[6]
LAB_ROOT = Path(__file__).parents[2]
DOCS_ROOT = REPO_ROOT / "docs"

README = DOCS_ROOT / "labs" / "azure-monitor" / "sre-agent-event-lab" / "index.md"
GUIDE_PATHS = {
    "01-agent-setup.md": (
        DOCS_ROOT / "labs" / "azure-monitor" / "sre-agent-event-lab-setup" / "index.md"
    ),
    "02-scenario-s1.md": (
        DOCS_ROOT / "labs" / "azure-monitor" / "sre-agent-scenario-http-500" / "index.md"
    ),
    "03-scenario-s2.md": (
        DOCS_ROOT / "labs" / "azure-monitor" / "sre-agent-scenario-latency" / "index.md"
    ),
    "04-scenario-s3.md": (
        DOCS_ROOT
        / "labs"
        / "azure-monitor"
        / "sre-agent-scenario-blob-permission"
        / "index.md"
    ),
    "05-results.md": (
        DOCS_ROOT / "labs" / "azure-monitor" / "sre-agent-results" / "index.md"
    ),
}


class PublishedGuideDirectory:
    """Provide the former directory interface over published page bundles."""

    def __truediv__(self, name: str | Path) -> Path:
        return GUIDE_PATHS[str(name)]

    def glob(self, pattern: str):
        if pattern != "*.md":
            return iter(())
        return iter(GUIDE_PATHS.values())


GUIDES = PublishedGuideDirectory()
RESULTS_GUIDE = GUIDE_PATHS["05-results.md"]
RUNBOOK = DOCS_ROOT / "guides" / "azure-monitor" / "sre-agent-incident-runbook" / "index.md"
DYNAMIC_THRESHOLDS = (
    DOCS_ROOT / "guides" / "azure-monitor" / "sre-agent-dynamic-thresholds" / "index.md"
)
VALIDATION_RESULTS = (
    DOCS_ROOT / "research" / "azure-monitor" / "sre-agent-validation-results" / "index.md"
)
BRIEFING = (
    DOCS_ROOT / "guides" / "azure-monitor" / "azure-sre-agent-overview" / "index.md"
)
OFFICIAL_ASSETS = LAB_ROOT / "assets" / "official"
