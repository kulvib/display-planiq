"""Fase 63B: DB hotpath regression must use actual, covered operations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import display_63_compare_baselines as compare
import display_63_cost_performance_baseline as perf


def report(*, operations=100, statements=100, checkouts=100, windows=3, websocket=False):
    counters = {
        "requests": 0 if websocket else operations,
        "websocket_rechecks": operations if websocket else 0,
        "statements": statements,
        "checkouts": checkouts,
    }
    return {
        "schema": perf.SCHEMA,
        "sample_seconds": 3600,
        "observed_distinct_clients_in_paths": 1,
        "request_categories": {},
        "db_hotpath_windows_observed": windows,
        "db_hotpath_categories": {
            "terminal_ws_recheck" if websocket else "shared_status": counters,
        },
    }


def test_63b_detects_statement_cost_regression_per_operation():
    before = report(statements=100)
    after = report(statements=200)
    result = compare.compare(before, after)
    assert result["status"] == "REGRESSION_INDICATOR"
    assert {x["metric"] for x in result["regression_indicators"]} == {"statements_per_operation"}
    assert result["compared_metrics"] == 2


def test_63b_detects_db_checkout_regression_and_normalizes_population():
    before = report(operations=100, statements=100, checkouts=100)
    after = report(operations=200, statements=200, checkouts=400)
    result = compare.compare(before, after)
    assert {x["metric"] for x in result["regression_indicators"]} == {"checkouts_per_operation"}


def test_63b_websocket_rechecks_are_not_excluded_from_denominator():
    before = report(operations=30, statements=30, websocket=True)
    after = report(operations=30, statements=90, websocket=True)
    assert "statements_per_operation" in {
        x["metric"] for x in compare.compare(before, after)["regression_indicators"]
    }


def test_63b_two_complete_summary_windows_required():
    before = report(windows=1)
    after = report(statements=999, windows=10)
    result = compare.compare(before, after)
    assert result["compared_metrics"] == 0
    assert "insufficient_db_hotpath_summary_coverage" in result["warnings"]
    assert result["regression_indicators"] == []


def test_63b_short_http_window_blocks_db_comparison():
    before = report()
    before["sample_seconds"] = 300
    result = compare.compare(before, report(statements=999))
    assert result["compared_metrics"] == 0
    assert "insufficient_observation_duration" in result["warnings"]


def test_63b_missing_zero_and_invalid_sql_values_are_not_comparable():
    before = report(operations=0)
    after = report(statements=1_000_000)
    assert compare.compare(before, after)["compared_metrics"] == 0
    before = report()
    before["db_hotpath_categories"]["shared_status"]["statements"] = "100 private token"
    assert compare.compare(before, after)["compared_metrics"] == 1  # checkouts only


def test_63b_never_echoes_untrusted_categories_or_sql():
    before = report()
    after = report(statements=400)
    before["db_hotpath_categories"]["private IP / password"] = {"requests": 50, "statements": 2}
    after["db_hotpath_categories"]["private IP / password"] = {"requests": 50, "statements": 500}
    serialized = json.dumps(compare.compare(before, after))
    assert "private IP" not in serialized
    assert "password" not in serialized


def test_63b_sanitized_cursor_time_is_included_in_baseline():
    start = datetime(2026, 11, 17, tzinfo=timezone.utc)
    def request(time):
        return {
            "timestamp": time.isoformat(),
            "message": "responseTimeMS=8",
            "labels": {"type": "request", "method": "HEAD", "statusCode": "200", "path": "/health"},
        }
    summary = {
        "window_seconds": 900.0,
        "categories": {"shared_status": {"requests": 30, "statements": 60, "cursor_ms": 83.75},
                       "untrusted sql text password": {"requests": 100, "cursor_ms": 1000}},
    }
    rows = [request(start), request(start + timedelta(minutes=35)),
            {"message": "db_hotpath_summary " + json.dumps(summary)}]
    observation = perf.analyze(rows)
    assert observation["db_hotpath_window_seconds_sum"] == 900
    assert observation["db_hotpath_categories"]["shared_status"]["cursor_ms"] == 83.75
    assert "untrusted sql" not in json.dumps(observation)


@pytest.mark.parametrize("bad", [-1, "0.5", float("nan"), float("inf"), True, 100_000_000])
def test_63b_invalid_cursor_time_never_enters_report(bad):
    start = datetime(2026, 11, 17, tzinfo=timezone.utc)
    rows = [
        f'{start.isoformat()} INFO: "HEAD /health HTTP/1.1" 200',
        f'{(start + timedelta(minutes=35)).isoformat()} INFO: "HEAD /health HTTP/1.1" 200',
        {"message": "db_hotpath_summary " + json.dumps({
            "window_seconds": 900,
            "categories": {"shared_status": {"requests": 50, "cursor_ms": bad}},
        })},
    ]
    assert perf.analyze(rows)["db_hotpath_categories"]["shared_status"].get("cursor_ms", 0) == 0
