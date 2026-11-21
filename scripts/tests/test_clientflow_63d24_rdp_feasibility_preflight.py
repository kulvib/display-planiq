"""63D-24: physical GNOME RDP inventory is fail-closed and strictly read-only."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import audit_viborg1_rdp_capability as audit


def test_target_bound_to_physical_test_client_and_root():
    valid = {"CLIENT_ID": 3}
    audit.validate_target("viborg1-NUC14MNK-B2", 0, valid)
    audit.validate_target("viborg1-NUC14MNK-B2", 0, {"client_id": "3"})
    for host, uid, identity in [
        ("other-computer", 0, valid),
        ("viborg1-NUC14MNK-B2", 1000, valid),
        ("viborg1-NUC14MNK-B2", 0, {"CLIENT_ID": 56}),
        ("viborg1-NUC14MNK-B2", 0, {}),
    ]:
        with pytest.raises(ValueError, match="STOP"):
            audit.validate_target(host, uid, identity)


def test_socket_detection_reports_only_aggregate_presence():
    rows = (
        "LISTEN 0 128 127.0.0.1:3389 0.0.0.0:*\n"
        "LISTEN 0 128 [::1]:3390 [::]:*\n"
        "LISTEN 0 128 [::]:443 [::]:*\n"
    )
    assert audit.rdp_listener_summary(rows) == {
        "rdp_listener_count": 2,
        "rdp_nonloopback_listener_present": False,
    }
    assert audit.rdp_listener_summary("LISTEN 0 128 [::]:3389 [::]:*") == {
        "rdp_listener_count": 1,
        "rdp_nonloopback_listener_present": True,
    }
    assert audit.rdp_listener_summary("") == {
        "rdp_listener_count": 0,
        "rdp_nonloopback_listener_present": False,
    }


def test_unknown_command_result_is_not_reported_as_inactive(monkeypatch):
    monkeypatch.setattr(audit, "command", lambda *a, **k: (None, ""))
    assert audit.service_active("systemctl", "is-active", "something") == "unknown"
    monkeypatch.setattr(audit, "command", lambda *a, **k: (0, "active"))
    assert audit.service_active("systemctl", "is-active", "something") == "active"


def test_probe_is_read_only_and_never_claims_network_readiness(tmp_path, monkeypatch):
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"CLIENT_ID": 3}), encoding="utf-8")
    monkeypatch.setattr(audit, "IDENTITY", identity)
    monkeypatch.setattr(audit.socket, "gethostname", lambda: "viborg1-NUC14MNK-B2")
    monkeypatch.setattr(audit.os, "geteuid", lambda: 0)
    monkeypatch.setattr(audit.shutil, "which", lambda name: "/usr/bin/grdctl" if name == "grdctl" else None)

    observed = []

    def fake_command(*args, **_kwargs):
        observed.append(args)
        if args[:2] == ("id", "-u"):
            return (0, "1000")
        if args[0] == "dpkg-query":
            return (0, "install ok installed")
        if args[0] == "ss":
            return (0, "LISTEN 0 128 127.0.0.1:3389 0.0.0.0:*")
        if args[:2] == ("systemctl", "is-active"):
            return (0, "active")
        raise AssertionError(f"unexpected command: {args[0]}")

    monkeypatch.setattr(audit, "command", fake_command)
    report = audit.snapshot()
    assert report["read_only"] is True
    assert report["client_id_verified"] == 3
    assert report["rdp_listener_count"] == 1
    assert report["rdp_nonloopback_listener_present"] is False
    assert report["gnome_remote_desktop_installed"] is True
    assert report["rdp_connection_tested"] is False
    assert report["https_443_reverse_transport_tested"] is False
    assert report["render_capacity_tested"] is False
    assert report["kiosk_configuration_changed"] is False
    assert identity.read_text(encoding="utf-8") == json.dumps({"CLIENT_ID": 3})
    allowed = {"id", "dpkg-query", "ss", "systemctl", "runuser"}
    assert all(command[0] in allowed for command in observed)
    assert not any("restart" in command or "enable" in command for command in observed)


def test_source_does_not_perform_network_or_configuration_mutation():
    source = (Path(__file__).resolve().parents[1] / "audit_viborg1_rdp_capability.py").read_text()
    for forbidden in (
        "urlopen(", "requests.", "socket.connect(", "systemd-run", "set-credentials",
        "grdctl rdp enable", "systemctl daemon-reload", "ufw allow", "subprocess.Popen(",
    ):
        assert forbidden not in source
