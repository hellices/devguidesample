from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from scripts.docs import validate_public_safety


def make_repository(tmp_path: Path) -> Path:
    (tmp_path / "docs" / "guides" / "aks" / "example").mkdir(parents=True)
    (tmp_path / "samples" / "aks" / "example").mkdir(parents=True)
    return tmp_path


def test_public_safety_accepts_documented_placeholders_and_public_ids(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    (root / "docs" / "guides" / "aks" / "example" / "index.md").write_text(
        """\
# Safe example

- Subscription: `<subscription-id>`
- Resource group: `rg-example-koreacentral`
- Agent thread: `<agent-thread-id>`
- Azure Databricks application ID: `2ff814a6-3304-4ab8-85cb-cd0e6f879c1d`
- GitHub asset: https://github.com/user-attachments/assets/7e916a87-7199-4082-be02-19158c255bf6
- Search example: https://search-example-koreacentral-01.search.windows.net
- Registry example: acrexamplekrc01.azurecr.io/image:latest
- Container Apps example: https://ca-api.example.koreacentral.azurecontainerapps.io
- Generic registry example: myregistry.azurecr.io/image:latest
- Placeholder registry: <ACR_NAME>.azurecr.io/image:latest
""",
        encoding="utf-8",
    )

    result = validate_public_safety.validate_repository(root)

    assert result.errors == []


def test_public_safety_accepts_public_names_that_share_marker_words(
    tmp_path: Path,
) -> None:
    root = make_repository(tmp_path)
    (root / "docs" / "guides" / "aks" / "example" / "index.md").write_text(
        """\
# Public references

- Algorithm: `Rubicon`
- Example project: `AIPlayground`
- Upstream source: https://github.com/KRAFTON-Inc/example
""",
        encoding="utf-8",
    )

    result = validate_public_safety.validate_repository(root)

    assert result.errors == []


def test_public_safety_reports_environment_specific_identifiers(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    page = root / "docs" / "guides" / "aks" / "example" / "index.md"
    page.write_text(
        """\
# Unsafe example

- `/subscriptions/f752aff6-b20c-4973-b32b-0a60ba2c6764/resourceGroups/rg-rubicon-prod`
- Agent thread: `6dd0e640-d969-46cb-a976-7c81b66fcadc`
- Endpoint: `https://embed.20.249.162.81.nip.io`
- Customer resource group: `rg-krafton-kafka-dev-jpe`
- Internal search endpoint: `https://ais-aiplay-krc-01.search.windows.net`
- Internal storage account: `saidxtest44159`
- User-derived resource group: `rg-hellices-krc-01`
- Internal registry: `acrcustomvec01`
- Generated Container Apps domain: `icycliff-31a3d588`
- Production-like Cosmos host: `db-neu-prd-cosmos-northeurope`
- Search service: `onnuri-search-59018`
- Resource group: `aisearchtest`
- Registry name: `acrmemrayb219eb`
""",
        encoding="utf-8",
    )

    result = validate_public_safety.validate_repository(root)

    assert any("Azure subscription ID" in error for error in result.errors)
    assert any("environment-specific name" in error for error in result.errors)
    assert any("agent thread ID" in error for error in result.errors)
    assert any("IP-based nip.io endpoint" in error for error in result.errors)
    environment_errors = [
        error for error in result.errors if "environment-specific name" in error
    ]
    assert len(environment_errors) == 11


def test_public_safety_reports_non_example_azure_service_hostnames(
    tmp_path: Path,
) -> None:
    root = make_repository(tmp_path)
    page = root / "docs" / "guides" / "aks" / "example" / "index.md"
    page.write_text(
        """\
# Unsafe Azure endpoints

- Search: https://onnuri-search-59018.search.windows.net
- Registry: acrmemrayb219eb.azurecr.io/leaky-agent:v2
- Container Apps: https://ca-embedding.icycliff-31a3d588.koreacentral.azurecontainerapps.io
""",
        encoding="utf-8",
    )

    result = validate_public_safety.validate_repository(root)

    hostname_errors = [
        error for error in result.errors if "non-example Azure service hostname" in error
    ]
    assert len(hostname_errors) == 3


def test_public_safety_scans_samples_and_skips_binary_files(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    (root / "samples" / "aks" / "example" / "config.yaml").write_text(
        'resourceId: "/subscriptions/b219ebf4-b544-46b1-b7ce-9c9b25ea826c/resourceGroups/rg-example"\n',
        encoding="utf-8",
    )
    (root / "samples" / "aks" / "example" / "capture.png").write_bytes(b"\x89PNG\r\n")

    result = validate_public_safety.validate_repository(root)

    assert result.file_count == 1
    assert any("Azure subscription ID" in error for error in result.errors)


def test_public_safety_scans_compound_and_extensionless_text_files(
    tmp_path: Path,
) -> None:
    root = make_repository(tmp_path)
    sample = root / "samples" / "aks" / "example"
    (sample / ".env.example").write_text(
        "SEARCH_ENDPOINT=https://ais-aiplay-krc-01.search.windows.net\n",
        encoding="utf-8",
    )
    (sample / "Dockerfile").write_text(
        "ENV REGISTRY=acrcustomvec01.azurecr.io\n",
        encoding="utf-8",
    )
    (sample / "main.bicepparam").write_text(
        "param resourceGroupName = 'rg-rubicon-prod'\n",
        encoding="utf-8",
    )

    result = validate_public_safety.validate_repository(root)

    assert result.file_count == 3
    environment_errors = [
        error for error in result.errors if "environment-specific name" in error
    ]
    assert len(environment_errors) == 3


def test_public_safety_scans_saved_email_artifacts(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    (root / "samples" / "aks" / "example" / "incident.eml").write_text(
        "Agent thread ID: 6dd0e640-d969-46cb-a976-7c81b66fcadc\n",
        encoding="utf-8",
    )

    result = validate_public_safety.validate_repository(root)

    assert result.file_count == 1
    assert any("agent thread ID" in error for error in result.errors)


def test_public_safety_script_runs_outside_repository_cwd(tmp_path: Path) -> None:
    root = make_repository(tmp_path / "repository")
    (root / "docs" / "guides" / "aks" / "example" / "index.md").write_text(
        "# Safe\n\nSubscription: `<subscription-id>`\n",
        encoding="utf-8",
    )
    script = Path(__file__).parents[2] / "scripts" / "docs" / "validate_public_safety.py"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, str(script), "--repo-root", str(root)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
