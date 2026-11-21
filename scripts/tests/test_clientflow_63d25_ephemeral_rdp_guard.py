"""63D-25: fail-closed, isolated, reversible RDP firewall guard dry-run."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import clientflow_63d25_ephemeral_rdp_guard as guard


def test_target_guards():
    guard.validated_identity(
        host="viborg1-NUC14MNK-B2", root_uid=0, document={"CLIENT_ID": 3}
    )
    for host, uid, document in [
        ("not-viborg1", 0, {"CLIENT_ID": 3}),
        ("viborg1-NUC14MNK-B2", 1000, {"CLIENT_ID": 3}),
        ("viborg1-NUC14MNK-B2", 0, {"CLIENT_ID": 56}),
        ("viborg1-NUC14MNK-B2", 0, {}),
    ]:
        with pytest.raises(RuntimeError, match="STOP"):
            guard.validated_identity(host=host, root_uid=uid, document=document)


def test_guard_applies_to_ipv4_ipv6_and_excludes_loopback():
    assert f"table inet {guard.TABLE}" in guard.RULES
    assert 'iifname != "lo" tcp dport { 3389, 3390 } drop' in guard.RULES
    assert "policy accept;" in guard.RULES
    assert "hook input priority -100" in guard.RULES
    assert guard.validate_table_output(guard.RULES)
    assert not guard.validate_table_output('table inet unrelated { }')
    assert not guard.validate_table_output(
        f'table inet {guard.TABLE} {{ chain inbound {{ policy accept; }} }}'
    )
    assert not guard.no_rdp_listener("LISTEN 0 128 127.0.0.1:3389 0.0.0.0:*")
    assert not guard.no_rdp_listener("LISTEN 0 128 [::]:3390 [::]:*")
    assert guard.no_rdp_listener("LISTEN 0 128 0.0.0.0:443 0.0.0.0:*")


def test_live_guard_drill_installs_only_after_timer_and_removes_it(monkeypatch, tmp_path):
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"CLIENT_ID": 3}))
    monkeypatch.setattr(guard, "IDENTITY", identity)
    monkeypatch.setattr(guard.socket, "gethostname", lambda: "viborg1-NUC14MNK-B2")
    monkeypatch.setattr(guard.os, "geteuid", lambda: 0)
    runtime = tmp_path / "1000"
    runtime.mkdir()
    (runtime / "bus").touch()
    original_is_socket = Path.is_socket
    monkeypatch.setattr(Path, "is_socket", lambda p: True if p.name == "bus" else original_is_socket(p))
    # Path /run/user/1000 need not exist in CI: the fake D-Bus path is validated at
    # the fixture level without touching the production filesystem.
    monkeypatch.setattr(guard.time, "sleep", lambda _: None)

    commands = []
    table_exists = False
    timer_armed = False

    class Result:
        def __init__(self, code=0, stdout="", stderr=""):
            self.returncode, self.stdout, self.stderr = code, stdout, stderr

    def fake_run(*argv, **kw):
        nonlocal table_exists, timer_armed
        commands.append(argv)
        if argv[:3] == ("systemctl", "is-active", "gnome-remote-desktop.service"):
            return Result(code=3, stdout="inactive")
        if argv[:3] == ("id", "-u", "clientflow-kiosk"):
            return Result(stdout="1000")
        if argv[0] == "runuser":
            return Result(code=3, stdout="inactive")
        if argv[:3] == ("ss", "-H", "-ltn"):
            return Result(stdout="LISTEN 0 128 0.0.0.0:443 0.0.0.0:*")
        if argv[:4] == ("nft", "list", "table", "inet"):
            return (
                Result(stdout=guard.RULES) if table_exists
                else Result(code=1, stderr="No such file or directory")
            )
        if argv[:3] == ("nft", "--check", "--file"):
            assert kw["input"] == guard.RULES
            return Result()
        if argv[0] == "systemd-run":
            assert not table_exists
            timer_armed = True
            return Result()
        if argv[:2] == ("systemctl", "is-active") and argv[2].endswith(".timer"):
            return Result(stdout="active" if timer_armed else "inactive")
        if argv[:3] == ("nft", "--file", "-"):
            assert timer_armed
            assert not table_exists
            table_exists = True
            return Result()
        if argv[:4] == ("nft", "delete", "table", "inet"):
            table_exists = False
            return Result()
        if argv[:2] == ("systemctl", "stop"):
            assert not table_exists
            timer_armed = False
            return Result()
        raise AssertionError("Unexpected call: " + repr(argv))

    monkeypatch.setattr(guard, "run", fake_run)
    # Only this test fixture replaces the system DBus check, never pilot source.
    assert guard.main() == 0
    assert not table_exists
    assert not timer_armed
    assert not any("enable" in part or "restart" in part for call in commands for part in call)


def test_source_has_no_configuration_or_network_side_effects_outside_exact_nft_guard():
    source = (Path(__file__).resolve().parents[1] / "clientflow_63d25_ephemeral_rdp_guard.py").read_text()
    for forbidden in ("grdctl rdp enable", "ufw allow", "flush ruleset", "systemctl restart",
                      "urlopen(", "socket.connect(", "set-credentials", "enable --now"):
        assert forbidden not in source
    assert "systemd-run" in source
    assert "nft" in source
