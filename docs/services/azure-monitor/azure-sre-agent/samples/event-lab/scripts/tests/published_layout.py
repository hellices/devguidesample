"""Canonical repository paths for the SRE lab's published documentation."""

from __future__ import annotations

from functools import cache
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).parents[8]
LAB_ROOT = Path(__file__).parents[2]
DOCS_ROOT = REPO_ROOT / "docs"
TOPIC_ROOT = DOCS_ROOT / "services" / "azure-monitor" / "azure-sre-agent"

README = TOPIC_ROOT / "event-lab" / "index.md"
GUIDE_PATHS = {
    "01-agent-setup.md": TOPIC_ROOT / "setup" / "index.md",
    "02-scenario-s1.md": TOPIC_ROOT / "scenario-http-500" / "index.md",
    "03-scenario-s2.md": TOPIC_ROOT / "scenario-latency" / "index.md",
    "04-scenario-s3.md": TOPIC_ROOT / "scenario-blob-permission" / "index.md",
    "05-results.md": TOPIC_ROOT / "results" / "index.md",
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
RUNBOOK = TOPIC_ROOT / "incident-runbook" / "index.md"
DYNAMIC_THRESHOLDS = TOPIC_ROOT / "dynamic-thresholds" / "index.md"
VALIDATION_RESULTS = TOPIC_ROOT / "validation-results" / "index.md"
BRIEFING = TOPIC_ROOT / "index.md"
OFFICIAL_ASSETS = LAB_ROOT / "assets" / "official"


@cache
def resolve_published_file(path: Path) -> Path:
    """Resolve a virtual page asset through the repository's validated catalog."""
    from scripts.docs.content import load_taxonomy
    from scripts.docs.topics import build_topic_catalog

    if path.is_file():
        return path
    catalog = build_topic_catalog(DOCS_ROOT, load_taxonomy(REPO_ROOT / "docs-taxonomy.yml"))
    relative = PurePosixPath(path.resolve().relative_to(DOCS_ROOT).as_posix())
    asset = catalog.published_assets.get(relative)
    return DOCS_ROOT / asset.source if asset is not None else path
