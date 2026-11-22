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
    assert "OnCalendar=*-*-* *:*:0/10" in pilot.TIMER
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
    def report(status):
        monkeypatch.setattr(
            pilot, "kiosk",
            lambda uid, *args, **kwargs: Result(stdout=status),
        )

    report("RDP:\n Username: (empty)\n Password: (empty)\n")
    assert pilot.credentials_empty(1000)
    report("Overall:\n\tUnit status: inactive\nRDP:\n\tUsername: (empty)\n\tPassword: (empty)\n")
    assert pilot.credentials_empty(1000)
    report("RDP:\n\tUsername: (empty)\n\tPassword: (empty)\nVNC:\n\tPassword: (hidden)\n")
    assert pilot.credentials_empty(1000)
    report("RDP:\n\tUsername: (empty)\n\tUsername: (empty)\n\tPassword: (empty)\n")
    assert not pilot.credentials_empty(1000)
    report("RDP:\n\tUsername: (empty)\n\tPassword: (empty)\nRDP:\n\tUsername: (empty)\n\tPassword: (empty)\n")
    assert not pilot.credentials_empty(1000)
    report("RDP:\n Username: (hidden)\n Password: (hidden)\n")
    assert not pilot.credentials_empty(1000)
    report("RDP:\n\tPassword: (empty)\n")
    assert not pilot.credentials_empty(1000)
    report("")
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
    monkeypatch.setattr(pilot.guard, "guard_verified", lambda: True)
    monkeypatch.setattr(pilot, "stop", lambda: events.append("RDP-first cleanup"))
    pilot.tick()
    assert events == []
    monkeypatch.setattr(pilot, "deadline_expired", lambda data: True)
    pilot.tick()
    assert events == ["RDP-first cleanup"]
    monkeypatch.setattr(pilot, "deadline_expired", lambda data: False)
    monkeypatch.setattr(pilot.guard, "guard_verified", lambda: False)
    pilot.tick()
    assert events == ["RDP-first cleanup", "RDP-first cleanup"]


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
    monkeypatch.setattr(pilot, "session_collection_preflight", lambda uid: None)
    monkeypatch.setattr(pilot, "set_temporary_default_alias", lambda uid: events.append("alias-bound"))
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
    assert events.index("guard-install") < events.index("alias-bound")
    assert events.index("alias-bound") < events.index("grdctl rdp set-credentials")
    assert events.index("guard-install") < events.index("grdctl rdp set-tls-key")
    assert events.index("grdctl rdp set-credentials") < events.index("grdctl rdp enable")
    assert (state_dir / "state.json").is_file()
    assert json.loads((state_dir / "state.json").read_text())["temporary_session_alias"] is True
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
    marker.write_text(json.dumps({"phase": "63D-30", "baseline": pilot.EXPECTED_BASE, "temporary_session_alias": True}))
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
    monkeypatch.setattr(pilot, "clear_temporary_default_alias", lambda uid: calls.append("alias-cleared"))
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
    assert calls.index("grdctl rdp clear-credentials") < calls.index("alias-cleared")
    assert calls.index("alias-cleared") < calls.index("remove-guard")
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
    assert "OnCalendar=*-*-* *:*:0/10" in src
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


def test_auth_probe_secret_is_only_in_stdin_and_cert_is_pinned(
    monkeypatch, tmp_path, capsys,
):
    """FreeRDP receives a one-time secret only via its stdin argument stream."""
    import types
    user = "cfpilot1234abcd"
    password = "T" * 44
    class SecretFile:
        def is_symlink(self):
            return False
        def is_file(self):
            return True
        def stat(self):
            return types.SimpleNamespace(st_uid=0, st_mode=0o100600)
        def read_text(self, encoding="utf-8"):
            return user + "\n" + password + "\n"

    monkeypatch.setattr(pilot, "SECRET_FILE", SecretFile())
    monkeypatch.setattr(pilot, "target", lambda: (1000, tmp_path))
    monkeypatch.setattr(pilot, "state_load", lambda: {"phase": "63D-30"})
    monkeypatch.setattr(pilot, "deadline_expired", lambda _: False)
    monkeypatch.setattr(pilot, "watchdog_verified", lambda: True)
    monkeypatch.setattr(pilot.guard, "guard_verified", lambda: True)
    monkeypatch.setattr(pilot, "get_setting", lambda uid, key: "true")
    monkeypatch.setattr(pilot, "listeners", lambda: [3389])
    monkeypatch.setattr(pilot.shutil, "which", lambda name: {
        "xfreerdp": "/usr/bin/xfreerdp",
        "xvfb-run": "/usr/bin/xvfb-run",
    }.get(name))

    cert_dir = tmp_path / "certificate"
    cert_dir.mkdir()
    (cert_dir / "tls.crt").write_text("test only")
    monkeypatch.setattr(pilot, "tls_directory", lambda uid: cert_dir)

    invoked = []
    def fake_run(argv, **kwargs):
        invoked.append((argv, kwargs))
        if argv[0] == "openssl":
            assert "tls.crt" in argv[-3] or "tls.crt" in argv
            return types.SimpleNamespace(returncode=0, stdout=b"DER-ONLY")
        assert argv == [
            "/usr/bin/xvfb-run", "-a", "/usr/bin/xfreerdp", "/args-from:stdin"
        ]
        assert kwargs.get("capture_output") is True
        assert kwargs.get("text") is True
        assert user in kwargs["input"]
        assert password in kwargs["input"]
        assert "+auth-only" in kwargs["input"]
        assert "/v:127.0.0.1:3389" in kwargs["input"]
        assert "/cert:fingerprint:sha256:" in kwargs["input"]
        assert "/cert:ignore" not in kwargs["input"]
        assert password not in " ".join(argv)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(pilot.subprocess, "run", fake_run)
    pilot.auth_probe()
    output = capsys.readouterr().out
    assert "FREERDP_LOCAL_AUTH_ONLY= PASS" in output
    assert user not in output and password not in output
    assert len(invoked) == 2


def test_auth_probe_fails_closed_when_guard_or_watchdog_is_missing(monkeypatch):
    monkeypatch.setattr(pilot, "target", lambda: (1000, Path("/tmp")))
    monkeypatch.setattr(pilot, "state_load", lambda: {"phase": "63D-30"})
    monkeypatch.setattr(pilot, "deadline_expired", lambda _: False)
    monkeypatch.setattr(pilot, "watchdog_verified", lambda: False)
    monkeypatch.setattr(pilot.guard, "guard_verified", lambda: True)
    with pytest.raises(RuntimeError, match="watchdog"):
        pilot.auth_probe()
    monkeypatch.setattr(pilot, "watchdog_verified", lambda: True)
    monkeypatch.setattr(pilot.guard, "guard_verified", lambda: False)
    with pytest.raises(RuntimeError, match="firewall"):
        pilot.auth_probe()


def test_auth_probe_does_not_attempt_connection_without_test_packages(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(pilot, "target", lambda: (1000, Path("/tmp")))
    monkeypatch.setattr(pilot, "state_load", lambda: {"phase": "63D-30"})
    monkeypatch.setattr(pilot, "deadline_expired", lambda _: False)
    monkeypatch.setattr(pilot, "watchdog_verified", lambda: True)
    monkeypatch.setattr(pilot.guard, "guard_verified", lambda: True)
    monkeypatch.setattr(pilot, "get_setting", lambda uid, key: "true")
    monkeypatch.setattr(pilot, "listeners", lambda: [3389])
    monkeypatch.setattr(pilot, "SECRET_FILE", SimpleNamespace(
        is_symlink=lambda: False,
        is_file=lambda: True,
        stat=lambda: SimpleNamespace(st_uid=0, st_mode=0o100600),
        read_text=lambda encoding="utf-8": "cfpilot1234abcd\n" + "S"*44 + "\n",
    ))
    monkeypatch.setattr(pilot.shutil, "which", lambda name: None)
    def must_not_run(*args, **kwargs):
        raise AssertionError("Should not run openssl or FreeRDP if packages missing")
    monkeypatch.setattr(pilot.subprocess, "run", must_not_run)
    with pytest.raises(RuntimeError, match="freerdp"):
        pilot.auth_probe()


def test_bounded_auth_exercise_starts_authenticates_and_always_stops(
    monkeypatch, capsys,
):
    source_path = Path(pilot.__file__).resolve()
    monkeypatch.setattr(pilot, "STAGED_RUNNER", source_path)
    monkeypatch.setattr(pilot, "target", lambda: (1000, Path("/tmp")))
    monkeypatch.setattr(pilot, "watchdog_verified", lambda: True)
    monkeypatch.setattr(pilot.shutil, "which", lambda name: "/usr/bin/" + name)
    current = {"state": None}
    monkeypatch.setattr(pilot, "state_load", lambda: current["state"])
    events = []
    def fake_start():
        events.append("start")
        current["state"] = {"phase": "63D-30"}
    def fake_auth():
        events.append("auth")
    def fake_stop():
        events.append("stop")
        current["state"] = None
    monkeypatch.setattr(pilot, "start", fake_start)
    monkeypatch.setattr(pilot, "auth_probe", fake_auth)
    monkeypatch.setattr(pilot, "stop", fake_stop)
    pilot.exercise_auth()
    assert events == ["start", "auth", "stop"]
    assert "RDP_AUTH_AND_ROLLBACK_DRILL=PASS" in capsys.readouterr().out


def test_bounded_auth_exercise_stops_even_if_authentication_fails(monkeypatch):
    monkeypatch.setattr(pilot, "STAGED_RUNNER", Path(pilot.__file__).resolve())
    monkeypatch.setattr(pilot, "target", lambda: (1000, Path("/tmp")))
    monkeypatch.setattr(pilot, "watchdog_verified", lambda: True)
    monkeypatch.setattr(pilot.shutil, "which", lambda name: "/usr/bin/" + name)
    current = {"state": None}
    monkeypatch.setattr(pilot, "state_load", lambda: current["state"])
    events = []
    def fake_start():
        events.append("start")
        current["state"] = {"phase": "63D-30"}
    def fake_auth():
        events.append("auth-failed")
        raise RuntimeError("FreeRDP authentication rejected")
    def fake_stop():
        events.append("stop")
        current["state"] = None
    monkeypatch.setattr(pilot, "start", fake_start)
    monkeypatch.setattr(pilot, "auth_probe", fake_auth)
    monkeypatch.setattr(pilot, "stop", fake_stop)
    with pytest.raises(RuntimeError, match="authentication rejected"):
        pilot.exercise_auth()
    assert events == ["start", "auth-failed", "stop"]


def test_bounded_auth_exercise_does_not_start_without_a_client(monkeypatch):
    monkeypatch.setattr(pilot, "STAGED_RUNNER", Path(pilot.__file__).resolve())
    monkeypatch.setattr(pilot, "target", lambda: (1000, Path("/tmp")))
    monkeypatch.setattr(pilot, "watchdog_verified", lambda: True)
    monkeypatch.setattr(pilot, "state_load", lambda: None)
    monkeypatch.setattr(pilot.shutil, "which", lambda name: None)
    events = []
    monkeypatch.setattr(pilot, "start", lambda: events.append("start"))
    with pytest.raises(RuntimeError, match="FreeRDP/Xvfb"):
        pilot.exercise_auth()
    assert events == []

@pytest.mark.parametrize(("arguments", "label"), [
    (("grdctl", "rdp", "set-tls-key", "/private/KEY_PATH"), "RDP_SET_TLS_KEY"),
    (("grdctl", "rdp", "set-tls-cert", "/private/CERT_PATH"), "RDP_SET_TLS_CERT"),
    (("grdctl", "rdp", "set-credentials"), "RDP_SET_CREDENTIALS"),
    (("grdctl", "rdp", "disable-port-negotiation"), "RDP_DISABLE_PORT_NEGOTIATION"),
    (("grdctl", "rdp", "disable-view-only"), "RDP_DISABLE_VIEW_ONLY"),
    (("grdctl", "rdp", "enable"), "RDP_ENABLE"),
    (("grdctl", "rdp", "disable"), "RDP_DISABLE"),
    (("grdctl", "rdp", "clear-credentials"), "RDP_CLEAR_CREDENTIALS"),
    (("systemctl", "--user", "enable", "--now", "gnome-remote-desktop.service"), "USER_RDP_SERVICE_ENABLE"),
    (("systemctl", "--user", "disable", "--now", "gnome-remote-desktop.service"), "USER_RDP_SERVICE_DISABLE"),
    (("gsettings", "set", pilot.SCHEMA, "tls-key", "/private/KEY_PATH"), "GSETTINGS_SET"),
    (("unrecognized", "/private/KEY_PATH"), "OTHER_USER_COMMAND"),
])
def test_gnome_failure_reports_only_safe_operation_not_secrets(monkeypatch, capsys, arguments, label):
    secret = "very-private-password-and-user"
    monkeypatch.setattr(
        pilot, "kiosk",
        lambda uid, *args, input=None: Result(code=23, stdout=secret),
    )
    with pytest.raises(RuntimeError, match="GNOME user operation failed"):
        pilot.kiosk_ok(1000, *arguments, input=secret + "\\n")
    output = capsys.readouterr().out
    assert "GNOME_USER_FAILED_OPERATION= " + label in output
    assert "GNOME_USER_COMMAND_FAILED=True" in output
    assert secret not in output
    assert "KEY_PATH" not in output
    assert "CERT_PATH" not in output


def test_gnome_success_does_not_emit_diagnostic_or_reveal_stdin(monkeypatch, capsys):
    secret = "never-print-me"
    monkeypatch.setattr(
        pilot, "kiosk",
        lambda uid, *args, input=None: Result(code=0, stdout=secret),
    )
    pilot.kiosk_ok(1000, "grdctl", "rdp", "set-credentials", input=secret)
    assert capsys.readouterr().out == ""

def test_session_collection_preflight_only_accepts_existing_unlocked_ram_keyring(monkeypatch, capsys):
    path = pilot.SESSION_COLLECTION
    values = {
        "Collections": 'ao 1 "' + path + '"',
        "Locked": "b false",
    }
    aliases = {"default": "/", "login": "/"}

    def fake_bus(uid, *args):
        if args[0] == "get-property":
            return values[args[-1]]
        if args[0] == "call" and args[-3] == "ReadAlias":
            return 'o "' + aliases[args[-1]] + '"'
        raise AssertionError("Only read calls allowed in preflight")

    monkeypatch.setattr(pilot, "secret_bus", fake_bus)
    pilot.session_collection_preflight(1000)
    assert "RAM_ONLY_SESSION_COLLECTION_VERIFIED=True" in capsys.readouterr().out
    values["Collections"] = 'ao 1 "/org/freedesktop/secrets/collection/other"'
    with pytest.raises(RuntimeError, match="session collection"):
        pilot.session_collection_preflight(1000)
    values["Collections"] = 'ao 1 "' + path + '"'
    values["Locked"] = "b true"
    with pytest.raises(RuntimeError, match="locked"):
        pilot.session_collection_preflight(1000)
    values["Locked"] = "b false"
    aliases["default"] = path
    with pytest.raises(RuntimeError, match="alias"):
        pilot.session_collection_preflight(1000)


def test_temporary_alias_is_set_only_for_verified_session_and_reverted(monkeypatch, capsys):
    alias = {"default": "/", "login": "/"}
    calls = []
    monkeypatch.setattr(pilot, "session_collection_preflight", lambda uid: calls.append("verified"))
    monkeypatch.setattr(pilot, "secret_alias", lambda uid, name: alias[name])

    def fake_bus(uid, *args):
        assert args[0] == "call"
        assert args[-2] == "default"
        assert args[-1] in {"/", pilot.SESSION_COLLECTION}
        calls.append("set")
        alias["default"] = args[-1]
        return ""

    monkeypatch.setattr(pilot, "secret_bus", fake_bus)
    pilot.set_temporary_default_alias(1000)
    assert alias["default"] == pilot.SESSION_COLLECTION
    pilot.clear_temporary_default_alias(1000)
    assert alias == {"default": "/", "login": "/"}
    assert calls == ["verified", "set", "set"]
    assert "TEMPORARY_SESSION_ALIAS_CLEARED=True" in capsys.readouterr().out


def test_clear_alias_rejects_unrelated_default_without_mutation(monkeypatch):
    monkeypatch.setattr(
        pilot, "secret_alias",
        lambda uid, name: "/org/freedesktop/secrets/collection/unrelated",
    )
    monkeypatch.setattr(
        pilot, "secret_bus",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not overwrite")),
    )
    with pytest.raises(RuntimeError, match="Unexpected existing"):
        pilot.clear_temporary_default_alias(1000)


def test_session_preflight_failure_must_precede_firewall_or_rdp(monkeypatch, tmp_path):
    monkeypatch.setattr(pilot, "STAGED_RUNNER", Path(pilot.__file__).resolve())
    monkeypatch.setattr(pilot, "target", lambda: (1000, tmp_path))
    monkeypatch.setattr(pilot, "state_load", lambda: None)
    monkeypatch.setattr(pilot, "watchdog_verified", lambda: True)
    monkeypatch.setattr(pilot, "read_baseline", lambda uid: dict(pilot.EXPECTED_BASE))
    monkeypatch.setattr(
        pilot, "session_collection_preflight",
        lambda uid: (_ for _ in ()).throw(RuntimeError("STOP: not session collection")),
    )
    monkeypatch.setattr(
        pilot.guard, "install_guard",
        lambda uid: (_ for _ in ()).throw(AssertionError("firewall must not install")),
    )
    with pytest.raises(RuntimeError, match="not session collection"):
        pilot.start()
