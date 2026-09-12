import json

import pytest


def test_publishes_only_allowlisted_measurements():
    from evidence import check

    result = check(
        "learn-initialize",
        "live",
        "passed",
        http_status=200,
        protocol_version="2025-11-25",
    )
    assert result["observed"] == {
        "http_status": 200,
        "protocol_version": "2025-11-25",
    }
    assert result["status"] == "passed"


@pytest.mark.parametrize("field", ["token", "url", "response", "tenant_id", "message"])
def test_rejects_unreviewed_payload_fields(field):
    from evidence import check

    with pytest.raises(ValueError, match="measurement"):
        check("learn-initialize", "live", "passed", **{field: "private-value"})


def test_rejects_private_values_in_public_fields():
    from evidence import check

    with pytest.raises(ValueError, match="protocol_version"):
        check(
            "learn-initialize",
            "live",
            "passed",
            protocol_version="https://internal.example.test",
        )


def test_rejects_unknown_status():
    from evidence import check

    with pytest.raises(ValueError, match="status"):
        check("obo-arm", "live", "probably-passed")


def test_blocked_is_not_a_pass_in_report():
    from evidence import check, render_report

    document = {
        "recorded_at": "2026-09-13T02:00:00+09:00",
        "checks": [
            check("learn-initialize", "live", "passed", http_status=200),
            check("obo-arm", "live", "blocked", error_code="AADSTS65001"),
        ],
    }
    html = render_report(document)
    assert "1 passed" in html
    assert "1 blocked" in html
    assert "AADSTS65001" in html
    assert "Sanitized execution evidence" in html
    assert "Azure portal" in html


def test_renderer_revalidates_files_before_publishing():
    from evidence import render_report

    document = {
        "recorded_at": "2026-09-13T02:00:00+09:00",
        "checks": [
            {
                "id": "learn-initialize",
                "scope": "live",
                "status": "passed",
                "observed": {"token": "must-not-appear"},
            }
        ],
    }
    with pytest.raises(ValueError, match="measurement"):
        render_report(document)


def test_output_has_no_unrequested_identity_fields():
    from evidence import check, write_results

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "evidence.json"
        write_results(path, [check("apim-tools-list", "live", "passed", tool_count=1)])
        result = json.loads(path.read_text())
    assert set(result) == {"recorded_at", "checks"}
    assert result["checks"][0]["observed"] == {"tool_count": 1}


def test_duplicate_check_ids_are_rejected():
    from evidence import check, render_report

    same = check("learn-initialize", "live", "passed", http_status=200)
    with pytest.raises(ValueError, match="duplicate"):
        render_report(
            {"recorded_at": "2026-09-13T02:00:00+09:00", "checks": [same, same]}
        )
