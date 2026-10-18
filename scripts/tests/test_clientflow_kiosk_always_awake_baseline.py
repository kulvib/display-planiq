"""Protect the physical kiosk against GNOME five-minute blank/lock regression."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import pwd
from types import SimpleNamespace

import pytest
from clientflow_runtime import kiosk_lockdown as lockdown_module

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "client/runtime/clientflow_runtime"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, RUNTIME / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_platform_awake_settings_are_recurring_and_optional_rollback_cannot_reset_them():
    platform = _load("cf_display_platform_settings", "display_platform_prepare.py")
    lockdown = lockdown_module
    policy = _load("cf_recurring_kiosk_settings", "kiosk_session_policy.py")
    platform_map = {(schema, key): value for schema, key, value in platform._gsettings_commands()}
    always_awake = {(schema, key): value for schema, key, value in lockdown.KIOSK_DISPLAY_AWAKE_BASELINE}
    optional = {(schema, key) for schema, key, _value in lockdown.OPTIONAL_GSETTINGS}
    assert len(always_awake) >= 11
    assert not (optional & always_awake.keys())
    for setting, value in always_awake.items():
        assert platform_map.get(setting) == value
        assert setting in policy.CRITICAL_KIOSK_SETTINGS
    assert ("org.gnome.desktop.session", "idle-delay") in always_awake
    assert always_awake[("org.gnome.desktop.session", "idle-delay")] == "uint32 0"
    assert ("org.gnome.desktop.screensaver", "lock-enabled", "false") in lockdown.ENFORCED_GSETTINGS


def test_lockdown_disable_never_resets_critical_display_keys(monkeypatch):
    lockdown = lockdown_module
    calls = []
    monkeypatch.setattr(lockdown, "_gsettings_base", lambda *_args: ["gsettings"])
    monkeypatch.setattr(lockdown, "_run", lambda command, **_kwargs: calls.append(command))
    lockdown._apply_gsettings("clientflow-kiosk", SimpleNamespace(), False)
    reset = {(cmd[-2], cmd[-1]) for cmd in calls if "reset" in cmd}
    applied = {(cmd[-3], cmd[-2]): cmd[-1] for cmd in calls if "set" in cmd}
    for schema, key, value in lockdown.KIOSK_DISPLAY_AWAKE_BASELINE:
        assert (schema, key) not in reset
        assert applied[(schema, key)] == value
    assert applied[("org.gnome.desktop.notifications", "show-banners")] == "false"


def test_active_kiosk_recurring_policy_applies_and_verifies_critical_values(monkeypatch):
    policy = _load("cf_kiosk_awake_live", "kiosk_session_policy.py")
    record = pwd.struct_passwd(("clientflow-kiosk", "x", 1001, 1001, "", "/home/clientflow-kiosk", "/bin/bash"))
    # Only the bus-existence check is mocked; all commands are inspected.
    original_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self: True if str(self) == "/run/user/1001/bus" else original_exists(self))
    calls = []
    state = {}
    def fake_run(command, **_kwargs):
        calls.append(command)
        if "gsettings" in " ".join(command):
            op, schema, key = command[-4], command[-3], command[-2]
            # Set has four trailing tokens; get has three.
            if command[-4] == "set":
                state[(schema, key)] = command[-1]
            elif command[-3] == "get":
                return SimpleNamespace(returncode=0, stdout=state.get((command[-2], command[-1]), "") + "\n")
        return SimpleNamespace(returncode=0, stdout="")
    monkeypatch.setattr(policy, "_run", fake_run)
    policy._apply_gsettings(record)
    assert len(state) >= len(policy.CRITICAL_KIOSK_SETTINGS)
    assert {tuple(command[-2:]) for command in calls if "get" in command} == policy.CRITICAL_KIOSK_SETTINGS
    assert ("org.gnome.desktop.session", "idle-delay") in state
    assert state[("org.gnome.desktop.session", "idle-delay")] == "uint32 0"


def test_kiosk_recurring_policy_fails_if_gsettings_write_does_not_stick(monkeypatch):
    policy = _load("cf_kiosk_drift", "kiosk_session_policy.py")
    record = pwd.struct_passwd(("clientflow-kiosk", "x", 1001, 1001, "", "/home/clientflow-kiosk", "/bin/bash"))
    original_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self: True if str(self) == "/run/user/1001/bus" else original_exists(self))
    monkeypatch.setattr(policy, "_run", lambda _cmd, **_kw: SimpleNamespace(returncode=0, stdout="uint32 300\n"))
    with pytest.raises(policy.KioskSessionPolicyError, match="GNOME kiosk baseline drift"):
        policy._apply_gsettings(record)


def test_kiosk_policy_retries_before_default_five_minute_idle_timeout():
    timer = (ROOT / "client/systemd/clientflow-kiosk-session-policy.timer").read_text()
    assert "OnBootSec=30s" in timer
    assert "OnUnitActiveSec=1min" in timer
    assert "AccuracySec=10s" in timer


def test_chrome_and_gnome_popup_guards_remain_enabled():
    runtime = (RUNTIME / "display_runtime.py").read_text()
    platform = (RUNTIME / "display_platform_prepare.py").read_text()
    recurring = (RUNTIME / "kiosk_session_policy.py").read_text()
    for flag in ('"--disable-notifications"', '"--disable-infobars"'):
        assert flag in runtime
    assert '"notifications": 2' in runtime
    assert '"popups": 2' in runtime
    assert '"Hidden=true\\n"' in platform
    assert '("org.gnome.desktop.notifications", "show-banners", "false")' in recurring
    assert '("org.gnome.desktop.notifications", "show-in-lock-screen", "false")' in recurring
