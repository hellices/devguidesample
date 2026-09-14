import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def test_sidebar_toggle_javascript_behavior_with_available_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable: parent browser verification is required")
    result = subprocess.run(
        [node, "--test", str(ROOT / "tests/docs/sidebar-toggle.test.cjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
