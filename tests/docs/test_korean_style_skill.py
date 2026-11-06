"""Run the writing-korean-docs skill's checker tests with the docs test suite."""

from __future__ import annotations

import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[2] / ".github/skills/writing-korean-docs/scripts"


def test_korean_style_checker_unit_tests_pass() -> None:
    suite = unittest.defaultTestLoader.discover(str(SCRIPTS), top_level_dir=str(SCRIPTS))
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.testsRun > 0
    assert result.wasSuccessful(), [str(test) for test, _ in result.failures + result.errors]


def test_skill_files_exist() -> None:
    skill = SCRIPTS.parent
    assert (skill / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname: writing-korean-docs\n")
    assert (skill / "rewrite-examples.md").is_file()
    assert (SCRIPTS / "check_korean_style.py").is_file()
