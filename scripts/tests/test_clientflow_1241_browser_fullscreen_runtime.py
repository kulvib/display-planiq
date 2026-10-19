"""Regression tests: verified kiosk Chrome fullscreen and safe unknown fallback."""
from __future__ import annotations

from concurrent.futures import Future
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "client" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from clientflow_runtime import browser_fullscreen, display_runtime  # noqa: E402


@pytest.mark.parametrize("cdp_state,expected", [
    ("fullscreen", "fullscreen"),
    ("normal", "windowed"),
    ("maximized", "windowed"),
    ("minimized", "windowed"),
])
def test_cdp_window_states_are_measured_without_guessing(cdp_state, expected, monkeypatch):
    async def fake_state(_socket, _target):
        return "fullscreen" if cdp_state == "fullscreen" else "windowed"

    monkeypatch.setattr(browser_fullscreen, "_read_json", lambda path: (
        {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/1"}
        if path == "/json/version" else [{"type": "page", "id": "page-1"}]
    ))
    monkeypatch.setattr(browser_fullscreen, "_window_state", fake_state)
    assert browser_fullscreen.probe_browser_fullscreen() == expected


@pytest.mark.parametrize("socket", [
    "ws://example.com:9222/devtools/browser/1",
    "ws://127.0.0.1:9223/devtools/browser/1",
    "wss://127.0.0.1:9222/devtools/browser/1",
    "ws://127.0.0.1:9222/devtools/page/1",
    "ws://root@127.0.0.1:9222/devtools/browser/1",
])
def test_cdp_socket_must_remain_loopback_and_browser_only(socket):
    with pytest.raises(ValueError):
        browser_fullscreen._validated_browser_socket(socket)


@pytest.mark.parametrize("pages", [[], ["one", "two"]])
def test_no_or_ambiguous_pages_return_unknown(monkeypatch, pages):
    monkeypatch.setattr(browser_fullscreen, "_read_json", lambda path: (
        {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/1"}
        if path == "/json/version" else [{"type": "page", "id": x} for x in pages]
    ))
    assert browser_fullscreen.probe_browser_fullscreen() == "unknown"


def test_inaccessible_cdp_returns_unknown(monkeypatch):
    def inaccessible(_path):
        raise OSError("Chrome has stopped")
    monkeypatch.setattr(browser_fullscreen, "_read_json", inaccessible)
    assert browser_fullscreen.probe_browser_fullscreen() == "unknown"


def test_runtime_ignores_fullscreen_result_from_previous_chrome(monkeypatch):
    writes = []
    monkeypatch.setattr(display_runtime, "atomic_write_shared_json", lambda _path, payload, **_kw: writes.append(payload))
    instance = display_runtime.DisplayRuntime.__new__(display_runtime.DisplayRuntime)
    instance.configuration = {"revision": 1}
    instance.browser_requested = True
    instance.display_power = "on"
    instance.shared_group_gid = 100
    instance.browser = SimpleNamespace(pid=200, poll=lambda: None)
    instance.browser_fullscreen = "unknown"
    instance.browser_fullscreen_at = None
    instance.browser_fullscreen_pid = None
    instance.next_fullscreen_probe = float("inf")
    instance.fullscreen_future_pid = 199
    instance.fullscreen_future = Future()
    instance.fullscreen_future.set_result("fullscreen")
    instance._last_status_payload = {}
    instance._status("running", step="start_chrome", event_source="system_start")
    instance._poll_browser_fullscreen(None)
    assert writes[-1]["browser_fullscreen"] == "unknown"
    assert writes[-1]["step"] == "start_chrome"


def test_runtime_accepts_current_pid_measurement_without_resetting_chrome_event(monkeypatch):
    writes = []
    monkeypatch.setattr(display_runtime, "atomic_write_shared_json", lambda _path, payload, **_kw: writes.append(payload))
    instance = display_runtime.DisplayRuntime.__new__(display_runtime.DisplayRuntime)
    instance.configuration = {"revision": 1}
    instance.browser_requested = True
    instance.display_power = "on"
    instance.shared_group_gid = 100
    instance.browser = SimpleNamespace(pid=200, poll=lambda: None)
    instance.browser_fullscreen = "unknown"
    instance.browser_fullscreen_at = None
    instance.browser_fullscreen_pid = None
    instance.next_fullscreen_probe = float("inf")
    instance.fullscreen_future_pid = 200
    instance.fullscreen_future = Future()
    instance.fullscreen_future.set_result("fullscreen")
    instance._last_status_payload = {}
    instance._status("running", step="start_chrome", event_source="system_start")
    previous_time = writes[-1]["updated_at"]
    instance._poll_browser_fullscreen(None)
    assert writes[-1]["browser_fullscreen"] == "fullscreen"
    assert writes[-1]["step"] == "start_chrome"
    assert writes[-1]["updated_at"] == previous_time
    assert writes[-1]["browser_fullscreen_updated_at"] > 0

@pytest.mark.parametrize("reply,expected", [
    ({"id": 1, "result": {"bounds": {"windowState": "fullscreen"}}}, "fullscreen"),
    ({"id": 1, "result": {"bounds": {"windowState": "normal"}}}, "windowed"),
    ({"id": 1, "result": {"bounds": {"windowState": "minimized"}}}, "windowed"),
])
def test_real_cdp_reply_and_ignored_event(monkeypatch, reply, expected):
    import asyncio
    import json

    class FakeSocket:
        def __init__(self):
            self.sent = []
            self.replies = [json.dumps({"method": "Target.targetInfoChanged"}), json.dumps(reply)]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def send(self, message):
            self.sent.append(json.loads(message))

        async def recv(self):
            return self.replies.pop(0)

    fake = FakeSocket()
    monkeypatch.setattr(browser_fullscreen.websockets, "connect", lambda *_a, **_kw: fake)
    measured = asyncio.run(browser_fullscreen._window_state("ws://127.0.0.1:9222/devtools/browser/1", "page-1"))
    assert measured == expected
    assert fake.sent == [{
        "id": 1, "method": "Browser.getWindowForTarget", "params": {"targetId": "page-1"}
    }]


def test_window_bounds_fallback_does_not_change_the_window(monkeypatch):
    import asyncio
    import json

    class FakeSocket:
        def __init__(self):
            self.sent = []
            self.replies = [
                json.dumps({"id": 1, "result": {"windowId": 7}}),
                json.dumps({"id": 2, "result": {"bounds": {"windowState": "fullscreen"}}}),
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def send(self, message):
            self.sent.append(json.loads(message))

        async def recv(self):
            return self.replies.pop(0)

    fake = FakeSocket()
    monkeypatch.setattr(browser_fullscreen.websockets, "connect", lambda *_a, **_kw: fake)
    result = asyncio.run(browser_fullscreen._window_state("ws://127.0.0.1:9222/devtools/browser/1", "page-1"))
    assert result == "fullscreen"
    assert [x["method"] for x in fake.sent] == ["Browser.getWindowForTarget", "Browser.getWindowBounds"]
