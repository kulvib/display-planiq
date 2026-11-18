"""Offline comparison thresholds require adequate evidence; never claim no slowdown."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import display_63_compare_baselines as compare
import display_63_cost_performance_baseline as perf


def report():
    return {
        "schema": perf.SCHEMA,
        "sample_seconds": 3600,
        "observed_distinct_clients_in_paths": 1,
        "request_categories": {
            "client_presence": {"requests": 240, "timed_requests": 200,
                                "p95_response_ms": 10, "scales_with_clients": True},
            "client_token": {"requests": 25, "timed_requests": 25,
                             "p95_response_ms": 80, "scales_with_clients": True},
        },
        "frontend": {"groups": {"javascript": {"gzip_bytes": 100000},
                                "stylesheet": {"gzip_bytes": 10000}}},
    }


def test_63_identical_baselines_have_no_indicator_but_are_not_proof():
    result = compare.compare(report(), report())
    assert result["regression_indicators"] == []
    assert result["real_world_cost_or_performance_verified"] is False
    assert result["release_or_deployment_authorized"] is False
    assert result["compared_metrics"] >= 4


def test_63_p95_regression_catches_material_slower_api():
    old, new = report(), report()
    new["request_categories"]["client_token"]["p95_response_ms"] = 120
    result = compare.compare(old, new)
    assert any(x["metric"] == "p95_response_ms" for x in result["regression_indicators"])


def test_63_p95_small_noise_does_not_trigger():
    old, new = report(), report()
    new["request_categories"]["client_presence"]["p95_response_ms"] = 12
    assert not any(x["metric"] == "p95_response_ms" for x in compare.compare(old, new)["regression_indicators"])


def test_63_more_client_requests_are_detected():
    old, new = report(), report()
    new["request_categories"]["client_presence"]["requests"] = 400
    assert any(x["metric"] == "requests_per_client_hour" for x in compare.compare(old, new)["regression_indicators"])


def test_63_population_normalization_avoids_false_traffic_alarm():
    old, new = report(), report()
    new["observed_distinct_clients_in_paths"] = 2
    new["request_categories"]["client_presence"]["requests"] = 480
    assert not any(x["metric"] == "requests_per_client_hour" for x in compare.compare(old, new)["regression_indicators"])


def test_63_bundle_growth_is_flagged():
    old, new = report(), report()
    new["frontend"]["groups"]["javascript"]["gzip_bytes"] = 110000
    assert any(x["metric"] == "gzip_bytes" for x in compare.compare(old, new)["regression_indicators"])


def test_63_missing_frontend_or_latency_reports_no_unearned_proof():
    old, new = report(), report()
    old.pop("frontend")
    new.pop("frontend")
    old["sample_seconds"] = 90
    assert compare.compare(old, new)["warnings"] == ["insufficient_db_hotpath_summary_coverage", "insufficient_observation_duration"]
    assert compare.compare(old, new)["compared_metrics"] == 0


def test_63_wrong_report_schema_rejected():
    wrong = copy.deepcopy(report())
    wrong["schema"] = "malicious"
    with pytest.raises(perf.PerformanceStop):
        compare.compare(wrong, report())


def test_63_no_raw_source_paths_or_client_credentials_leak():
    result = compare.compare(report(), report())
    assert "123.123.123.123" not in json.dumps(result)
    assert "/api/" not in json.dumps(result)


def test_63_read_report_refuses_symlinks(tmp_path):
    base = tmp_path / "before.json"
    base.write_text(json.dumps(report()))
    assert compare.read_report(base)["schema"] == perf.SCHEMA
    symlink = tmp_path / "link.json"
    symlink.symlink_to(base)
    with pytest.raises(perf.PerformanceStop, match="unsafe"):
        compare.read_report(symlink)


def test_63_cli_fails_on_indicator_only_when_opted_in(tmp_path, capsys):
    a = tmp_path / "before.json"
    b = tmp_path / "after.json"
    a.write_text(json.dumps(report()))
    new = report()
    new["request_categories"]["client_token"]["p95_response_ms"] = 130
    b.write_text(json.dumps(new))
    args = ["--before", str(a), "--after", str(b)]
    assert compare.main(args) == 0
    assert compare.main(args + ["--fail-on-indicator"]) == 1
    assert "REGRESSION_INDICATOR" in capsys.readouterr().out


def test_63_http_error_rate_regression_is_detected():
    old, new = report(), report()
    old["request_categories"]["client_presence"]["errors_5xx"] = 0
    new["request_categories"]["client_presence"]["errors_5xx"] = 16
    assert any(x["metric"] == "http_5xx_percent" for x in compare.compare(old, new)["regression_indicators"])


def test_63_unrecognized_category_not_echoed_in_compare():
    old, new = report(), report()
    old["request_categories"]["private-credential-in-label"] = {"requests": 100, "timed_requests": 50, "p95_response_ms": 10}
    new["request_categories"]["private-credential-in-label"] = {"requests": 100, "timed_requests": 50, "p95_response_ms": 100}
    assert "private-credential" not in json.dumps(compare.compare(old, new))
