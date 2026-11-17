#!/usr/bin/env python3
"""62D: local-only aggregate of HTTP statuses from Render access-log exports.

Does not contact Render, touch production, retain IP addresses, print URLs,
return authentication data or assert true RPO/RTO. Each printed window is only
an OBSERVED 502/503 span in supplied logs, not a measured uptime guarantee.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

SCHEMA = 'planiq-display-62d-deployment-gap-observation-v1'
# Render's text access logs contain `statusCode=502` (structured) or Uvicorn
# `"GET /path HTTP/1.1" 502`; do not parse/print the full request line.
STATUS_JSON = re.compile(r'(?<![\w])(?:statusCode|status_code)["=:\s]+["\s]*(\d{3})\b')
STATUS_UVICORN = re.compile(r'"(?:GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)\s+\S+\s+HTTP/\d(?:\.\d)?"\s+(\d{3})\b')
ISO_UTC = re.compile(r'(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?Z')
MAX_LINES = 300_000
MAX_BYTES = 64 * 1024 * 1024


class GapReportStop(RuntimeError):
    pass


def _timestamp(line: str) -> datetime | None:
    match = ISO_UTC.search(line)
    if not match:
        return None
    try:
        # Ignore subsecond precision; gap evidence is only seconds-resolution.
        return datetime.fromisoformat(match.group(1)).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def analyze_lines(lines) -> dict:
    counts = Counter()
    observed = []
    total = parsed = 0
    for total, line in enumerate(lines, 1):
        if total > MAX_LINES:
            raise GapReportStop('log_too_large')
        match = STATUS_JSON.search(line) or STATUS_UVICORN.search(line)
        timestamp = _timestamp(line)
        if match is None or timestamp is None:
            continue
        parsed += 1
        code = int(match.group(1))
        counts[code] += 1
        if code in (502, 503):
            observed.append(timestamp)

    observed.sort()
    # Gaps separate after >15s between observed errors. No extrapolation to
    # non-observed requests, which could make apparent duration misleading.
    windows = []
    for stamp in observed:
        if not windows or (stamp - windows[-1]['_last']).total_seconds() > 15:
            windows.append({'_first': stamp, '_last': stamp, 'errors_observed': 1})
        else:
            windows[-1]['_last'] = stamp
            windows[-1]['errors_observed'] += 1
    windows_out = [{
        'first_observed_utc': w['_first'].strftime('%Y-%m-%dT%H:%M:%SZ'),
        'last_observed_utc': w['_last'].strftime('%Y-%m-%dT%H:%M:%SZ'),
        'observed_span_seconds': int((w['_last']-w['_first']).total_seconds()),
        'errors_observed': w['errors_observed'],
    } for w in windows]
    return {
        'schema': SCHEMA,
        'mode': 'offline_log_observation',
        'input_lines': total,
        'parseable_timestamped_responses': parsed,
        'http_200_count': counts[200],
        'http_401_count': counts[401],
        'http_405_count': counts[405],
        'http_500_count': counts[500],
        'http_502_count': counts[502],
        'http_503_count': counts[503],
        'observed_502_503_windows': windows_out,
        'complete_log_evidence': False,
        'measured_service_uptime': False,
        'deployment_without_downtime_proven': False,
        'client_deployment_authorized': False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-file', type=Path, required=True, help='offline local UTF-8 text export')
    args = p.parse_args(argv)
    try:
        file = args.input_file
        if not file.is_file() or file.is_symlink() or file.stat().st_size > MAX_BYTES:
            raise GapReportStop('unsafe_log_input')
        with file.open('r', encoding='utf-8', errors='replace') as fh:
            result = analyze_lines(fh)
    except (GapReportStop, OSError) as exc:
        print('62D STOP: ' + (str(exc) if isinstance(exc, GapReportStop) else 'unreadable_log'), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
