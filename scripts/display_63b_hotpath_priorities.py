#!/usr/bin/env python3
"""63B: identify measured DB hotpaths from 63's identity-free offline report.

Read-only, deterministic, no raw log paths, no production connection and no
cost, latency, performance, or capacity proof from a traffic-only observation.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

from display_63_compare_baselines import read_report
from display_63_cost_performance_baseline import ALLOWED_DB_CATEGORIES, PerformanceStop

MAX_COUNTER = 10_000_000


def _count(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= MAX_COUNTER else None


def _milliseconds(value: object) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or value > 86_400_000:
        return None
    return float(value)


def priorities(report: dict) -> dict:
    rows = report.get("db_hotpath_categories", {})
    windows = _count(report.get("db_hotpath_windows_observed", 0))
    if not isinstance(rows, dict) or windows is None:
        raise PerformanceStop("malformed_db_observation")
    findings = []
    total_statements = 0
    for category in sorted(ALLOWED_DB_CATEGORIES & rows.keys()):
        counters = rows[category]
        if not isinstance(counters, dict):
            continue
        requests = _count(counters.get("requests", 0))
        rechecks = _count(counters.get("websocket_rechecks", 0))
        statements = _count(counters.get("statements"))
        checkouts = _count(counters.get("checkouts"))
        selects = _count(counters.get("selects"))
        cursor_ms = _milliseconds(counters.get("cursor_ms", 0))
        if None in (requests, rechecks, statements, checkouts, selects, cursor_ms):
            continue
        operations = requests + rechecks
        if operations == 0:
            continue
        total_statements += statements
        findings.append({
            "category": category,
            "observed_operations": operations,
            "observed_statements": statements,
            "statements_per_operation": round(statements / operations, 3),
            "selects_per_operation": round(selects / operations, 3),
            "checkouts_per_operation": round(checkouts / operations, 3),
            "total_db_cursor_ms": round(cursor_ms, 2),
            "security_sensitive_revocation_path": category in {
                "livestream_presence", "terminal_ws_recheck", "remote_desktop_ws_recheck",
            },
        })
    findings.sort(key=lambda row: (-row["observed_statements"], -row["observed_operations"], row["category"]))
    for row in findings:
        row["share_of_measured_hotpath_statements_percent"] = (
            round(100 * row["observed_statements"] / total_statements, 2) if total_statements else 0
        )
    warnings = []
    if windows < 2:
        warnings.append("insufficient_db_summary_windows")
    if not findings:
        warnings.append("no_valid_db_hotpath_rows")
    if report.get("log_export_complete") is not True:
        warnings.append("log_export_completeness_unverified")
    return {
        "schema": "planiq-display-63b-hotpath-priorities-v1",
        "status": "MEASURED_PRIORITIES_NOT_COST_PROOF" if windows >= 2 and findings
                  else "INSUFFICIENT_DB_EVIDENCE",
        "db_summary_windows": windows,
        "measured_hotpath_statements": total_statements,
        "hotpaths_descending_observed_statements": findings,
        "warnings": sorted(warnings),
        "measured_money_savings": None,
        "release_or_capacity_approval": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path,
                        help="sanitized JSON created by display_63_cost_performance_baseline.py")
    args = parser.parse_args(argv)
    try:
        output = priorities(read_report(args.baseline))
    except (OSError, ValueError, TypeError, PerformanceStop, json.JSONDecodeError) as exc:
        message = str(exc) if isinstance(exc, PerformanceStop) else "invalid_or_unreadable_report"
        print("63B STOP: " + message, file=sys.stderr)
        return 2
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["status"] == "MEASURED_PRIORITIES_NOT_COST_PROOF" else 2


if __name__ == "__main__":
    raise SystemExit(main())
