#!/usr/bin/env python3
"""PlanIQ Display 63: offline, identity-free HTTP/DB/frontend cost-performance baseline.

Never contacts a service, alters cadence, or uses production secrets. Projections
are linear traffic models, NOT benchmarks, price forecasts or 100-client proof.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
import re
import sys

SCHEMA = "planiq-display-63-performance-observation-v1"
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 300_000
MAX_ASSETS = 5_000
ISO = re.compile(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)")
STATUS = re.compile(r'(?<!\w)(?:statusCode|status_code)["=: ]+[" ]*(\d{3})\b')
UVICORN = re.compile(r'"(GET|HEAD|POST|PUT|DELETE|PATCH|OPTIONS)\s+(\S+)\s+HTTP/\d(?:\.\d)?"\s+(\d{3})\b')
ELAPSED = re.compile(r'\bresponseTimeMS=(\d+(?:\.\d+)?)\b')
ID_IN_PATH = re.compile(r"/clients/(\d+)(?:/|$)")
CLIENT_CATEGORIES = frozenset({"client_connectivity", "client_token", "client_presence", "client_status",
                               "client_claim", "client_wait", "client_other", "client_remote"})
ALLOWED_DB_CATEGORIES = frozenset({
    "updater_token", "updater_other", "terminal_token", "remote_desktop_token", "shared_token",
    "terminal_relay", "terminal_agent", "remote_desktop_relay", "remote_desktop_agent",
    "livestream_presence", "livestream_status", "livestream_other",
    "shared_presence", "shared_status", "shared_other",
    "terminal_ws_recheck", "remote_desktop_ws_recheck",
})


class PerformanceStop(RuntimeError):
    pass


def category_for(path: str, method: str) -> tuple[str, bool]:
    """Return a fixed category and whether it scales with connected clients."""
    if path == "/health" and method == "HEAD":
        return "client_connectivity", True
    if path == "/health/db":
        return "backend_db_readiness", False
    if path in {"/api/client-auth/token", "/api/clientflow-update/token"}:
        return "client_token", True
    if path.startswith(("/api/status-agent/clients/", "/api/system-agent/clients/",
                        "/api/display-agent/clients/", "/api/livestream-agent/clients/")):
        if path.endswith("/presence"):
            return "client_presence", True
        if path.endswith("/status"):
            return "client_status", True
        if path.endswith("/commands/claim"):
            return "client_claim", True
        if "/commands/wait" in path:
            return "client_wait", True
        return "client_other", True
    if path.startswith(("/api/terminal-agent/clients/", "/api/remote-desktop-agent/clients/")):
        return "client_remote", True
    if path.startswith("/api/"):
        return "admin_or_api", False
    return "other", False


def _labels(row: dict) -> dict[str, str]:
    labels = row.get("labels", [])
    if isinstance(labels, dict):
        return {str(k): str(v) for k, v in labels.items()}
    if isinstance(labels, list):
        return {str(item.get("name")): str(item.get("value")) for item in labels
                if isinstance(item, dict) and isinstance(item.get("name"), str)}
    return {}


def _dt(value: str) -> datetime | None:
    match = ISO.search(value)
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(0).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _read_rows(path: Path):
    if path.is_symlink() or not path.is_file() or not (0 < path.stat().st_size <= MAX_INPUT_BYTES):
        raise PerformanceStop("input_file_missing_or_unsafe")
    with path.open(encoding="utf-8", errors="replace") as fh:
        contents = fh.read()
    stripped = contents.lstrip()
    # First try a full, ordinary Render JSON export (array or {"logs": [...]});
    # if it is NDJSON/text, fall back to one-record-per-line streaming.
    if stripped.startswith(("[", "{")):
        try:
            rows = json.loads(contents)
        except ValueError:
            rows = None
        if rows is not None:
            if isinstance(rows, dict) and "logs" in rows:
                rows = rows["logs"]
            elif isinstance(rows, dict):
                rows = [rows]
            if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
                raise PerformanceStop("invalid_or_oversized_json_export")
            yield from rows
            return
    for i, line in enumerate(contents.splitlines(), 1):
        if i > MAX_RECORDS or len(line) > 65536:
            raise PerformanceStop("oversized_log_export")
        if line.lstrip().startswith("{"):
            try:
                yield json.loads(line)
            except ValueError:
                continue
        else:
            yield line


def _request(row: object):
    if isinstance(row, dict):
        labels = _labels(row)
        if labels.get("type") not in (None, "request"):
            return None
        message = str(row.get("message", ""))
        stamp = _dt(str(row.get("timestamp", "")))
        path = labels.get("path", "").split("?", 1)[0]
        method = labels.get("method", "")
        code = labels.get("statusCode", "")
        ms = ELAPSED.search(message)
        if stamp and method in {"HEAD", "GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} and code.isdecimal():
            return stamp, method, path, int(code), (float(ms.group(1)) if ms else None)
        return None
    line = str(row)
    stamp = _dt(line)
    match = UVICORN.search(line)
    if stamp and match:
        method, path, code = match.groups()
        latency = ELAPSED.search(line)
        return stamp, method, path.split("?", 1)[0], int(code), (float(latency.group(1)) if latency else None)
    return None


def _database_summary(row: object) -> dict | None:
    if isinstance(row, dict):
        message = str(row.get("message", ""))
    else:
        message = str(row)
    marker = "db_hotpath_summary "
    if marker not in message:
        return None
    try:
        payload = json.loads(message.split(marker, 1)[1].strip())
    except ValueError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("categories"), dict):
        return None
    return payload["categories"]


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(len(ordered) * pct) - 1], 2)


def analyze(rows) -> dict:
    counters: dict[str, Counter] = defaultdict(Counter)
    timings: dict[str, list[float]] = defaultdict(list)
    seconds = Counter()
    unique_client_ids: set[str] = set()
    timestamps: list[datetime] = []
    db_counts: dict[str, Counter] = defaultdict(Counter)
    summaries = 0
    ignored = 0
    for index, row in enumerate(rows, 1):
        if index > MAX_RECORDS:
            raise PerformanceStop("too_many_rows")
        summary = _database_summary(row)
        if summary is not None:
            summaries += 1
            for key, values in summary.items():
                if key not in ALLOWED_DB_CATEGORIES or not isinstance(values, dict):
                    continue
                for metric in ("requests", "failed_http", "statements", "selects", "checkouts", "websocket_rechecks"):
                    v = values.get(metric, 0)
                    if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10_000_000:
                        db_counts[key][metric] += v
            continue
        data = _request(row)
        if data is None:
            ignored += 1
            continue
        stamp, method, path, code, ms = data
        category, per_client = category_for(path, method)
        counters[category]["requests"] += 1
        counters[category]["errors_4xx"] += int(400 <= code < 500)
        counters[category]["errors_5xx"] += int(code >= 500)
        counters[category]["errors_502_503"] += int(code in (502, 503))
        if ms is not None and 0 <= ms <= 600_000 and math.isfinite(ms):
            timings[category].append(ms)
        if per_client:
            match = ID_IN_PATH.search(path)
            if match:
                unique_client_ids.add(match.group(1))
        timestamps.append(stamp)
        seconds[stamp.replace(microsecond=0)] += 1
    if not timestamps:
        raise PerformanceStop("no_timestamped_requests")
    duration = (max(timestamps) - min(timestamps)).total_seconds()
    if duration < 300:
        raise PerformanceStop("sample_too_short_min_300_seconds")
    observed_clients = len(unique_client_ids)
    request_categories = {}
    per_client_total = 0
    other_total = 0
    for name, values in sorted(counters.items()):
        is_client = name in CLIENT_CATEGORIES
        # Never return paths, client IDs, IP addresses or log messages.
        request_categories[name] = {
            **dict(values),
            "p50_response_ms": _percentile(timings[name], 0.50),
            "p95_response_ms": _percentile(timings[name], 0.95),
            "timed_requests": len(timings[name]),
            "scales_with_clients": is_client,
        }
        if is_client:
            per_client_total += values["requests"]
        else:
            other_total += values["requests"]
    models = []
    for clients in (1, 10, 50, 100):
        # Infer no client count from an auth token endpoint alone.
        if observed_clients:
            per_client_daily = per_client_total / observed_clients * 86400 / duration
            independent_daily = other_total * 86400 / duration
            models.append({
                "clients": clients,
                "projected_requests_per_day": round(independent_daily + per_client_daily * clients),
                "per_client_requests_per_day": round(per_client_daily),
                "projected_db_statements_per_day": None,
                "capacity_test_passed": False,
                "render_price_estimated": False,
            })
    return {
        "schema": SCHEMA,
        "status": "OBSERVATION_NOT_CAPACITY_PROOF",
        "sample_seconds": round(duration, 1),
        "observed_timestamped_requests": len(timestamps),
        "observed_distinct_clients_in_paths": observed_clients,
        "unparsed_or_nonrequest_lines": ignored,
        "peak_requests_in_one_observed_second": max(seconds.values()),
        "request_categories": request_categories,
        "db_hotpath_windows_observed": summaries,
        "db_hotpath_categories": {k: dict(v) for k, v in sorted(db_counts.items())},
        "linear_traffic_scenarios": models,
        "log_export_complete": False,
        "real_100_client_load_test_passed": False,
        "frontend_no_regression_proven": False,
        "backend_no_regression_proven": False,
        "zero_additional_database_calls_from_this_tool": True,
        "cost_savings_proven": False,
    }


def frontend_baseline(dist: Path) -> dict:
    if dist.is_symlink() or not dist.is_dir():
        raise PerformanceStop("frontend_dist_missing_or_unsafe")
    counts: dict[str, Counter] = defaultdict(Counter)
    visited = 0
    for path in dist.rglob("*"):
        visited += 1
        if visited > MAX_ASSETS or path.is_symlink():
            raise PerformanceStop("frontend_dist_too_large_or_symlinked")
        if not path.is_file() or path.suffix not in (".js", ".css", ".html"):
            continue
        if path.stat().st_size > 32 * 1024 * 1024:
            raise PerformanceStop("frontend_asset_too_large")
        data = path.read_bytes()
        group = {".js": "javascript", ".css": "stylesheet", ".html": "html"}[path.suffix]
        counts[group]["files"] += 1
        counts[group]["uncompressed_bytes"] += len(data)
        counts[group]["gzip_bytes"] += len(gzip.compress(data, compresslevel=6, mtime=0))
    if not counts:
        raise PerformanceStop("frontend_no_build_assets")
    return {
        "kind": "built_static_asset_size_not_load_time",
        "groups": {key: dict(value) for key, value in sorted(counts.items())},
        "frontend_p95_load_time_ms": None,
        "frontend_performance_regression_proven_absent": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-file", type=Path, required=True,
                        help="local export of Render request logs (JSON, NDJSON or timestamped Uvicorn text)")
    parser.add_argument("--frontend-dist", type=Path,
                        help="optional existing frontend/dist; measures bundle sizes, does not run build")
    args = parser.parse_args(argv)
    try:
        report = analyze(_read_rows(args.input_file))
        if args.frontend_dist:
            report["frontend"] = frontend_baseline(args.frontend_dist)
    except (PerformanceStop, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        # No file names, raw log entries or secrets in errors.
        error = str(exc) if isinstance(exc, PerformanceStop) else "invalid_or_unreadable_input"
        print("63 STOP: " + error, file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
