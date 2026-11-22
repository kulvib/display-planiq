#!/usr/bin/env python3
"""63D-39: CI-only, non-executing Ubuntu 26.04 RFB .deb provenance audit.

Only inspects downloaded archives. NEVER installs, executes, starts a service,
connects to or approves an RFB producer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

PACKAGES = ("x11vnc", "libvncserver1", "libvncclient1", "tigervnc-scraping-server")
LIBRARIES = ("libvncserver1", "libvncclient1")
SECURITY_BASELINE = "0.9.15+dfsg-3ubuntu0.2"
MAX_PACKAGE_BYTES = 30 * 1024 * 1024
VERSION = re.compile(r"[0-9][A-Za-z0-9.+:~_-]{0,110}\Z")
BLOCKERS = {
    "x11vnc": "CVE-2026-32853: Ubuntu resolute needs evaluation",
    "tigervnc-scraping-server": "CVE-2026-34352: Ubuntu resolute needs evaluation",
}


class AuditError(ValueError):
    """Fail-closed archive inventory; not an installation recommendation."""


def ci_host_ok(env: dict[str, str], os_release: str, uid: int) -> bool:
    fields = {}
    for line in os_release.splitlines():
        name, sep, value = line.partition("=")
        if sep:
            fields[name] = value.strip().strip('"')
    return (
        uid != 0
        and env.get("CI") == "true"
        and env.get("GITHUB_ACTIONS") == "true"
        and env.get("GITHUB_REPOSITORY") == "kulvib/display-planiq"
        and fields.get("ID") == "ubuntu"
        and fields.get("VERSION_ID") == "26.04"
    )


def read_control(path: Path, field: str) -> str:
    if field not in {"Package", "Version", "Architecture"}:
        raise AuditError("Unapproved Debian control field")
    try:
        done = subprocess.run(
            ("dpkg-deb", "-f", str(path), field),
            capture_output=True, text=True, timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditError("Debian package inspection unavailable") from exc
    if done.returncode != 0:
        raise AuditError("Cannot read Debian archive control metadata")
    return done.stdout.strip()


def compare_version(candidate: str) -> bool:
    if not VERSION.fullmatch(candidate):
        raise AuditError("Invalid Debian library version")
    try:
        done = subprocess.run(
            ("dpkg", "--compare-versions", candidate, "ge", SECURITY_BASELINE),
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditError("dpkg version comparison unavailable") from exc
    if done.returncode not in (0, 1):
        raise AuditError("Invalid dpkg comparison result")
    return done.returncode == 0


def inventory(download_dir: Path, *, control=read_control,
              compare=compare_version) -> dict:
    if not download_dir.is_dir() or download_dir.is_symlink():
        raise AuditError("Invalid CI download directory")
    entries = sorted(download_dir.iterdir())
    if len(entries) != len(PACKAGES):
        raise AuditError("RFB archive set must be exactly four packages")
    found: dict[str, dict[str, object]] = {}
    for path in entries:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or not 0 < info.st_size <= MAX_PACKAGE_BYTES
            or path.suffix != ".deb"
        ):
            raise AuditError("Unsafe or oversized RFB package archive")
        package = control(path, "Package")
        version = control(path, "Version")
        architecture = control(path, "Architecture")
        if (
            package not in PACKAGES or package in found
            or not path.name.startswith(package + "_")
            or not VERSION.fullmatch(version)
            or architecture != "amd64"
        ):
            raise AuditError("Unexpected RFB package identity or architecture")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        found[package] = {
            "version": version, "size": info.st_size,
            "sha256": digest, "architecture": architecture,
        }
    if set(found) != set(PACKAGES):
        raise AuditError("Missing expected RFB package")
    minimums = {name: compare(str(found[name]["version"])) for name in LIBRARIES}
    if not all(minimums.values()):
        raise AuditError("LibVNCServer below required USN-8494-1 minimum")
    return {
        "schema": "63d39-rfb-ci-archive-inventory-v1",
        "audit_evidence_pass": True,
        "archive_versions_and_sha256": found,
        "library_at_least_usn_8494_1": minimums,
        "cve_review_blockers": BLOCKERS,
        "package_executed": False,
        "package_installed": False,
        "producer_approved": False,
        "activation_permitted": False,
        "browser_rdp_proven": False,
        "reason": "STOP: Ubuntu advisories, Unix-only behavior and root supervisor not approved",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8")
        if not ci_host_ok(dict(os.environ), release, os.geteuid()):
            raise AuditError("Only unprivileged Ubuntu 26.04 GitHub CI allowed")
        outcome = inventory(args.download_dir)
    except (AuditError, OSError) as exc:
        outcome = {
            "schema": "63d39-rfb-ci-archive-inventory-v1",
            "audit_evidence_pass": False,
            "producer_approved": False,
            "activation_permitted": False,
            "package_installed": False,
            "reason": "STOP: " + str(exc),
        }
    print(json.dumps(outcome, sort_keys=True, indent=2), flush=True)
    return 0 if outcome["audit_evidence_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
