"""Keep quick-settings enforcement functional inside its no-new-privileges sandbox.

A physical Ubuntu 26.04 client reported runuser failing with EPERM while the
periodic kiosk-session policy (outside this sandbox) remained healthy.
"""

from pathlib import Path
import pwd
import subprocess

import pytest

from clientflow_runtime import kiosk_quicksettings_guard as guard
from clientflow_runtime import kiosk_session_policy as policy

ROOT = Path(__file__).resolve().parents[2]


def _kiosk_record() -> pwd.struct_passwd:
    return pwd.struct_passwd(
        ("clientflow-kiosk", "x", 1001, 1001, "", "/home/clientflow-kiosk", "/bin/sh")
    )


def test_quick_guard_uses_direct_privilege_drop_without_changing_periodic_policy(monkeypatch):
    calls: list[dict[str, bool]] = []
    states = iter([True, False])
    monkeypatch.setattr(guard, "_desired", lambda: next(states))
    monkeypatch.setattr(guard.kiosk_session_policy, "enforce", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(guard.time, "sleep", lambda _: None)

    guard.run()

    assert calls == [{"lockdown_quicksettings": True, "use_setpriv": True}]


def test_direct_privilege_drop_is_fixed_user_and_removes_child_capabilities():
    record = _kiosk_record()
    program = [str(policy.GSETTINGS), "set", "org.gnome.desktop.lockdown", "disable-command-line", "true"]
    command = policy._user_command(record, program, use_setpriv=True)
    assert command == [
        str(policy.SETPRIV),
        "--reuid=1001",
        "--regid=1001",
        "--init-groups",
        "--inh-caps=-all",
        "--bounding-set=-all",
        "--no-new-privs",
        "env",
        "HOME=/home/clientflow-kiosk",
        "XDG_RUNTIME_DIR=/run/user/1001",
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/bus",
        *program,
    ]
    assert str(policy.RUNUSER) not in command

    # Existing working scheduled session policy must remain unchanged.
    periodic = policy._user_command(record, program)
    assert periodic[:4] == [str(policy.RUNUSER), "-u", "clientflow-kiosk", "--"]
    assert str(policy.SETPRIV) not in periodic


def test_missing_direct_drop_tool_fails_closed_before_enforcing(monkeypatch, tmp_path):
    monkeypatch.setattr(policy.os, "geteuid", lambda: 0)
    monkeypatch.setattr(policy, "SETPRIV", tmp_path / "setpriv-not-present")
    monkeypatch.setattr(policy, "_run", lambda *_args, **_kwargs: pytest.fail("Unexpected system mutation"))

    with pytest.raises(policy.KioskSessionPolicyError, match="setpriv-not-present"):
        policy.enforce(lockdown_quicksettings=True, use_setpriv=True)


def test_guard_keeps_original_systemd_hardening():
    quick = (ROOT / "client/systemd/clientflow-kiosk-quicksettings-guard.service").read_text(encoding="utf-8")
    periodic = (ROOT / "client/systemd/clientflow-kiosk-session-policy.service").read_text(encoding="utf-8")
    for required in (
        "User=root",
        "NoNewPrivileges=yes",
        "PrivateTmp=yes",
        "ProtectSystem=strict",
        "ProtectHome=read-only",
        "RestrictAddressFamilies=AF_UNIX AF_NETLINK",
    ):
        assert required in quick
    assert "NoNewPrivileges=no" in periodic


def test_guard_uses_fixed_user_switch_for_both_desktop_and_audio_commands(monkeypatch, tmp_path):
    record = _kiosk_record()
    monkeypatch.setattr(policy, "GSETTINGS", tmp_path / "gsettings")
    monkeypatch.setattr(policy, "WPCTL", tmp_path / "wpctl")
    for name in ("gsettings", "wpctl"):
        binary = tmp_path / name
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)

    original_exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: True if str(self) in {"/run/user/1001/bus", "/run/user/1001/pipewire-0"} else original_exists(self),
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        policy,
        "_run",
        lambda cmd, **_: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    policy._apply_gsettings(record, lockdown_quicksettings=True, use_setpriv=True)
    policy._apply_audio(record, use_setpriv=True)

    assert len(calls) >= 7
    assert all(cmd[:2] == [str(policy.SETPRIV), "--reuid=1001"] for cmd in calls)
    assert any(str(policy.GSETTINGS) in cmd for cmd in calls)
    assert any(str(policy.WPCTL) in cmd for cmd in calls)
    assert all(str(policy.RUNUSER) not in cmd for cmd in calls)
