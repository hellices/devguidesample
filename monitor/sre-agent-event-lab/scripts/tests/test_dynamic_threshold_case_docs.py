import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[4]
LAB_ROOT = REPO_ROOT / "monitor" / "sre-agent-event-lab"
GUIDE = LAB_ROOT / "dynamic-thresholds.md"
README = LAB_ROOT / "README.md"
BRIEF = REPO_ROOT / "monitor" / "azure-monitor-dynamic-thresholds-brief.md"
AZURE_SRE_AGENT = REPO_ROOT / "monitor" / "azure-sre-agent.md"
GUIDE_CHART = "assets/official/dynamic-threshold-preview-chart.png"
BRIEF_CHART = "sre-agent-event-lab/assets/official/dynamic-threshold-preview-chart.png"
OFFICIAL_SOURCE = (
    "https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-dynamic-thresholds"
)
EXIT_COMMAND_RE = re.compile(
    r"(?m)(?:^\s*exit(?:\s|;|$)|(?:\|\||&&|;)\s*exit(?:\s|;|$))"
)


def section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def rendered_image_targets(text: str) -> list[str]:
    markdown_targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    html_targets = re.findall(r"<img[^>]*\ssrc=[\"']([^\"']+)[\"']", text)
    return markdown_targets + html_targets


def bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, re.DOTALL)


def contains_exit_command(text: str) -> bool:
    return bool(EXIT_COMMAND_RE.search(text))


def test_case_is_explicitly_multi_day_and_does_not_promise_day_one_alerts():
    text = GUIDE.read_text()

    assert "Phase 1 — 당일" in text
    assert "Phase 2 — 3일 이후" in text
    assert "3일" in text
    assert "30 samples" in text
    assert "3주" in text
    assert "당일에는 alert 발화를 기대하지 않습니다" in text


def test_case_phase_two_is_independently_resumable():
    phase_two = section(GUIDE.read_text(), "## Phase 2 — 3일 이후: learned band와 anomaly 검증")

    assert "cd monitor/sre-agent-event-lab" in phase_two
    assert "source ./scripts/lab-env.sh" in phase_two
    assert phase_two.index("cd monitor/sre-agent-event-lab") < phase_two.index(
        "source ./scripts/lab-env.sh"
    )


def test_case_reuses_s2_readiness_and_recovery_patterns():
    phase_two = section(GUIDE.read_text(), "## Phase 2 — 3일 이후: learned band와 anomaly 검증")

    assert "/api/orders" in phase_two
    assert "P95DurationMs=percentile(DurationMs, 95)" in phase_two
    assert "OLD_REVISION" in phase_two
    assert "NEW_REVISION" in phase_two
    assert "healthState" in phase_two
    assert "active" in phase_two
    assert "Healthy" in phase_two
    assert "INJECTED=0" in phase_two
    assert "&& INJECTED=1" in phase_two
    assert "if (( INJECTED )); then" in phase_two
    assert "ORDER_DELAY_MS=4000" in phase_two
    assert "ORDER_DELAY_MS=0" in phase_two
    assert "scripts/loadgen.py" in phase_two
    assert "trap restore_delay EXIT INT TERM" in phase_two
    assert '"https://${APP_FQDN}/api/orders"' in phase_two
    assert "CONTAINER_APP_FQDN" not in phase_two
    assert "복구 실패" in phase_two
    assert (
        "curl -s --max-time 15 -o /dev/null -w '%{time_total}s %{http_code}\\n' "
        '"https://${APP_FQDN}/api/orders"'
    ) in phase_two


def test_case_phase_two_never_uses_exit_in_pasted_bash_blocks():
    phase_two = section(GUIDE.read_text(), "## Phase 2 — 3일 이후: learned band와 anomaly 검증")

    for block in bash_blocks(phase_two):
        assert not contains_exit_command(block)


@pytest.mark.parametrize(
    "snippet",
    [
        "exit 1",
        "  exit 1",
        "cmd || exit 1",
        "cmd ; exit 1",
    ],
)
def test_case_phase_two_exit_detector_catches_inline_exit_forms(snippet):
    assert contains_exit_command(snippet)


def test_case_phase_two_explains_why_it_only_checks_state_before_the_comparison_window():
    phase_two = section(GUIDE.read_text(), "## Phase 2 — 3일 이후: learned band와 anomaly 검증")

    assert "begin-run" in phase_two
    assert "S2 점수와 evidence 상태를 덮어쓸 수 있는" in phase_two
    assert "scenario state만 먼저 확인합니다" in phase_two
    assert "약 20분 동안" in phase_two
    assert "다른 시나리오를" in phase_two
    assert "시작하지 마세요" in phase_two


def test_case_phase_two_keeps_revision_state_local_and_marks_restore_complete():
    phase_two = section(GUIDE.read_text(), "## Phase 2 — 3일 이후: learned band와 anomaly 검증")

    assert 'local NEW_REVISION=""' in phase_two
    assert 'local STATE=""' in phase_two

    success_probe = (
        "curl -s --max-time 15 -o /dev/null -w '%{time_total}s %{http_code}\\n' "
        '"https://${APP_FQDN}/api/orders"'
    )
    restore_tail = phase_two[phase_two.index(success_probe) :]
    assert "INJECTED=0" in restore_tail


def test_case_phase_two_fails_loud_when_baseline_revision_lookups_fail():
    phase_two = section(GUIDE.read_text(), "## Phase 2 — 3일 이후: learned band와 anomaly 검증")

    assert "주입 준비 실패: 기존 revision 이름을 읽지 못했습니다." in phase_two
    assert "주입 준비 실패: 기존 revision 이름이 비어 있습니다." in phase_two
    assert "복구 준비 실패: 현재 revision 이름을 읽지 못했습니다." in phase_two
    assert "복구 준비 실패: 현재 revision 이름이 비어 있습니다." in phase_two


def test_case_uses_exported_lab_env_names_instead_of_raw_azd_lookups():
    text = GUIDE.read_text()

    assert "BASELINE_WEB_TEST_NAME" in text
    assert "DYNAMIC_THRESHOLD_ALERT_NAME" in text
    assert "azd env get-value" not in text


def test_case_documents_state_gate_and_static_s2_investigation_warning():
    phase_two = section(GUIDE.read_text(), "## Phase 2 — 3일 이후: learned band와 anomaly 검증")

    assert "evidence/state.json" in phase_two
    assert "lab_state.py show" in phase_two
    assert "running" in phase_two
    assert "failed" in phase_two
    assert "alert-sre-lab-s2-latency" in phase_two
    assert "Azure SRE Agent" in phase_two


def test_case_counts_learning_samples_from_the_binned_signal():
    text = GUIDE.read_text()

    assert "| summarize P95DurationMs=percentile(DurationMs, 95) by bin(TimeGenerated, 5m)" in text
    assert "| summarize Samples=count(), FirstSample=min(TimeGenerated), LastSample=max(TimeGenerated)" in text
    assert "azd up" in text
    assert "학습이 다시 시작" in text


def test_case_keeps_the_dynamic_rule_in_shadow_mode():
    text = GUIDE.read_text()

    assert "Action Group을 연결하지 않은 shadow mode" in text
    assert "DYNAMIC_THRESHOLD_ALERT_NAME" in text
    assert "BASELINE_WEB_TEST_NAME" in text
    assert "1분 evaluation을 지원하지 않습니다" in text
    assert "겹치는 20분 window" in text


def test_case_uses_local_official_chart_with_source_attribution():
    guide_text = GUIDE.read_text()
    brief_text = BRIEF.read_text()

    assert rendered_image_targets(guide_text) == [GUIDE_CHART]
    assert rendered_image_targets(brief_text) == [BRIEF_CHART]
    assert f"]({GUIDE_CHART})" in guide_text
    assert f"]({BRIEF_CHART})" in brief_text
    assert "> 출처:" in guide_text
    assert "> Source:" in brief_text
    assert OFFICIAL_SOURCE in guide_text
    assert OFFICIAL_SOURCE in brief_text
    assert (LAB_ROOT / "assets" / "official" / "dynamic-threshold-preview-chart.png").is_file()
    assert "```mermaid" in guide_text


def test_case_and_brief_link_to_each_other_and_sre_agent_names_the_hands_on_case():
    relative_case = "sre-agent-event-lab/dynamic-thresholds.md"
    concept_link = "[Dynamic Thresholds 개념 정리](../azure-monitor-dynamic-thresholds-brief.md)"
    sre_agent_text = AZURE_SRE_AGENT.read_text()

    assert relative_case in BRIEF.read_text()
    assert concept_link in GUIDE.read_text()
    assert "[dynamic-thresholds.md](dynamic-thresholds.md)" in README.read_text()
    assert "(sre-agent-event-lab/dynamic-thresholds.md)" in sre_agent_text
    assert "Dynamic Thresholds" in sre_agent_text
    assert "실습" in sre_agent_text


def test_case_and_brief_use_locale_less_learn_links_and_reconcile_preview_wording():
    guide_text = GUIDE.read_text()
    brief_text = BRIEF.read_text()

    assert "https://learn.microsoft.com/en-us/azure/" not in guide_text
    assert "https://learn.microsoft.com/en-us/azure/" not in brief_text
    assert "ARM/Bicep" in brief_text
    assert "shadow mode" in brief_text
    assert "Preview Chart" in brief_text


def test_readme_names_the_additional_billable_resources():
    text = README.read_text()

    assert "5분 주기 Dynamic Threshold 로그 검색 경고 규칙 1개" in text
    assert "Standard availability test 1개" in text
