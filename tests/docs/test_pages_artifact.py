import json
from pathlib import Path, PurePosixPath
import tarfile

from mkdocs.commands.build import build
from mkdocs.config import load_config
import yaml

from scripts.docs.content import load_taxonomy
from scripts.docs.topics import build_topic_catalog


ROOT = Path(__file__).parents[2]


def pages_artifact_filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    # GNU tar's --exclude=".[^/]*" in upload-pages-artifact@v5, at every depth.
    # Checking components also works on hosts whose BSD tar glob rules differ.
    if any(component.startswith(".") for component in PurePosixPath(member.name).parts):
        return None
    return member


def test_current_published_assets_survive_pages_artifact_hidden_exclusion(tmp_path: Path) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/pages.yml").read_text())
    assert any(
        step.get("uses") == "actions/upload-pages-artifact@v5"
        for step in workflow["jobs"]["build"]["steps"]
    )
    catalog = build_topic_catalog(ROOT / "docs", load_taxonomy(ROOT / "docs-taxonomy.yml"))
    assert catalog.published_assets
    site = tmp_path / "site"
    build(load_config(str(ROOT / "mkdocs.yml"), site_dir=str(site), strict=True))

    assert not (site / "superpowers").exists()
    search = json.loads(
        (site / "search" / "search_index.json").read_text(encoding="utf-8")
    )
    assert not any(
        entry["location"].startswith("superpowers/")
        for entry in search["docs"]
    )

    hidden_controls = [
        ".artifact-control",
        ".artifact-controls/file.txt",
        "services/.artifact-control",
        "services/artifact-controls/.private/file.txt",
        ".git/config",
        ".github/workflows/control.yml",
    ]
    for name in hidden_controls:
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"must not be packaged")

    archive = tmp_path / "artifact.tar"
    with tarfile.open(archive, "w") as artifact:
        artifact.add(site, arcname=".", filter=pages_artifact_filter)
    with tarfile.open(archive) as artifact:
        members = {
            PurePosixPath(member.name): member
            for member in artifact.getmembers()
            if member.isfile()
        }
        assert all(PurePosixPath(name) not in members for name in hidden_controls)
        assert not any("samples" in path.parts for path in members)
        assert not any(component.startswith(".") for path in members for component in path.parts)
        for target, asset in catalog.published_assets.items():
            assert all(not component.startswith(".") for component in target.parts)
            assert target in members, f"Pages packaging omitted declared target: {target}"
            source_bytes = (ROOT / "docs" / asset.source).read_bytes()
            assert (site / target).read_bytes() == source_bytes
            with artifact.extractfile(members[target]) as packaged:
                assert packaged.read() == source_bytes
