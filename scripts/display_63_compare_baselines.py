#!/usr/bin/env python3
"""63: compare two sanitized offline observations; never claim production capacity proof.

Signals are diagnostic regression indicators, not statistically representative
benchmarks. Incomplete samples never become proof of no slowdown.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from display_63_cost_performance_baseline import (
    SCHEMA, PerformanceStop, MAX_INPUT_BYTES, CLIENT_CATEGORIES, ALLOWED_DB_CATEGORIES,
)

MIN_SAMPLE_SECONDS = 1800
MIN_TIMED_REQUESTS = 20
MIN_CATEGORY_REQUESTS = 20
P95_RELATIVE_LIMIT = 0.15
P95_ABSOLUTE_LIMIT_MS = 10
TRAFFIC_PER_CLIENT_RELATIVE_LIMIT = 0.20
FRONTEND_GZIP_RELATIVE_LIMIT = 0.05
DB_STATEMENTS_PER_OPERATION_RELATIVE_LIMIT = 0.20
DB_STATEMENTS_PER_OPERATION_ABSOLUTE_LIMIT = 0.5
DB_CHECKOUTS_PER_OPERATION_RELATIVE_LIMIT = 0.25
DB_CHECKOUTS_PER_OPERATION_ABSOLUTE_LIMIT = 0.25
MIN_DB_OPERATIONS = 20
MIN_DB_SUMMARIES = 2


def read_report(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or not (0 < path.stat().st_size < min(MAX_INPUT_BYTES, 2 * 1024 * 1024)):
        raise PerformanceStop("report_file_missing_or_unsafe")
    with path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise PerformanceStop("incompatible_report_schema")
    return payload


def compare(before: dict, after: dict) -> dict:
    if before.get("schema") != SCHEMA or after.get("schema") != SCHEMA:
        raise PerformanceStop("incompatible_report_schema")
    warnings = []
    indicators = []
    measured = 0
    duration_before = before.get("sample_seconds", 0)
    duration_after = after.get("sample_seconds", 0)
    clients_before = before.get("observed_distinct_clients_in_paths", 0)
    clients_after = after.get("observed_distinct_clients_in_paths", 0)
    eligible = (isinstance(duration_before, (int, float)) and isinstance(duration_after, (int, float))
                and duration_before >= MIN_SAMPLE_SECONDS and duration_after >= MIN_SAMPLE_SECONDS)
    if not eligible:
        warnings.append("insufficient_observation_duration")
    if not clients_before or not clients_after:
        warnings.append("no_identifiable_client_population")
    ca = before.get("request_categories", {})
    cb = after.get("request_categories", {})
    if not isinstance(ca, dict) or not isinstance(cb, dict):
        raise PerformanceStop("malformed_observation")
    valid_categories = CLIENT_CATEGORIES | {"backend_db_readiness", "admin_or_api", "other"}
    for category in sorted(set(ca) & set(cb) & valid_categories):
        a, b = ca[category], cb[category]
        if not isinstance(a, dict) or not isinstance(b, dict):
            continue
        if a.get("timed_requests", 0) >= MIN_TIMED_REQUESTS and b.get("timed_requests", 0) >= MIN_TIMED_REQUESTS and eligible:
            p1, p2 = a.get("p95_response_ms"), b.get("p95_response_ms")
            if isinstance(p1, (float, int)) and isinstance(p2, (float, int)) and p1 >= 0 and p2 >= 0:
                measured += 1
                if p2 > p1 * (1 + P95_RELATIVE_LIMIT) and p2 > p1 + P95_ABSOLUTE_LIMIT_MS:
                    indicators.append({"category": category, "metric": "p95_response_ms", "before": p1, "after": p2})
        # HTTP 5xx is a direct service-availability regression indicator.
        # Require enough observations and a material absolute rise, not noise.
        if (eligible and a.get("requests", 0) >= MIN_CATEGORY_REQUESTS
                and b.get("requests", 0) >= MIN_CATEGORY_REQUESTS):
            old_errors, new_errors = a.get("errors_5xx", 0), b.get("errors_5xx", 0)
            if (type(old_errors) is int and type(new_errors) is int
                    and 0 <= old_errors <= a["requests"] and 0 <= new_errors <= b["requests"]):
                measured += 1
                old_share = old_errors / a["requests"]
                new_share = new_errors / b["requests"]
                if new_share > old_share + 0.02 and new_share > old_share * 1.5:
                    indicators.append({"category": category, "metric": "http_5xx_percent",
                                       "before": round(old_share * 100, 2),
                                       "after": round(new_share * 100, 2)})
        # Request-rate change is meaningful only for the same fixed category and
        # observed client population; no extrapolation to real billing costs.
        if (eligible and clients_before and clients_after and a.get("scales_with_clients") is True
                and b.get("scales_with_clients") is True and a.get("requests", 0) >= MIN_CATEGORY_REQUESTS
                and b.get("requests", 0) >= MIN_CATEGORY_REQUESTS):
            old_rate = a["requests"] / (duration_before / 3600) / clients_before
            new_rate = b["requests"] / (duration_after / 3600) / clients_after
            measured += 1
            if new_rate > old_rate * (1 + TRAFFIC_PER_CLIENT_RELATIVE_LIMIT):
                indicators.append({"category": category, "metric": "requests_per_client_hour",
                                   "before": round(old_rate, 2), "after": round(new_rate, 2)})
    # DB counters are emitted only when a hotpath triggers the completed 15m
    # window. Missing/short samples are not evidence of zero DB traffic.
    da = before.get("db_hotpath_categories", {})
    db = after.get("db_hotpath_categories", {})
    wa = before.get("db_hotpath_windows_observed", 0)
    wb = after.get("db_hotpath_windows_observed", 0)
    if not isinstance(da, dict) or not isinstance(db, dict):
        raise PerformanceStop("malformed_db_observation")
    enough_db = eligible and type(wa) is int and type(wb) is int and wa >= MIN_DB_SUMMARIES and wb >= MIN_DB_SUMMARIES
    if not enough_db:
        warnings.append("insufficient_db_hotpath_summary_coverage")
    else:
        for category in sorted(set(da) & set(db) & ALLOWED_DB_CATEGORIES):
            old, new = da[category], db[category]
            if not isinstance(old, dict) or not isinstance(new, dict):
                continue
            def operation_count(counts):
                requests = counts.get("requests", 0)
                rechecks = counts.get("websocket_rechecks", 0)
                if type(requests) is not int or type(rechecks) is not int or requests < 0 or rechecks < 0:
                    return 0
                return requests + rechecks

            a_ops, b_ops = operation_count(old), operation_count(new)
            if min(a_ops, b_ops) < MIN_DB_OPERATIONS:
                continue
            for metric, relative, absolute in (
                ("statements", DB_STATEMENTS_PER_OPERATION_RELATIVE_LIMIT,
                 DB_STATEMENTS_PER_OPERATION_ABSOLUTE_LIMIT),
                ("checkouts", DB_CHECKOUTS_PER_OPERATION_RELATIVE_LIMIT,
                 DB_CHECKOUTS_PER_OPERATION_ABSOLUTE_LIMIT),
            ):
                a_count, b_count = old.get(metric), new.get(metric)
                if (type(a_count) is not int or type(b_count) is not int
                        or not (0 <= a_count <= 10_000_000 and 0 <= b_count <= 10_000_000)):
                    continue
                a_rate = a_count / a_ops
                b_rate = b_count / b_ops
                measured += 1
                if b_rate > a_rate * (1 + relative) and b_rate > a_rate + absolute:
                    indicators.append({
                        "category": category, "metric": metric + "_per_operation",
                        "before": round(a_rate, 3), "after": round(b_rate, 3),
                    })
    fa = before.get("frontend", {}).get("groups", {}) if isinstance(before.get("frontend"), dict) else {}
    fb = after.get("frontend", {}).get("groups", {}) if isinstance(after.get("frontend"), dict) else {}
    for category in ("javascript", "stylesheet"):
        if category not in fa or category not in fb:
            continue
        old = fa[category].get("gzip_bytes", 0)
        new = fb[category].get("gzip_bytes", 0)
        if type(old) is int and type(new) is int and old > 0 and new >= 0:
            measured += 1
            if new > old * (1 + FRONTEND_GZIP_RELATIVE_LIMIT):
                indicators.append({"category": category, "metric": "gzip_bytes", "before": old, "after": new})
    return {
        "schema": "planiq-display-63-regression-indicators-v1",
        "status": "REGRESSION_INDICATOR" if indicators else "NO_INDICATOR_NOT_PROOF_OF_NO_REGRESSION",
        "compared_metrics": measured,
        "warnings": sorted(warnings),
        "regression_indicators": indicators,
        "real_world_cost_or_performance_verified": False,
        "release_or_deployment_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--fail-on-indicator", action="store_true")
    args = parser.parse_args(argv)
    try:
        outcome = compare(read_report(args.before), read_report(args.after))
    except (OSError, ValueError, TypeError, PerformanceStop, json.JSONDecodeError) as exc:
        message = str(exc) if isinstance(exc, PerformanceStop) else "invalid_or_unreadable_report"
        print("63 STOP: " + message, file=sys.stderr)
        return 2
    print(json.dumps(outcome, indent=2, sort_keys=True))
    return 1 if args.fail_on_indicator and outcome["regression_indicators"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
