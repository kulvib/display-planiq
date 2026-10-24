"""Fail-closed kiosk internet authority without physical network or Chrome."""
from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/runtime"))

from clientflow_runtime import display_internet, display_readiness, display_runtime  # noqa: E402


class _Executor:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def submit(self, fn, url):
        self.calls.append((fn, url))
        future: Future = Future()
        future.set_result(next(self.outcomes))
        return future


def test_monitor_blocks_initial_start_and_requires_sustained_success():
    monitor = display_internet.InternetMonitor()
    executor = _Executor([False, True, True])
    assert monitor.online is False
    monitor.tick(executor, "https://example.org/x", now=0)
    monitor.tick(executor, "https://example.org/x", now=1)
    assert monitor.state == "offline" and monitor.online is False
    monitor.tick(executor, "https://example.org/x", now=10)
    monitor.tick(executor, "https://example.org/x", now=11)
    assert monitor.state == "checking" and monitor.online is False
    monitor.tick(executor, "https://example.org/x", now=20)
    monitor.tick(executor, "https://example.org/x", now=21)
    assert monitor.state == "online" and monitor.online is True


def test_brief_network_outage_keeps_browser_online_then_closes_after_grace():
    monitor = display_internet.InternetMonitor()
    executor = _Executor([True, True, False, False, False])
    for now in (0, 1, 10, 11):
        monitor.tick(executor, "https://example.org", now=now)
    assert monitor.online is True
    for now in (20, 21, 30, 31):
        monitor.tick(executor, "https://example.org", now=now)
        assert monitor.online is True
    for now in (40, 41):
        monitor.tick(executor, "https://example.org", now=now)
    assert monitor.online is False and monitor.state == "offline"


def test_link_switch_does_not_close_browser_if_https_stays_up():
    monitor = display_internet.InternetMonitor()
    executor = _Executor([True, True, True, True])
    for now in (0, 1, 10, 11, 20, 21, 30, 31):
        monitor.tick(executor, "https://example.org", now=now)
    assert monitor.online is True
    # We don't inspect WiFi/ethernet link names: the active route is authoritative.
    assert len(executor.calls) == 4


def test_https_probe_does_not_send_kiosk_path_or_query_and_disallows_local_http(monkeypatch):
    requested = []

    class _Response:
        status = 204
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    class _Opener:
        def open(self, req, timeout):
            requested.append((req.full_url, req.get_method(), timeout))
            return _Response()

    monkeypatch.setattr(display_internet, "build_opener", lambda *handlers: _Opener())
    assert display_internet._kiosk_origin("https://example.org/private/token?secret=abc") == "https://example.org/"
    assert display_internet._kiosk_origin("http://localhost:8888/app") is None
    assert display_internet.probe_internet("https://example.org/private/token?secret=abc")
    assert requested == [(display_internet.BACKEND_PROBE_URL, "HEAD", display_internet.REQUEST_TIMEOUT_SECONDS)]


def test_offline_probe_falls_back_to_kiosk_https_origin(monkeypatch):
    from urllib.error import URLError
    calls = []
    class _Response:
        status = 204
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    class _Opener:
        def open(self, req, timeout):
            calls.append(req.full_url)
            if req.full_url == display_internet.BACKEND_PROBE_URL:
                raise URLError("backend unavailable")
            return _Response()
    monkeypatch.setattr(display_internet, "build_opener", lambda *handlers: _Opener())
    assert display_internet.probe_internet("https://content.example/secure/token?access=private")
    assert calls == [display_internet.BACKEND_PROBE_URL, "https://content.example/"]


def _runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(display_runtime, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(display_runtime, "STATUS_PATH", tmp_path / "runtime.json")
    monkeypatch.setattr(display_runtime, "PID_PATH", tmp_path / "browser.pid")
    runtime = display_runtime.DisplayRuntime()
    runtime.configuration = {"schema_version": 1, "revision": 1, "kiosk_url": "https://example.org"}
    runtime.browser_requested = True
    monkeypatch.setattr(runtime, "_status", lambda state, **kw: setattr(runtime, "_last_status_payload", {"state": state, **kw}))
    return runtime


def test_no_chrome_launch_while_offline_even_after_explicit_manual_start(monkeypatch, tmp_path):
    runtime = _runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime, "_browser_command", lambda: (_ for _ in ()).throw(AssertionError("Chrome must not launch")))
    result = runtime.request_start_browser(source="gui")
    assert result["waiting_for_internet"] is True
    assert runtime.browser_requested is True and runtime.browser is None
    assert runtime._last_status_payload["state"] == "waiting_internet"
    assert runtime.boot_start_pending is False


def test_connection_loss_closes_browser_once_preserves_request_and_does_not_erase_profile(monkeypatch, tmp_path):
    runtime = _runtime(monkeypatch, tmp_path)
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    (profile / "Cookies").write_text("consent")
    runtime.internet.online = True
    runtime.internet.state = "online"
    runtime.browser = SimpleNamespace(pid=1234, poll=lambda: None)
    runtime.internet.tick = lambda *args, **kwargs: setattr(runtime.internet, "online", False) or setattr(runtime.internet, "state", "offline") or True
    terminated = []
    monkeypatch.setattr(display_runtime.os, "killpg", lambda pid, signal: terminated.append(pid))
    runtime.browser.wait = lambda timeout: 0
    runtime._tick_internet(_Executor([]))
    assert terminated == [1234]
    assert runtime.browser is None and runtime.browser_requested is True
    assert runtime._last_status_payload["state"] == "waiting_internet"
    assert (profile / "Cookies").read_text() == "consent"


def test_manual_or_calendar_stop_never_automatically_recovers(monkeypatch, tmp_path):
    runtime = _runtime(monkeypatch, tmp_path)
    runtime.stop_browser(source="calendar")
    assert runtime.browser_requested is False
    runtime.internet.tick = lambda *_args, **_kw: setattr(runtime.internet, "online", True) or setattr(runtime.internet, "state", "online") or True
    monkeypatch.setattr(display_runtime, "atomic_write_shared_json", lambda *_args, **_kw: None)
    runtime._tick_internet(_Executor([]))
    assert runtime.browser_requested is False
    assert runtime._last_status_payload["state"] == "stopped"
    assert runtime._last_status_payload["step"] == "chrome_closed_programmatically"
    assert runtime._last_status_payload["event_source"] == "calendar"


def test_recovery_restarts_only_requested_browser_without_erasing_cookies(monkeypatch, tmp_path):
    runtime = _runtime(monkeypatch, tmp_path)
    runtime.boot_start_pending = True
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "Cookies").write_text("approved-consent")
    monkeypatch.setattr(runtime, "_countdown", lambda *args, **kw: None)
    starts = []
    monkeypatch.setattr(runtime, "start_browser", lambda **kw: starts.append(kw) or {"started": True, "pid": 88})
    monkeypatch.setattr(runtime, "_boot_start_required", lambda: False)
    runtime.internet.online = False
    assert runtime._start_browser_with_boot_policy()["waiting_for_internet"] is True
    assert runtime.boot_start_pending is True
    assert not starts
    runtime.internet.online = True
    assert runtime._start_browser_with_boot_policy()["started"] is True
    assert runtime.boot_start_pending is False
    assert len(starts) == 1
    assert (profile / "Cookies").read_text() == "approved-consent"


def test_manual_start_during_outage_does_not_run_countdown(monkeypatch, tmp_path):
    runtime = _runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime, "_countdown", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No countdown without internet")))
    assert runtime.request_start_browser(source="backend")["waiting_for_internet"] is True


def test_status_with_no_browser_preserves_manual_stop_across_link_transitions(monkeypatch, tmp_path):
    runtime = _runtime(monkeypatch, tmp_path)
    runtime.stop_browser(source="gui")
    assert runtime.browser_requested is False
    monkeypatch.setattr(display_runtime, "atomic_write_shared_json", lambda *_args, **_kw: None)
    runtime.internet.tick = lambda *_args, **_kw: setattr(runtime.internet, "state", "offline") or True
    runtime._tick_internet(_Executor([]))
    assert runtime._last_status_payload["event_source"] == "gui"
    assert runtime._last_status_payload["step"] == "chrome_closed_programmatically"


def test_offline_readiness_requires_session_and_gui_and_unspawned_browser(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    status = tmp_path / "runtime.json"
    config.write_text('{"kiosk_url":"https://example.org"}')
    monkeypatch.setattr(display_readiness, "CONFIG_PATH", config)
    monkeypatch.setattr(display_readiness, "STATUS_PATH", status)
    monkeypatch.setattr(display_readiness, "_active_kiosk_session", lambda: True)
    monkeypatch.setattr(display_readiness, "_local_gui_ready", lambda: True)
    import time
    payload = {"state": "waiting_internet", "browser_pid": None, "browser_requested": True,
               "internet_access": "offline", "updated_at": time.time()}
    import json
    status.write_text(json.dumps(payload))
    assert display_readiness.ready()
    payload["internet_access"] = "online"
    status.write_text(json.dumps(payload))
    assert not display_readiness.ready()
    payload["internet_access"] = "offline"
    payload["browser_pid"] = 1234
    status.write_text(json.dumps(payload))
    assert not display_readiness.ready()
    payload["browser_pid"] = None
    payload["updated_at"] = time.time() - 60
    status.write_text(json.dumps(payload))
    assert not display_readiness.ready()


def test_source_projection_and_gui_status_share_the_same_waiting_internet_label():
    backend = (ROOT / "backend/service1/display_control.py").read_text()
    gui = (ROOT / "client/libexec/local-gui").read_text()
    assert 'if state == "waiting_internet":' in backend
    assert 'if state == "waiting_internet":' in gui
    assert "Kiosk browser afventer internetforbindelse…" in backend
    assert "Kiosk browser afventer internetforbindelse…" in gui


def test_kiosk_probe_origin_rejects_embedded_credentials_and_bad_ports():
    # The fallback is an origin-only reachability check: auth-bearing URLs
    # must never be normalized into a request carrying those credentials.
    assert display_internet._kiosk_origin('https://user:secret@example.com/display?token=abc') is None
    assert display_internet._kiosk_origin('https://user@example.com/') is None
    assert display_internet._kiosk_origin('https://example.com:invalid/foo') is None
    assert display_internet._kiosk_origin('https://[2001:db8::1]:443/x?sig=secret') == 'https://[2001:db8::1]:443/'
    assert display_internet._kiosk_origin('https://example.org/x?q=secret#fragment') == 'https://example.org/'
