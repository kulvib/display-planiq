"""63D-40: non-executing ELF evidence and negative security contracts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import clientflow_63d40_rfb_offline_elf as audit


HEADER = """ELF Header:
  Class:                             ELF64
  Machine:                           Advanced Micro Devices X86-64
"""
SEGMENTS = """Program Headers:
  GNU_STACK      0x000000 0x000000 0x000000 0x000000 0x000000 RW 0x10
"""
DYNAMIC = """Dynamic section at offset 0x3000 contains 3 entries:
 0x0000000000000001 (NEEDED)             Shared library: [libvncserver.so.1]
 0x0000000000000001 (NEEDED)             Shared library: [libX11.so.6]
"""


def evidence():
    return {
        "audit_evidence_pass": True,
        "archive_versions_and_sha256": {
            name: {"version": version, "sha256": digest, "architecture": "amd64"}
            for name, (version, digest) in audit.PINNED.items()
        },
        "producer_approved": False,
        "activation_permitted": False,
        "package_executed": False,
        "package_installed": False,
    }


def fake_packages(tmp_path: Path):
    for name in audit.PINNED:
        (tmp_path / (name + "_candidate_amd64.deb")).write_bytes(name.encode())


def evidence_commands(args):
    if args[:2] == ("dpkg-deb", "-x"):
        dest = Path(args[3])
        if dest.name == "x11vnc":
            target = dest / "usr/bin/x11vnc"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"\x7fELF" * 10)
        return ""
    if args[:2] == ("readelf", "-hW"):
        return HEADER
    if args[:2] == ("readelf", "-lW"):
        return SEGMENTS
    if args[:2] == ("readelf", "-dW"):
        return DYNAMIC
    raise AssertionError("unexpected command")


def test_realistic_offline_evidence_is_never_approval(tmp_path):
    fake_packages(tmp_path)
    result = audit.inspect(tmp_path, inventory=lambda _: evidence(),
                           command=evidence_commands)
    assert result["archive_pin_check"] == "PASS"
    assert result["nonexecuting_elf_evidence"]["non_executable_stack"]
    assert "libvncserver.so.1" in result["nonexecuting_elf_evidence"]["needed_sonames"]
    for key in (
        "producer_approved", "activation_permitted", "physical_host_changed",
        "package_executed", "package_installed", "x11vnc_unix_socket_abi_proven",
        "no_tcp_listener_proven",
    ):
        assert result[key] is False
    assert "rfbserver.c" in result["unix_socket_documentation_warning"]


@pytest.mark.parametrize("field,value", [
    ("audit_evidence_pass", False),
    ("producer_approved", True),
    ("activation_permitted", True),
    ("package_installed", True),
    ("package_executed", True),
])
def test_untrusted_previous_evidence_denied(field, value):
    previous = evidence()
    previous[field] = value
    with pytest.raises(audit.EvidenceError):
        audit.validate_archive_pins(previous)


@pytest.mark.parametrize("attribute", ["version", "sha256", "architecture"])
def test_changed_package_identity_denied(attribute):
    previous = evidence()
    previous["archive_versions_and_sha256"]["x11vnc"][attribute] = "untrusted"
    with pytest.raises(audit.EvidenceError, match="Pinned"):
        audit.validate_archive_pins(previous)


def test_missing_or_extra_package_denied():
    previous = evidence()
    previous["archive_versions_and_sha256"].pop("x11vnc")
    with pytest.raises(audit.EvidenceError):
        audit.validate_archive_pins(previous)
    previous = evidence()
    previous["archive_versions_and_sha256"]["untrusted"] = {}
    with pytest.raises(audit.EvidenceError):
        audit.validate_archive_pins(previous)


def test_multiple_archive_names_denied(tmp_path):
    fake_packages(tmp_path)
    (tmp_path / "x11vnc_duplicate_amd64.deb").write_bytes(b"no")
    with pytest.raises(audit.EvidenceError, match="ambiguous"):
        audit.inspect(tmp_path, inventory=lambda _: evidence(),
                      command=evidence_commands)


def test_symlink_archive_denied(tmp_path):
    fake_packages(tmp_path)
    link = next(tmp_path.glob("x11vnc_*.deb"))
    link.unlink()
    link.symlink_to(next(tmp_path.glob("libvncserver1_*.deb")))
    with pytest.raises(audit.EvidenceError):
        audit.inspect(tmp_path, inventory=lambda _: evidence(),
                      command=evidence_commands)


def test_bad_or_executable_stack_denied():
    with pytest.raises(audit.EvidenceError):
        audit.parse_elf(HEADER, SEGMENTS.replace(" RW ", " RWE "), DYNAMIC)
    with pytest.raises(audit.EvidenceError):
        audit.parse_elf(HEADER.replace("ELF64", "ELF32"), SEGMENTS, DYNAMIC)
    with pytest.raises(audit.EvidenceError):
        audit.parse_elf(HEADER, SEGMENTS, "No NEEDED dependencies")


def test_allowlist_rejects_execution_and_package_install():
    for rejected in (
        ("apt-get", "install", "x11vnc"),
        ("bash", "-c", "true"),
        ("systemctl", "start", "gnome-remote-desktop"),
        ("dpkg-deb", "-e", "fake.deb", "/tmp/abc"),
        ("readelf", "-a", "/some/file"),
        ("x11vnc", "-unixsock", "/tmp/untrusted"),
    ):
        with pytest.raises(audit.EvidenceError):
            audit.fixed_command(rejected)


def test_cmd_shapes_cannot_be_extended(monkeypatch):
    commands = []
    class Done:
        returncode = 0
        stdout = HEADER
    def stub(args, **kwargs):
        commands.append((args, kwargs))
        return Done()
    monkeypatch.setattr(audit.subprocess, "run", stub)
    assert audit.fixed_command(("readelf", "-hW", "/tmp/example")) == HEADER
    assert commands[0][0] == ("readelf", "-hW", "/tmp/example")
    assert commands[0][1]["check"] is False
    assert commands[0][1]["timeout"] == 30
