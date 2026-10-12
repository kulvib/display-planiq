"""Executable bounded status edge contract for short Display countdowns."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "client/runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from clientflow_runtime import display_agent, display_countdown_bridge, display_runtime  # noqa: E402


def _countdown(started: float, remaining: int, *, state: str = "countdown", reason: str = "system_start") -> dict:
    return {
        "state": state,
        "countdown_started_at": started,
        "countdown_total_seconds": 10,
        "countdown_remaining": remaining,
        "countdown_reason": reason,
        "updated_at": started + (10 - remaining),
    }


def test_runtime_all_ticks_share_a_stable_start_identity(monkeypatch):
    statuses = []
    runtime = display_runtime.DisplayRuntime()
    monkeypatch.setattr(runtime, "_status", lambda state, **details: statuses.append({"state": state, **details}))
    monkeypatch.setattr(display_runtime.time, "sleep", lambda _: None)
    runtime._countdown("countdown", 10, reason="system_start")
    assert [s["countdown_remaining"] for s in statuses] == list(range(10, 0, -1))
    assert len({s["countdown_started_at"] for s in statuses}) == 1
    assert all(s["countdown_total_seconds"] == 10 for s in statuses)


def test_bridge_sends_one_start_and_one_completion_not_each_tick(tmp_path):
    path = tmp_path / "runtime-status.json"
    sent = []
    bridge = display_countdown_bridge.CountdownStatusBridge(
        path, lambda phase, token: sent.append((phase, token)), logger=logging.getLogger("test"), now=lambda: 1100,
    )
    bridge.inspect_once()
    assert sent == []
    for remaining in range(10, 0, -1):
        path.write_text(json.dumps(_countdown(1091, remaining)), encoding="utf-8")
        bridge.inspect_once()
    assert sent == [("started", "1091.0")]
    path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
    bridge.inspect_once()
    bridge.inspect_once()
    assert sent == [("started", "1091.0"), ("finished", "1091.0")]


def test_bridge_recognizes_next_countdown_without_extra_heartbeat(tmp_path):
    path = tmp_path / "runtime-status.json"
    sent = []
    bridge = display_countdown_bridge.CountdownStatusBridge(
        path, lambda phase, token: sent.append((phase, token)), logger=logging.getLogger("test"), now=lambda: 1100,
    )
    path.write_text(json.dumps(_countdown(1098, 10)), encoding="utf-8")
    bridge.inspect_once()
    # Two operations can arrive back to back before the watcher sees an idle state.
    path.write_text(json.dumps(_countdown(1099, 10, reason="reset_browser")), encoding="utf-8")
    bridge.inspect_once()
    assert sent == [("started", "1098.0"), ("started", "1099.0")]


def test_malformed_old_future_and_partial_status_never_report(tmp_path):
    path = tmp_path / "runtime-status.json"
    sent = []
    bridge = display_countdown_bridge.CountdownStatusBridge(
        path, lambda phase, token: sent.append((phase, token)), logger=logging.getLogger("test"), now=lambda: 1100,
    )
    samples = [
        {**_countdown(1000, 9)},
        {**_countdown(1102, 9)},
        {**_countdown(1099, 9), "countdown_total_seconds": 100000},
        {**_countdown(1099, 9), "countdown_total_seconds": True},
        {**_countdown(1099, 9), "countdown_remaining": "9"},
        {**_countdown(1099, 9), "countdown_started_at": float("nan")},
        {**_countdown(1099, 9), "updated_at": 1080},
    ]
    for data in samples:
        path.write_text(json.dumps(data), encoding="utf-8")
        bridge.inspect_once()
    path.write_text("{bad json", encoding="utf-8")
    bridge.inspect_once()
    assert sent == []


def test_broken_network_does_not_trigger_one_request_per_second(tmp_path):
    path = tmp_path / "runtime-status.json"
    attempts = []

    def fail(phase, token):
        attempts.append((phase, token))
        raise OSError("offline")

    bridge = display_countdown_bridge.CountdownStatusBridge(
        path, fail, logger=logging.getLogger("test"), now=lambda: 1100,
    )
    for remaining in range(10, 0, -1):
        path.write_text(json.dumps(_countdown(1091, remaining)), encoding="utf-8")
        bridge.inspect_once()
    assert len(attempts) == 1


def test_sender_rejects_stale_start_or_stale_completion(monkeypatch):
    sent = []
    transport = SimpleNamespace()
    monkeypatch.setattr(display_agent, "report_status", lambda *a, **kw: sent.append(kw))
    monkeypatch.setattr(display_agent.time, "time", lambda: 1100)
    payload = {"runtime": _countdown(1099, 10)}
    monkeypatch.setattr(display_agent, "_status", lambda: payload)
    display_agent._send_countdown_transition(transport, "started", "1098.0")
    display_agent._send_countdown_transition(transport, "finished", "1099.0")
    assert sent == []
    display_agent._send_countdown_transition(transport, "started", "1099.0")
    assert len(sent) == 1 and sent[0]["observed_state"] == "online"
    payload = {"runtime": {"state": "running", "browser_pid": 42}}
    display_agent._send_countdown_transition(transport, "finished", "1099.0")
    assert len(sent) == 2 and sent[1]["payload"]["runtime"]["state"] == "running"
