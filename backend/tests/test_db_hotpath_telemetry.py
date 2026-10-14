"""Deterministic, in-memory contract for low-cardinality DB hotpath accounting."""
from __future__ import annotations

import json
from types import SimpleNamespace

from service1.db_hotpath_telemetry import HotpathDatabaseTelemetry, classify_hotpath


def test_only_fixed_route_categories_are_accepted_without_dynamic_identifiers() -> None:
    examples = {
        "/api/livestream-agent/clients/57/presence": "livestream_presence",
        "/api/livestream-agent/clients/57/status": "livestream_status",
        "/api/livestream-agent/clients/57/commands/claim": "livestream_other",
        "/api/remote-desktop-agent/clients/57/control/http/private/poll": "remote_desktop_relay",
        "/api/remote-desktop-agent/clients/57/files/http/private/poll": "remote_desktop_relay",
        "/api/terminal-agent/clients/57/http/private/poll": "terminal_relay",
        "/api/clientflow-update/token": "updater_token",
        "/api/display-agent/clients/57/presence": "shared_presence",
        "/api/status-agent/clients/57/status": "shared_status",
        "/api/terminal-auth/token": "terminal_token",
        "/api/remote-desktop-auth/token": "remote_desktop_token",
    }
    for path, category in examples.items():
        assert classify_hotpath(path) == category
        assert "57" not in category and "private" not in category
    assert classify_hotpath("/health") is None
    assert classify_hotpath("/api/clients/57") is None
    assert classify_hotpath("/api/unknown/clients/57?secret=raw") is None


def test_summary_uses_only_bounded_counters_and_never_logs_dynamic_paths_or_secrets() -> None:
    clock = [100.0]
    logs = []
    monitor = HotpathDatabaseTelemetry(
        clock=lambda: clock[0], interval_seconds=900, emit=logs.append
    )
    secret = "client-id-57-secret-token-not-for-logs"
    metrics = SimpleNamespace(statement_count=3, select_count=2, checkout_count=1, duration_ms=4.3333)
    monitor.record(f"/api/terminal-agent/clients/57/http/{secret}/poll", 200, metrics)
    monitor.record("/api/terminal-agent/clients/56/http/private/poll", 401, metrics)
    monitor.record("/api/clients/57", 500, metrics)  # deliberately excluded
    assert logs == []
    clock[0] += 900
    monitor.record("/api/clientflow-update/token", 200, metrics)
    assert len(logs) == 1
    assert secret not in logs[0]
    assert "/api/" not in logs[0]
    assert "57" not in logs[0]
    snapshot = json.loads(logs[0])
    assert snapshot == {
        "window_seconds": 900,
        "categories": {
            "terminal_relay": {
                "requests": 2,
                "failed_http": 1,
                "statements": 6,
                "selects": 4,
                "checkouts": 2,
                "cursor_ms": 8.67,
                "max_statements": 3,
            },
        },
    }
    clock[0] += 900
    monitor.record("/api/clientflow-update/token", 200, metrics)
    assert len(logs) == 2
    assert list(json.loads(logs[1])["categories"]) == ["updater_token"]


def test_unmatched_traffic_does_not_flush_or_build_up_metrics() -> None:
    clock = [0.0]
    logs = []
    monitor = HotpathDatabaseTelemetry(clock=lambda: clock[0], interval_seconds=900, emit=logs.append)
    metrics = SimpleNamespace(statement_count=0, select_count=0, checkout_count=0, duration_ms=0)
    for _ in range(200):
        monitor.record("/health", 200, metrics)
    clock[0] = 901
    monitor.record("/api/clients/23", 200, metrics)
    assert logs == []
    monitor.record("/api/livestream-agent/clients/23/presence", 200, metrics)
    assert logs == []
