#!/usr/bin/env python3
"""63D-40: SHA-pinned, offline ELF evidence for Ubuntu 26.04 RFB packages.

The reviewed artifacts are NEVER installed or executed. The archive contents
are extracted only into an ephemeral CI-owned private directory for readelf
inspection. This program cannot approve or activate a native RFB producer.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from scripts import clientflow_63d39_rfb_ci_audit as prior

# Obtained from exact signed-index Ubuntu 26.04 CI archive inventory in
# GitHub run 45060143659, job "63D-39 isolated Ubuntu 26.04 RFB archive evidence".
# Any APT update requires explicit re-review, not automatic upgrade.
PINNED = {
    "x11vnc": (
        "0.9.17-2",
        "6db501632d2ead8186fd015da508075103e1efe5f234372ba6a8682c5bb60bd0",
    ),
    "libvncserver1": (
        "0.9.15+dfsg-3ubuntu0.2",
        "7ce6b886e691f637bc43bdc167659416db60e91f30e82c99d6f4b5761f510531",
    ),
    "libvncclient1": (
        "0.9.15+dfsg-3ubuntu0.2",
        "4bdf33d5d441de9dd3e950fa59aec4af20fe149ce44adf3772a87c674343786a",
    ),
    "tigervnc-scraping-server": (
        "1.15.0+dfsg-2build1",
        "03d5178bd4ced1eb15d573d475a5cc01b099e38f3432b5225e6f5c1860e6c7df",
    ),
}
# Even a matching SHA and NX stack can never mean "producer approved".
PRODUCER_APPROVED = False
_UNIX_SOCKET_DOCUMENTED_LIMITATION = (
    "x11vnc upstream -unixsock documentation requires LibVNCServer "
    "rfbserver.c modification; unmodified Ubuntu ABI compatibility unproven"
)


class EvidenceError(ValueError):
    """Fail-closed binary evidence error, no secrets or arbitrary commands."""


def validate_archive_pins(evidence: object) -> None:
    if type(evidence) is not dict or not evidence.get("audit_evidence_pass"):
        raise EvidenceError("63D-39 archive evidence not accepted")
    packages = evidence.get("archive_versions_and_sha256")
    if type(packages) is not dict or set(packages) != set(PINNED):
        raise EvidenceError("Unexpected package inventory set")
    for package, (version, digest) in PINNED.items():
        meta = packages[package]
        if (
            type(meta) is not dict or meta.get("version") != version
            or meta.get("sha256") != digest
            or meta.get("architecture") != "amd64"
        ):
            raise EvidenceError("Pinned Ubuntu 26.04 package changed")
    if any(evidence.get(k) is not False for k in (
        "producer_approved", "activation_permitted", "package_executed",
        "package_installed",
    )):
        raise EvidenceError("Audit evidence granted unexpected privilege")


def fixed_command(args: tuple[str, ...]) -> str:
    """Reviewable subprocess allowlist. No shell, apt install or ELF execution."""
    if not args:
        raise EvidenceError("No evidence command")
    if args[0] == "dpkg-deb":
        if len(args) != 4 or args[1] != "-x":
            raise EvidenceError("Disallowed Debian package operation")
        if not args[2].endswith(".deb"):
            raise EvidenceError("Non-Debian archive")
    elif args[0] == "readelf":
        if len(args) != 3 or args[1] not in {"-hW", "-lW", "-dW"}:
            raise EvidenceError("Disallowed ELF inspection operation")
    else:
        raise EvidenceError("Arbitrary subprocess denied")
    try:
        outcome = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError("Offline ELF inspection unavailable") from exc
    if outcome.returncode != 0 or len(outcome.stdout) > 100_000:
        raise EvidenceError("Offline ELF inspection failed or exceeded bounds")
    return outcome.stdout


def parse_elf(header: str, segments: str, dynamic: str) -> dict:
    """Independent, deliberately conservative ELF metadata parser."""
    if "ELF Header:" not in header or not re.search(
        r"(?m)^\s*Class:\s+ELF64\s*$", header,
    ) or not re.search(r"(?m)^\s*Machine:\s+Advanced Micro Devices X86-64\s*$", header):
        raise EvidenceError("Unrecognised amd64 ELF binary")
    stacks = [line for line in segments.splitlines() if "GNU_STACK" in line]
    if len(stacks) != 1 or not re.search(r"\bRW\b", stacks[0]) or re.search(
        r"\bRWE\b|\bRWX\b", stacks[0],
    ):
        raise EvidenceError("Executable or unverifiable ELF stack")
    needed = sorted(set(re.findall(
        r"\(NEEDED\)\s+Shared library: \[([a-zA-Z0-9_.+:-]+)\]", dynamic,
    )))
    if not needed or len(needed) > 128:
        raise EvidenceError("No bounded dynamic dependency inventory")
    return {
        "elf_class": "ELF64",
        "machine": "x86_64",
        "non_executable_stack": True,
        "needed_sonames": needed,
    }


def inspect_binary(path: Path, runner=fixed_command) -> dict:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError("RFB binary missing or symlinked")
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or not 0 < st.st_size < 30_000_000:
        raise EvidenceError("Unexpected RFB binary type or size")
    return parse_elf(
        runner(("readelf", "-hW", str(path))),
        runner(("readelf", "-lW", str(path))),
        runner(("readelf", "-dW", str(path))),
    )


def inspect(download_dir: Path, *, inventory=prior.inventory,
            command=fixed_command) -> dict:
    evidence = inventory(download_dir)
    validate_archive_pins(evidence)
    # The exact 4 official archives are uncompressed into a CI-only tmp tree.
    # Nothing is executed, installed, bound to a network port or activated.
    with tempfile.TemporaryDirectory(prefix="clientflow-63d40-") as workspace:
        root = Path(workspace)
        os.chmod(root, 0o700)
        for package in PINNED:
            matches = list(download_dir.glob(package + "_*.deb"))
            if len(matches) != 1 or matches[0].is_symlink():
                raise EvidenceError("Pinned package filename ambiguous")
            dest = root / package
            dest.mkdir(mode=0o700)
            command(("dpkg-deb", "-x", str(matches[0]), str(dest)))
        executable = root / "x11vnc/usr/bin/x11vnc"
        elf = inspect_binary(executable, runner=command)
        # This evidence is informational; it is not proof of Unix-only mode.
        return {
            "schema": "63d40-ubuntu-rfb-offline-elf-v1",
            "archive_pin_check": "PASS",
            "nonexecuting_elf_evidence": elf,
            "x11vnc_unix_socket_abi_proven": False,
            "unix_socket_documentation_warning": _UNIX_SOCKET_DOCUMENTED_LIMITATION,
            "tigervnc_cve_2026_34352_cleared": False,
            "x11vnc_cve_2026_32853_cleared": False,
            "no_tcp_listener_proven": False,
            "package_installed": False,
            "package_executed": False,
            "producer_approved": False,
            "activation_permitted": False,
            "physical_host_changed": False,
            "reason": "STOP: exact ABI, advisory status and Unix-only runtime remain unapproved",
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8")
        if not prior.ci_host_ok(dict(os.environ), release, os.geteuid()):
            raise EvidenceError("Only unprivileged GitHub Ubuntu 26.04 CI is authorised")
        result = inspect(args.download_dir)
    except (EvidenceError, prior.AuditError, OSError) as exc:
        result = {
            "schema": "63d40-ubuntu-rfb-offline-elf-v1",
            "archive_pin_check": "FAIL",
            "producer_approved": False, "activation_permitted": False,
            "package_installed": False, "package_executed": False,
            "physical_host_changed": False, "reason": "STOP: " + str(exc),
        }
    print(json.dumps(result, sort_keys=True, indent=2), flush=True)
    return 0 if result.get("archive_pin_check") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
