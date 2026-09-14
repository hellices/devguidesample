from pathlib import Path
import os
import re
import shutil
import subprocess

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
import material
import pytest

from scripts.docs import hooks


def theme_environment():
    return Environment(loader=ChoiceLoader([
        DictLoader({"authored.html": '<a href="javascript:void(0)">Authored input must stay auditable</a>'}),
        FileSystemLoader(str(Path(material.__file__).parent / "templates")),
    ]))


def apply_environment_hook(env):
    config = {"theme": {"name": "material", "features": ["search.share", "search.highlight"]}}
    handler = getattr(hooks, "on_env", lambda environment, **kwargs: environment)
    result = handler(env, config=config, files=[])
    assert config["theme"]["features"] == ["search.share", "search.highlight"]
    return result


def test_installed_material_share_initializer_is_a_nonexecutable_anchor():
    env = apply_environment_hook(theme_environment())
    source = env.loader.get_source(env, "partials/search.html")[0]
    share = re.search(r'<a\b[^>]*data-md-component="search-share"[^>]*>', source)
    assert share is not None
    assert 'href="#"' in share[0]
    assert "data-clipboard" in share[0] and 'tabindex="-1"' in share[0]
    assert "javascript:" not in share[0]


def test_material_template_adaptation_does_not_sanitize_authored_urls():
    env = apply_environment_hook(theme_environment())
    assert env.get_template("authored.html").render() == (
        '<a href="javascript:void(0)">Authored input must stay auditable</a>'
    )


def test_material_node_contract_does_not_require_a_prior_root_build(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable")
    root = Path(__file__).parents[2]
    for relative in (
        "tests/docs/explore-material.test.cjs", "tests/docs/explore-fixture.cjs",
        "docs/assets/javascripts/explore.js",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
    source_map = next((Path(material.__file__).parent / "templates/assets/javascripts").glob("bundle*.js.map"))
    env = {**os.environ, "MATERIAL_SOURCE_MAP": str(source_map)}
    env.pop("EXPLORE_FIXTURE", None)
    result = subprocess.run(
        [node, "--test", str(tmp_path / "tests/docs/explore-material.test.cjs")],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
