from pathlib import Path


REPO_ROOT = Path(__file__).parents[4]
LAB_ROOT = REPO_ROOT / "monitor" / "sre-agent-event-lab"
GUIDE = LAB_ROOT / "dynamic-thresholds.md"
README = LAB_ROOT / "README.md"
BRIEF = REPO_ROOT / "monitor" / "azure-monitor-dynamic-thresholds-brief.md"
OFFICIAL_CHART = (
    "https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/media/"
    "alerts-dynamic-thresholds/threshold-picture-8bit.png"
)


def test_case_is_explicitly_multi_day_and_does_not_promise_day_one_alerts():
    text = GUIDE.read_text()

    assert "Phase 1 — 당일" in text
    assert "Phase 2 — 3일 이후" in text
    assert "3일" in text
    assert "30 samples" in text
    assert "3주" in text
    assert "당일에는 alert 발화를 기대하지 않습니다" in text


def test_case_reuses_s2_and_has_explicit_recovery():
    text = GUIDE.read_text()

    assert "/api/orders" in text
    assert "P95DurationMs=percentile(DurationMs, 95)" in text
    assert 'CONTAINER_APP_FQDN="${APP_FQDN}"' in text
    assert "ORDER_DELAY_MS=4000" in text
    assert "ORDER_DELAY_MS=0" in text
    assert "scripts/loadgen.py" in text
    assert "trap restore_delay EXIT INT TERM" in text


def test_case_counts_learning_samples_from_the_binned_signal():
    text = GUIDE.read_text()

    assert "| summarize P95DurationMs=percentile(DurationMs, 95) by bin(TimeGenerated, 5m)" in text
    assert "| summarize Samples=count(), FirstSample=min(TimeGenerated), LastSample=max(TimeGenerated)" in text


def test_case_keeps_the_dynamic_rule_in_shadow_mode():
    text = GUIDE.read_text()

    assert "Action Group을 연결하지 않은 shadow mode" in text
    assert "AZURE_DYNAMIC_THRESHOLD_ALERT_NAME" in text
    assert "AZURE_BASELINE_WEB_TEST_NAME" in text


def test_case_uses_and_attributes_the_official_chart():
    text = GUIDE.read_text()

    assert OFFICIAL_CHART in text
    assert "Source:" in text
    assert "alerts-dynamic-thresholds" in text
    assert "```mermaid" in text


def test_customer_brief_and_lab_readme_link_to_the_case():
    relative_case = "sre-agent-event-lab/dynamic-thresholds.md"

    assert relative_case in BRIEF.read_text()
    assert "[dynamic-thresholds.md](dynamic-thresholds.md)" in README.read_text()


def test_readme_names_the_additional_billable_resources():
    text = README.read_text()

    assert "5분 주기 Dynamic Threshold 로그 검색 경고 규칙 1개" in text
    assert "Standard availability test 1개" in text
