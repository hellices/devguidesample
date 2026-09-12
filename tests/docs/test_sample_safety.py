from __future__ import annotations

import ast
from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).parents[2]
BENCH_ROOT = (
    ROOT
    / "samples"
    / "azure-ai-search"
    / "source-material"
    / "custom_vectorization"
    / "bench"
)


def module_assignments(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignments: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name):
            assignments[target.id] = ast.unparse(node.value)
    return assignments


def test_benchmark_requires_target_azure_resources_from_the_environment() -> None:
    assignments = module_assignments(BENCH_ROOT / "bench_runner.py")

    assert assignments["SEARCH_URL"] == "os.environ['SEARCH_URL']"
    assert assignments["STORAGE_ACCOUNT"] == "os.environ['STORAGE_ACCOUNT']"
    assert assignments["STORAGE_RG"] == "os.environ['STORAGE_RG']"


def test_benchmark_configmap_uses_explicit_resource_placeholders() -> None:
    config = next(
        yaml.safe_load_all(
            (BENCH_ROOT / "k8s" / "configmap.yaml").read_text(encoding="utf-8")
        )
    )

    assert config["data"] == {
        "SEARCH_URL": "https://<search-service-name>.search.windows.net",
        "VLLM_EMBED_URL": "http://vllm-embedding-svc:8081",
        "EMBED_SKILL_URI": "https://embed.example.com/api/embed",
        "STORAGE_ACCOUNT": "<storage-account-name>",
        "STORAGE_RG": "<storage-resource-group>",
        "BLOB_CONTAINER": "bench-docs",
        "EMBED_MODEL": "Qwen/Qwen3-Embedding-4B",
        "VECTOR_DIM": "2560",
        "STORAGE_RESOURCE_ID": (
            "/subscriptions/<subscription-id>/resourceGroups/"
            "<storage-resource-group>/providers/Microsoft.Storage/storageAccounts/"
            "<storage-account-name>"
        ),
    }


def test_sre_sample_and_current_lab_pages_use_the_relocated_paths() -> None:
    sample = (
        ROOT
        / "samples"
        / "azure-monitor"
        / "source-material"
        / "sre-agent-event-lab"
    )
    script_text = "\n".join(
        path.read_text(encoding="utf-8")
        for pattern in ("*.py", "*.sh")
        for path in (sample / "scripts").glob(pattern)
    )
    legacy_guides = (
        "guides/01-agent-setup.md",
        "guides/02-scenario-s1.md",
        "guides/03-scenario-s2.md",
        "guides/04-scenario-s3.md",
        "guides/05-results.md",
    )
    for legacy in legacy_guides:
        assert legacy not in script_text
    assert "cd monitor/sre-agent-event-lab" not in script_text

    expected_pages = (
        "docs/labs/azure-monitor/sre-agent-event-lab-setup/index.md",
        "docs/labs/azure-monitor/sre-agent-scenario-http-500/index.md",
        "docs/labs/azure-monitor/sre-agent-scenario-latency/index.md",
        "docs/labs/azure-monitor/sre-agent-scenario-blob-permission/index.md",
        "docs/labs/azure-monitor/sre-agent-results/index.md",
    )
    for page in expected_pages:
        assert page in script_text
        assert (ROOT / page).is_file()

    sample_path = "samples/azure-monitor/source-material/sre-agent-event-lab"
    for topic in (
        "sre-agent-event-lab",
        "sre-agent-event-lab-setup",
        "sre-agent-scenario-http-500",
        "sre-agent-scenario-latency",
        "sre-agent-scenario-blob-permission",
        "sre-agent-results",
    ):
        page = ROOT / "docs" / "labs" / "azure-monitor" / topic / "index.md"
        assert sample_path in page.read_text(encoding="utf-8"), page


def test_sre_shell_scripts_keep_executable_git_modes() -> None:
    prefix = "samples/azure-monitor/source-material/sre-agent-event-lab/scripts/"
    completed = subprocess.run(
        ["git", "ls-files", "--stage", f"{prefix}*.sh"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    entries = [line for line in completed.stdout.splitlines() if line]

    assert entries
    assert all(line.startswith("100755 ") for line in entries), entries
