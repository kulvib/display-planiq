"""63D-30: GNOME user-session RDP pilot; fail-closed rollback test battery.

No test starts RDP, installs systemd services, opens ports or changes any host
firewall rules; all physical interfaces are simulated in temporary paths.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import clientflow_63d30_local_rdp_pilot as pilot


class Result:
    def __init__(self, code=0, stdout=""):
        self.returncode = code
        self.stdout = stdout


def test_source_guard_is_pinned_to_physically_recovered_63d29_version():
    source = Path(pilot.guard.__file__).read_bytes()
    assert hashlib.sha256(source).hexdigest() == pilot.EXPECTED_GUARD_SHA256


def test_root_watchdog_recurs_across_reboot_and_uses_no_time_bomb_that_removes_only_firewall():
    assert "OnCalendar=*-*-* *:*:00" in pilot.TIMER
    assert "Persistent=true" in pilot.TIMER
    assert "WantedBy=timers.target" in pilot.TIMER
    assert "ExecStart=/usr/bin/python3" in pilot.SERVICE
    assert " tick" in pilot.SERVICE
    assert "ExecStop=" not in pilot.SERVICE
    assert "rdp enable" not in pilot.SERVICE
    assert "nft delete" not in pilot.SERVICE
    assert pilot.MAX_SECONDS == 360


def test_baseline_matches_physical_kiosk_and_rejects_unexpected_user_changes(monkeypatch):
    state = dict(pilot.EXPECTED_BASE)
    monkeypatch.setattr(pilot, "get_setting", lambda uid, key: state[key])
    monkeypatch.setattr(pilot, "credentials_empty", lambda uid: True)
    calls = []
    monkeypatch.setattr(pilot.guard, "ensure_rdp_off", lambda uid: calls.append(uid))
    assert pilot.read_baseline(1000) == pilot.EXPECTED_BASE
    assert calls == ["1000"]
    state["view-only"] = "false"
    with pytest.raises(RuntimeError, match="STOP"):
        pilot.read_baseline(1000)
    state["view-only"] = "true"
    monkeypatch.setattr(pilot, "credentials_empty", lambda uid: False)
    with pytest.raises(RuntimeError, match="credentials"):
        pilot.read_baseline(1000)


def test_credentials_are_parsed_without_showing_or_storing_secrets(monkeypatch):
    monkeypatch.setattr(
        pilot, "kiosk",
        lambda uid, *args, **kw: Result(stdout=(
            "RDP:\n"
            " Username: (empty)\n"
            " Password: (empty)\n"
        )),
    )
    assert pilot.credentials_empty(1000)
    monkeypatch.setattr(
        pilot, "kiosk",
        lambda uid, *args, **kw: Result(stdout=(
            " Username: (hidden)\n Password: (hidden)\n"
        )),
    )
    assert not pilot.credentials_empty(1000)
    monkeypatch.setattr(pilot, "kiosk", lambda uid, *args, **kw: Result(stdout=""))
    assert not pilot.credentials_empty(1000)


def test_deadline_fires_on_walltime_monotonic_or_new_boot(monkeypatch):
    monkeypatch.setattr(pilot, "boot_id", lambda: "boot-1")
    monkeypatch.setattr(pilot.time, "time", lambda: 100)
    monkeypatch.setattr(pilot.time, "monotonic", lambda: 20)
    baseline = {"boot_id": "boot-1", "deadline_wall": 101, "deadline_mono": 21}
    assert not pilot.deadline_expired(baseline)
    assert pilot.deadline_expired({**baseline, "boot_id": "boot-2"})
    assert pilot.deadline_expired({**baseline, "deadline_wall": 100})
    assert pilot.deadline_expired({**baseline, "deadline_mono": 20})


def test_tick_retains_guard_until_deadline_and_uses_stop_after_reboot(monkeypatch):
    events = []
    monkeypatch.setattr(pilot, "state_load", lambda: {"phase": "63D-30"})
    monkeypatch.setattr(pilot, "deadline_expired", lambda data: False)
    monkeypatch.setattr(pilot, "stop", lambda: events.append("RDP-first cleanup"))
    pilot.tick()
    assert events == []
    monkeypatch.setattr(pilot, "deadline_expired", lambda data: True)
    pilot.tick()
    assert events == ["RDP-first cleanup"]


def test_state_symlink_is_rejected_not_treated_as_missing(monkeypatch, tmp_path):
    actual = tmp_path / "state.json"
    actual.write_text('{"phase":"63D-30"}')
    symlink = tmp_path / "link.json"
    symlink.symlink_to(actual)
    monkeypatch.setattr(pilot, "STATE_FILE", symlink)
    with pytest.raises(RuntimeError, match="symlink"):
        pilot.state_load()


def test_start_arms_and_verifies_firewall_before_any_GNOME_change(monkeypatch, tmp_path, capsys):
    state_dir = tmp_path / "pilot"
    secret_dir = tmp_path / "secret"
    monkeypatch.setattr(pilot, "STATE_ROOT", state_dir)
    monkeypatch.setattr(pilot, "STATE_FILE", state_dir / "state.json")
    monkeypatch.setattr(pilot, "SECRET_ROOT", secret_dir)
    monkeypatch.setattr(pilot, "SECRET_FILE", secret_dir / "credentials")
    monkeypatch.setattr(pilot, "STAGED_RUNNER", Path(pilot.__file__).resolve())
    monkeypatch.setattr(pilot, "target", lambda: (1000, tmp_path))
    monkeypatch.setattr(pilot, "watchdog_verified", lambda: True)
    monkeypatch.setattr(pilot, "read_baseline", lambda uid: dict(pilot.EXPECTED_BASE))
    monkeypatch.setattr(pilot, "boot_id", lambda: "current-boot")
    monkeypatch.setattr(pilot.guard, "guard_exists", lambda: False)
    events = []
    monkeypatch.setattr(pilot.guard, "install_guard", lambda uid: events.append("guard-install"))
    monkeypatch.setattr(pilot.guard, "guard_verified", lambda: True)
    monkeypatch.setattr(
        pilot, "stage_tls",
        lambda uid: (tmp_path / "cert.crt", tmp_path / "key.key"),
    )
    def fake_kiosk_ok(uid, *cmd, **kwargs):
        events.append(" ".join(cmd[:3]))
        if cmd[:3] == ("grdctl", "rdp", "set-credentials"):
            assert "input" in kwargs
            assert "\n" in kwargs["input"]
            assert len(cmd) == 3  # credentials must never appear in argv
    monkeypatch.setattr(pilot, "kiosk_ok", fake_kiosk_ok)
    monkeypatch.setattr(pilot, "get_setting", lambda uid, key:
                        {"screen-share-mode": "'mirror-primary'", "port": "uint16 3389"}[key])
    monkeypatch.setattr(pilot, "listeners", lambda: [3389])
    pilot.start()
    assert events[0] == "guard-install"
    assert events.index("guard-install") < events.index("grdctl rdp set-tls-key")
    assert events.index("grdctl rdp set-credentials") < events.index("grdctl rdp enable")
    assert (state_dir / "state.json").is_file()
    secret = (secret_dir / "credentials").read_text()
    assert len(secret.splitlines()) == 2
    assert secret.splitlines()[0] not in capsys.readouterr().out
    assert (secret_dir / "credentials").stat().st_mode & 0o777 == 0o600


def test_stop_never_removes_guard_until_rdp_disabled_and_settings_restored(
    monkeypatch, tmp_path,
):
    state_dir = tmp_path / "pilot"
    state_dir.mkdir()
    marker = state_dir / "state.json"
    marker.write_text(json.dumps({"phase": "63D-30", "baseline": pilot.EXPECTED_BASE}))
    monkeypatch.setattr(pilot, "STATE_ROOT", state_dir)
    monkeypatch.setattr(pilot, "STATE_FILE", marker)
    monkeypatch.setattr(pilot, "SECRET_ROOT", tmp_path / "secrets")
    monkeypatch.setattr(pilot, "SECRET_FILE", tmp_path / "secrets" / "credentials")
    monkeypatch.setattr(pilot, "tls_directory", lambda uid: tmp_path / "missing-tls")
    monkeypatch.setattr(pilot, "target", lambda: (1000, tmp_path))
    calls = []
    monkeypatch.setattr(pilot, "kiosk_ok", lambda uid, *args, **kwargs:
                        calls.append(" ".join(args[:3])))
    monkeypatch.setattr(pilot, "listeners", lambda: [])
    monkeypatch.setattr(pilot, "set_setting", lambda uid, key, value:
                        calls.append("restore-" + key))
    monkeypatch.setattr(pilot, "credentials_empty", lambda uid: True)
    monkeypatch.setattr(pilot.guard, "ensure_rdp_off",
                        lambda uid: calls.append("verified-off"))
    monkeypatch.setattr(pilot.guard, "guard_exists", lambda: True)
    monkeypatch.setattr(pilot.guard, "remove_guard",
                        lambda uid: calls.append("remove-guard"))
    monkeypatch.setattr(pilot, "unstage", lambda uid: calls.append("unstage"))
    pilot.stop()
    assert calls[:3] == [
        "gsettings set org.gnome.desktop.remote-desktop.rdp",
        "grdctl rdp disable",
        "systemctl --user disable",
    ]
    assert calls.index("grdctl rdp clear-credentials") < calls.index("remove-guard")
    assert calls.index("restore-tls-key") < calls.index("remove-guard")
    assert calls.index("verified-off") < calls.index("remove-guard")
    assert calls.index("remove-guard") < calls.index("unstage")
    assert not marker.exists()


def test_stop_refuses_to_unprotect_if_rdp_socket_still_listens(monkeypatch, tmp_path):
    state_dir = tmp_path / "pilot"
    state_dir.mkdir()
    marker = state_dir / "state.json"
    marker.write_text(json.dumps({"phase": "63D-30", "baseline": pilot.EXPECTED_BASE}))
    monkeypatch.setattr(pilot, "STATE_ROOT", state_dir)
    monkeypatch.setattr(pilot, "STATE_FILE", marker)
    monkeypatch.setattr(pilot, "target", lambda: (1000, tmp_path))
    monkeypatch.setattr(pilot, "kiosk_ok", lambda *args, **kwargs: None)
    monkeypatch.setattr(pilot, "listeners", lambda: [3389])
    monkeypatch.setattr(pilot.time, "sleep", lambda _: None)
    calls = []
    monkeypatch.setattr(pilot.guard, "remove_guard", lambda uid: calls.append("removed"))
    with pytest.raises(RuntimeError, match="listener"):
        pilot.stop()
    assert calls == []
    assert marker.is_file()


def test_no_public_gateway_no_paid_stack_no_unprotected_rdp_fallback():
    src = Path(pilot.__file__).read_text()
    assert "grdctl" in src
    assert "set-credentials" in src
    assert "clear-credentials" in src
    assert "systemctl" in src
    assert "enable-port-negotiation" not in src
    assert "grdctl --system" not in src
    assert "grdctl --headless" not in src
    assert "nft flush ruleset" not in src
    assert "OnCalendar=*-*-* *:*:00" in src
    assert "secret" in src
    assert "HTTPS_443_RELAY_TESTED=False" in src


def test_local_x224_probe_only_uses_loopback_and_never_sends_credentials(monkeypatch):
    observed = []
    class Socket:
        def __enter__(self):
            return self
        def __exit__(self, *ignored):
            pass
        def settimeout(self, value):
            assert value == 3
        def sendall(self, packet):
            observed.append(packet)
        def recv(self, count):
            return bytes((3, 0, 0, 11, 6, 0xD0, 0, 0, 0, 0, 0))
    def fake_connect(address, timeout):
        assert address == ("127.0.0.1", 3389)
        assert timeout == 3
        return Socket()
    monkeypatch.setattr(pilot.socket, "create_connection", fake_connect)
    assert pilot.local_rdp_negotiation()
    assert observed == [bytes.fromhex("030000130ee000000000000100080003000000")]


def test_local_x224_probe_rejects_invalid_response_and_network_error(monkeypatch):
    class BadSocket:
        def __enter__(self):
            return self
        def __exit__(self, *ignored):
            pass
        def settimeout(self, value):
            pass
        def sendall(self, packet):
            pass
        def recv(self, count):
            return bytes((3, 0, 0, 11, 6, 0xFF, 0, 0, 0, 0, 0))
    monkeypatch.setattr(pilot.socket, "create_connection", lambda *a, **k: BadSocket())
    assert not pilot.local_rdp_negotiation()
    def no_connection(*a, **k):
        raise ConnectionRefusedError()
    monkeypatch.setattr(pilot.socket, "create_connection", no_connection)
    assert not pilot.local_rdp_negotiation()


def test_probe_refuses_unverified_guard_or_watchdog(monkeypatch):
    monkeypatch.setattr(pilot, "target", lambda: (1000, Path("/tmp")))
    monkeypatch.setattr(pilot, "state_load", lambda: {"phase": "63D-30"})
    monkeypatch.setattr(pilot, "watchdog_verified", lambda: False)
    monkeypatch.setattr(pilot.guard, "guard_verified", lambda: True)
    with pytest.raises(RuntimeError, match="watchdog"):
        pilot.probe()
    monkeypatch.setattr(pilot, "watchdog_verified", lambda: True)
    monkeypatch.setattr(pilot.guard, "guard_verified", lambda: False)
    with pytest.raises(RuntimeError, match="Firewall"):
        pilot.probe()


def test_unstage_refuses_to_disarm_watchdog_if_rdp_guard_remains(monkeypatch):
    monkeypatch.setattr(pilot, "state_load", lambda: None)
    monkeypatch.setattr(pilot.guard, "ensure_rdp_off", lambda uid: None)
    monkeypatch.setattr(pilot.guard, "guard_exists", lambda: True)
    calls = []
    monkeypatch.setattr(pilot, "run_ok", lambda *args, **kw: calls.append(args))
    with pytest.raises(RuntimeError, match="Firewall"):
        pilot.unstage(1000)
    assert calls == []
