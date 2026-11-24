#!/usr/bin/env python3
"""63D-48 controlled evidence comparison: no guesses or missing-data PASS.

Accepts local, operator-reviewed JSON; never connects to a kiosk or network.
Only anonymized metrics, no credentials, session IDs, IPs or pixel contents.
The test is intentionally strict: a connected WebSocket or a running X11
window cannot be scored as end-to-end pointer performance.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys

ENGINES = ("native-freerdp", "browser-freerdp-wasm", "browser-guacamole")
INTERACTIONS = ("pointer", "click", "drag", "scroll", "keyboard")
SOURCE = {"width": 2560, "height": 1080, "scale": 1.0}
MAX_SIZE = 64 * 1024
MOUSE_MEASUREMENT_METHODS = ("high-speed-video", "instrumented-input-to-pixel")


class EvidenceError(ValueError):
    pass


def check_keys(value: dict, required: set[str], optional: set[str] = frozenset()) -> None:
    if type(value) is not dict or set(value) - required - optional or required - set(value):
        raise EvidenceError("UNEXPECTED_OR_MISSING_FIELDS")


def check_int(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise EvidenceError("INVALID_INTEGER_MEASUREMENT")
    return value


def check_float(value: object, minimum: float, maximum: float) -> float:
    if type(value) not in (float, int) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise EvidenceError("INVALID_NUMERIC_MEASUREMENT")
    return float(value)


def require_true(value: object) -> None:
    if value is not True:
        raise EvidenceError("REQUIRED_EVIDENCE_NOT_PASSED")


def validate_run(item: dict) -> dict:
    required = {
        "engine", "source", "canvas", "method", "mouse_samples_ms",
        "interaction", "security", "resource",
    }
    check_keys(item, required)
    engine = item["engine"]
    if engine not in ENGINES:
        raise EvidenceError("UNKNOWN_ENGINE")
    if item["source"] != SOURCE:
        raise EvidenceError("UNVERIFIED_PHYSICAL_MONITOR")
    canvas = item["canvas"]
    check_keys(canvas, {"width", "height"})
    width = check_int(canvas["width"], 320, 8192)
    height = check_int(canvas["height"], 200, 8192)
    if width != SOURCE["width"] or height != SOURCE["height"]:
        raise EvidenceError("REMOTE_PIXEL_SIZE_MISMATCH")

    method = item["method"]
    if method not in MOUSE_MEASUREMENT_METHODS:
        raise EvidenceError("NOT_END_TO_END_MOUSE_MEASUREMENT")
    values = item["mouse_samples_ms"]
    if type(values) is not list or not 30 <= len(values) <= 1000:
        raise EvidenceError("INSUFFICIENT_OR_UNBOUNDED_MOUSE_SAMPLES")
    sorted_values = sorted(check_float(x, 0, 30000) for x in values)
    p50 = statistics.median(sorted_values)
    p95 = sorted_values[math.ceil(0.95 * len(sorted_values)) - 1]
    interaction = item["interaction"]
    check_keys(interaction, set(INTERACTIONS))
    for key in INTERACTIONS:
        require_true(interaction[key])

    security = item["security"]
    names = {
        "rdp_port_local_only", "session_authorized", "expiry_enforced",
        "secrets_not_logged", "agent_rollback_verified",
        "trust_boundary_reviewed",
    }
    check_keys(security, names)
    for key in names:
        require_true(security[key])
    resource = item["resource"]
    check_keys(resource, {"cpu_cores", "memory_mb", "traffic_mbps"})
    cpu = check_float(resource["cpu_cores"], 0, 64)
    memory = check_float(resource["memory_mb"], 0, 65536)
    traffic = check_float(resource["traffic_mbps"], 0, 10000)

    return {
        "engine": engine,
        "samples": len(sorted_values),
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "cpu_cores": cpu, "memory_mb": memory, "traffic_mbps": traffic,
        "target_met": p50 <= 150 and p95 <= 250,
    }


def compare(doc: dict) -> dict:
    check_keys(doc, {"schema", "client_id", "network_group", "runs"})
    if doc["schema"] != 1 or doc["client_id"] != 3:
        raise EvidenceError("UNRECOGNIZED_SCHEMA_OR_CLIENT")
    if type(doc["network_group"]) is not str or not 1 <= len(doc["network_group"]) <= 64:
        raise EvidenceError("INVALID_NETWORK_BASELINE")
    if not doc["network_group"].isascii() or not doc["network_group"].replace("-", "").isalnum():
        raise EvidenceError("INVALID_NETWORK_BASELINE")
    runs = doc["runs"]
    if type(runs) is not list or len(runs) != len(ENGINES):
        raise EvidenceError("ALL_THREE_ENGINES_REQUIRED")
    results = [validate_run(item) for item in runs]
    if len({x["engine"] for x in results}) != len(ENGINES):
        raise EvidenceError("DUPLICATE_ENGINE")
    ready = sorted((x for x in results if x["target_met"]),
                   key=lambda x: (x["p95_ms"], x["p50_ms"], x["traffic_mbps"]))
    return {
        "schema": 1, "physical_primary": "2560x1080@60Hz",
        "target_p50_ms": 150, "target_p95_ms": 250,
        "status": "COMPARABLE_EVIDENCE" if ready else "ALL_OPTIONS_FAILED_LATENCY_GATE",
        "options_meeting_latency_gate": [x["engine"] for x in ready],
        "results": results,
        "winner_requires_operator_approval": True,
        "release_1249_approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_file")
    args = parser.parse_args()
    try:
        path = Path(args.evidence_file)
        st = path.lstat()
        if not path.is_file() or path.is_symlink() or st.st_size > MAX_SIZE:
            raise EvidenceError("UNSAFE_EVIDENCE_FILE")
        data = json.loads(path.read_text(encoding="utf-8"))
        report = compare(data)
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0
    except (EvidenceError, ValueError, OSError, KeyError, TypeError) as exc:
        code = str(exc) if isinstance(exc, EvidenceError) else type(exc).__name__
        print("63D48_COMPARISON=STOP_" + code[:80])
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
