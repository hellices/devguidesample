from __future__ import annotations

from pathlib import Path

from scripts.docs import validate_public_safety


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
