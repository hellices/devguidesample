from pathlib import Path

import yaml


LAB_ROOT = Path(__file__).parents[1]
REPO_ROOT = Path(__file__).parents[7]
TAXONOMY = REPO_ROOT / "docs-taxonomy.yml"


def test_taxonomy_declares_event_hubs_and_victoriametrics():
    data = yaml.safe_load(TAXONOMY.read_text())

    assert data["services"]["azure-event-hubs"] == "Azure Event Hubs"
    assert data["technologies"]["victoriametrics"] == "VictoriaMetrics"


def test_sample_manifest_is_runnable_and_referenced_by_both_pages():
    manifest = yaml.safe_load((LAB_ROOT / "sample.yml").read_text())

    assert manifest == {
        "title": "Event Hubs OpenTelemetry VictoriaMetrics lab",
        "description": (
            "Deploys and verifies Event Hubs metrics, consumer lag, dual "
            "VictoriaMetrics ingestion paths, and an agent-built Grafana dashboard."
        ),
        "kind": "runnable",
        "used_by": ["index", "lab"],
    }
