"""Behavioural tests for `baseline.sh`.

`baseline.sh` is the one script that has to decide "did my traffic actually
reach Application Insights?" from a Log Analytics answer, so its parsing of
the real `az monitor log-analytics query` output shape -- a flat JSON array
of row objects, never the `{"tables": [...]}` REST envelope -- and the bound
on its polling loop are the two properties worth pinning. Both are exercised
by running the script as a real program against the fake CLIs in
`doctor_harness.py`.
"""
import json
import time

import pytest

from doctor_harness import FakeAz, az_calls_for, lab_dir_for, run_baseline


# Long enough to allow several poll rounds, short enough that a genuinely
# unbounded loop fails the test instead of hanging the suite.
TELEMETRY_TIMEOUT_SECONDS = "5"
POLL_INTERVAL_SECONDS = "1"


@pytest.fixture
def fake_az(tmp_path):
    return FakeAz(workdir=tmp_path)


def run_bounded_baseline(fake_az, **env_overrides):
    return run_baseline(
        fake_az,
        lab_baseline_telemetry_timeout_seconds=TELEMETRY_TIMEOUT_SECONDS,
        lab_baseline_telemetry_poll_interval_seconds=POLL_INTERVAL_SECONDS,
        **env_overrides,
    )


def telemetry_check(fake_az):
    evidence_dirs = sorted((lab_dir_for(fake_az) / "evidence").glob("baseline-*"))
    assert evidence_dirs, "baseline.sh wrote no evidence directory"
    return json.loads((evidence_dirs[-1] / "telemetry-check.json").read_text())


def analytics_queries(fake_az):
    return [line for line in az_calls_for(fake_az).splitlines() if "monitor log-analytics" in line]


def test_baseline_succeeds_when_both_request_types_appear(fake_az):
    """The healthy case: the workspace answers with a non-empty flat array
    for both request types."""
    result = run_bounded_baseline(fake_az)

    assert result.returncode == 0, result.stdout + result.stderr
    assert telemetry_check(fake_az) == {
        "orders_telemetry_seen": True,
        "documents_telemetry_seen": True,
        "checked_at": telemetry_check(fake_az)["checked_at"],
    }


def test_baseline_fails_when_the_workspace_returns_no_rows(fake_az):
    """The empty case: `[]` for `/api/orders` must not be mistaken for data,
    and the failure has to name what was and was not seen."""
    fake_az.app_insights_orders_seen = False

    result = run_bounded_baseline(fake_az)

    assert result.returncode != 0
    assert telemetry_check(fake_az)["orders_telemetry_seen"] is False
    assert telemetry_check(fake_az)["documents_telemetry_seen"] is True
    assert "orders=0" in result.stderr


def test_baseline_query_does_not_count_rows_of_a_count(fake_az):
    """KQL `count` always returns exactly one row, so a row count taken from
    a `| count` query reports "data exists" for an empty workspace."""
    run_bounded_baseline(fake_az)

    queries = analytics_queries(fake_az)
    assert queries
    for query in queries:
        assert "| count" not in query, f"baseline query relies on `| count`: {query}"


def test_baseline_polling_is_bounded_by_the_timeout(fake_az):
    """Telemetry that never arrives must end the run near the timeout, not
    hang and not exit after a single try."""
    fake_az.app_insights_orders_seen = False
    fake_az.app_insights_documents_seen = False

    started = time.monotonic()
    result = run_bounded_baseline(fake_az)
    elapsed = time.monotonic() - started

    assert result.returncode != 0
    assert elapsed < int(TELEMETRY_TIMEOUT_SECONDS) + 20, f"poll overran its bound: {elapsed}s"
    assert len(analytics_queries(fake_az)) > 2, "baseline gave up without polling"


def test_baseline_polls_at_least_once_with_a_zero_timeout(fake_az):
    """A degenerate timeout must still produce one honest attempt and a
    telemetry-check record, never an unexplained silent pass."""
    result = run_baseline(
        fake_az,
        lab_baseline_telemetry_timeout_seconds="0",
        lab_baseline_telemetry_poll_interval_seconds="1",
    )

    assert analytics_queries(fake_az), "baseline never queried the workspace"
    assert result.returncode == 0, result.stdout + result.stderr
    assert telemetry_check(fake_az)["orders_telemetry_seen"] is True


def test_baseline_records_evidence_for_both_load_phases(fake_az):
    result = run_bounded_baseline(fake_az)

    assert result.returncode == 0, result.stdout + result.stderr
    evidence_dir = sorted((lab_dir_for(fake_az) / "evidence").glob("baseline-*"))[-1]
    assert (evidence_dir / "orders.json").is_file()
    assert (evidence_dir / "documents.json").is_file()
