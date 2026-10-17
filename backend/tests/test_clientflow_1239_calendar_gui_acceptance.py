"""Runtime regressions for calendar daily reboot and GTK copy controls."""
from __future__ import annotations

import ast
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/runtime"))
from clientflow_runtime import calendar_agent as calendar  # noqa: E402


TODAY = datetime(2026, 10, 15, 8, 0).astimezone().timestamp()
YESTERDAY = TODAY - 86400


def test_calendar_day_reboot_guard_prevents_restarts_after_any_boot_today():
    assert not calendar._calendar_reboot_required({}, now_epoch=TODAY, boot_epoch=TODAY - 60)
    assert calendar._calendar_reboot_required({}, now_epoch=TODAY, boot_epoch=YESTERDAY)
    attempted = {"last_wake_reboot_day": calendar._local_day(TODAY)}
    assert not calendar._calendar_reboot_required(attempted, now_epoch=TODAY, boot_epoch=YESTERDAY)
    assert not calendar._calendar_reboot_required({}, now_epoch=TODAY, boot_epoch=None)
    # Same calendar date, previous boot 24 hours ago but next midnight could be within 24h.
    assert not calendar._calendar_reboot_required(
        {"last_wake_reboot_at": TODAY - 60}, now_epoch=TODAY, boot_epoch=YESTERDAY
    )


def test_calendar_reboot_request_is_persisted_before_reboot_and_never_starts_browser(monkeypatch):
    calls = []
    state = {"last_wake_reboot_at": 0}
    monkeypatch.setattr(calendar, "_boot_evidence", lambda: ("previous-boot", YESTERDAY))
    monkeypatch.setattr(calendar, "_save_scheduler_state", lambda st: calls.append(("save", dict(st))))
    monkeypatch.setattr(calendar, "_request_calendar_reboot", lambda: calls.append(("request", None)))
    monkeypatch.setattr(calendar, "display_control_lock", nullcontext)
    monkeypatch.setattr(calendar, "set_display_power", lambda action: calls.append(("power", action)))
    monkeypatch.setattr(calendar, "runtime_action", lambda action, **kw: calls.append(("browser", action)))
    calendar._apply_calendar_state("on", state=state, now_epoch=TODAY)
    assert [entry[0] for entry in calls] == ["save", "request"]
    assert state["last_wake_reboot_day"] == calendar._local_day(TODAY)
    assert state["last_wake_reboot_boot_id"] == "previous-boot"


def test_calendar_manual_or_post_boot_wake_never_requests_reboot(monkeypatch):
    calls = []
    monkeypatch.setattr(calendar, "_boot_evidence", lambda: ("new-boot", TODAY - 30))
    monkeypatch.setattr(calendar, "_request_calendar_reboot", lambda: pytest.fail("Unexpected reboot"))
    monkeypatch.setattr(calendar, "display_control_lock", nullcontext)
    monkeypatch.setattr(calendar, "set_display_power", lambda action: calls.append(action))
    monkeypatch.setattr(calendar, "runtime_action", lambda action, **kw: calls.append(action))
    calendar._apply_calendar_state("on", state={}, now_epoch=TODAY)
    calendar._apply_calendar_state("on", state={}, now_epoch=TODAY, initial=True)
    assert calls == ["on", "start_browser"]


def test_calendar_broker_failure_cannot_cause_a_second_daily_reboot(monkeypatch):
    state = {}
    calls = []
    monkeypatch.setattr(calendar, "_boot_evidence", lambda: ("previous-boot", YESTERDAY))
    monkeypatch.setattr(calendar, "_save_scheduler_state", lambda st: calls.append(("save", dict(st))))
    monkeypatch.setattr(calendar, "_request_calendar_reboot", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(calendar, "display_control_lock", nullcontext)
    monkeypatch.setattr(calendar, "set_display_power", lambda mode: calls.append(("power", mode)))
    monkeypatch.setattr(calendar, "runtime_action", lambda action, **kw: calls.append(("browser", action)))
    with pytest.raises(RuntimeError):
        calendar._apply_calendar_state("on", state=state, now_epoch=TODAY)
    assert state["last_wake_reboot_error"] == "reboot_request_failed"
    assert not calendar._calendar_reboot_required(state, now_epoch=TODAY, boot_epoch=YESTERDAY)
    assert ("power", "on") in calls and ("browser", "start_browser") in calls


class FakeLabel:
    def __init__(self, text):
        self.text = text
        self.classes = set()

    def get_text(self):
        return self.text

    def set_text(self, value):
        self.text = value

    def remove_css_class(self, value):
        self.classes.discard(value)

    def add_css_class(self, value):
        self.classes.add(value)


class FakeButton:
    def __init__(self):
        self.visible = True

    def set_visible(self, value):
        self.visible = value


class FakeClipboard:
    def __init__(self):
        self.value = ""

    # This fake models the real PyGObject GTK4 binding on Ubuntu 26.04:
    # GdkWaylandClipboard has set(value), not set_text(value).
    def set(self, value):
        self.value = value

    def read_text_async(self, _cancellable, callback):
        callback(self, object())

    def read_text_finish(self, _result):
        return self.value


def _gtk_copy_window():
    """Compile the actual GTK methods against a fake clipboard; no display required."""
    source = ast.parse((ROOT / "client/libexec/local-gui").read_text(encoding="utf-8"))
    klass = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "ClientFlowWindow")
    selected = [node for node in klass.body if isinstance(node, ast.FunctionDef)
                and node.name in {"_copy", "_set", "_can_copy_value"}]
    code = compile(ast.fix_missing_locations(ast.Module(
        body=[ast.ClassDef(name="Gui", bases=[], keywords=[], body=selected, decorator_list=[])],
        type_ignores=[])), "gtk-tests", "exec")
    clipboard = FakeClipboard()
    class Display:
        @staticmethod
        def get_clipboard():
            return clipboard
    class Gdk:
        class Display:
            @staticmethod
            def get_default():
                return Display()
        Clipboard = FakeClipboard
    class GLib:
        Error = RuntimeError
        @staticmethod
        def timeout_add(_delay, callback):
            return callback()
    ns = {"Gdk": Gdk, "GLib": GLib}
    exec(code, ns)
    window = ns["Gui"]()
    window.labels = {"kiosk_url": FakeLabel(""), "active_ip": FakeLabel("")}
    window.copy_values = {}
    window.copy_buttons = {"kiosk_url": FakeButton(), "active_ip": FakeButton()}
    window.copy_ok = {"kiosk_url": FakeLabel(""), "active_ip": FakeLabel("")}
    window.error_label = FakeLabel("")
    window._color_class = lambda _color: None
    return window, clipboard


def test_copy_controls_use_visible_gtk_value_and_hide_placeholders():
    window, clipboard = _gtk_copy_window()
    window._set("active_ip", "-")
    assert window.copy_buttons["active_ip"].visible is False
    window._set("active_ip", "Ikke tilsluttet")
    assert window.copy_buttons["active_ip"].visible is False
    window._set("kiosk_url", "Afventer godkendelse / ingen kiosk-URL endnu")
    assert window.copy_buttons["kiosk_url"].visible is False
    url = "https://eksempel.dk/fuld/url?lang=da"
    window._set("kiosk_url", url)
    assert window.copy_buttons["kiosk_url"].visible
    window.copy_values.clear()  # previously exposed an empty cache on Viborg1
    window._copy("kiosk_url")
    assert clipboard.value == url
    window._set("active_ip", "192.168.126.180")
    assert window.copy_buttons["active_ip"].visible
    window._copy("active_ip")
    assert clipboard.value == "192.168.126.180"


def test_copy_control_does_not_require_unavailable_gdk_set_text():
    window, clipboard = _gtk_copy_window()
    assert not hasattr(clipboard, "set_text")
    window._set("active_ip", "192.168.126.180")
    window._copy("active_ip")
    assert clipboard.value == "192.168.126.180"
    assert window.copy_ok["active_ip"].get_text() == ""
    assert window.error_label.get_text() == ""


def test_copy_control_reports_clipboard_failure_without_crashing():
    window, clipboard = _gtk_copy_window()
    window._set("active_ip", "192.168.126.180")
    def unavailable(_value):
        raise TypeError("clipboard backend unavailable")
    clipboard.set = unavailable
    window._copy("active_ip")
    assert "Kopiering fejlede:" in window.error_label.get_text()


def test_post_boot_browser_reconciliation_runs_exactly_once_per_new_boot():
    state = {
        "last_wake_reboot_day": calendar._local_day(TODAY),
        "last_wake_reboot_boot_id": "before",
    }
    check = lambda boot: calendar._needs_post_reboot_reconciliation(
        state, desired="on", previous="on", now_epoch=TODAY, current_boot_id=boot
    )
    assert not check("before")
    assert check("after")
    state["post_reboot_ready_boot_id"] = "after"
    assert not check("after")
    assert not calendar._needs_post_reboot_reconciliation(
        state, desired="off", previous="on", now_epoch=TODAY, current_boot_id="new"
    )
