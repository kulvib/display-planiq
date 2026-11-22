#!/usr/bin/env python3
"""63D-38: read-only Ubuntu 26.04 x11vnc candidate/LibVNCServer inventory.

Source-disabled candidate decision: NEVER installs/starts an RFB producer.
Its verdict is always STOP until a separate root supervisor and package/CVE
audit are explicitly accepted, independently of a matching package version.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

HOST = "viborg1-NUC14MNK-B2"
CLIENT_ID = "3"
PACKAGES = ("x11vnc", "libvncserver1", "libvncclient1", "tigervnc-scraping-server")
IDENTITY = Path("/etc/clientflow/identity.json")
RELEASE = Path("/etc/os-release")
SECURITY_BASELINE = "0.9.15+dfsg-3ubuntu0.2"

APT_POLICY = ("apt-cache", "policy", *PACKAGES)
DPKG_INSTALLED = (
    "dpkg-query", "-W",
    r"-f=$" + r"{binary:Package}:$" + r"{Version}:$" + r"{Status}\n", *PACKAGES,
)
READ_COMMANDS = (APT_POLICY, DPKG_INSTALLED)
VERSION_RE = re.compile(r"[0-9][A-Za-z0-9.+:~_-]{0,110}\Z")


def read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")[:4096]
    except (OSError, UnicodeError):
        return ""


def target_ok(host: str, euid: int, identity_text: str, release_text: str) -> bool:
    try:
        data = json.loads(identity_text)
    except (ValueError, TypeError):
        return False
    if type(data) is not dict:
        return False
    client = data.get("CLIENT_ID", data.get("client_id"))
    if str(client) != CLIENT_ID:
        return False
    props = {}
    for line in release_text.splitlines():
        key, sep, val = line.partition("=")
        if sep:
            props[key] = val.strip().strip('"')
    return (
        host == HOST and type(euid) is int and euid == 0
        and props.get("ID") == "ubuntu"
        and props.get("VERSION_ID") == "26.04"
    )


def readonly_command(args: tuple[str, ...]) -> tuple[int, str]:
    if args not in READ_COMMANDS:
        raise ValueError("Forbidden preflight operation")
    try:
        result = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""
    return int(result.returncode), result.stdout[:24_000]


def parse_apt_policy(raw: str) -> dict[str, dict[str, str | None]]:
    """Reject unknown package fields and preserve Debian epoch ':' versions."""
    data: dict[str, dict[str, str | None]] = {}
    current: str | None = None
    for line in raw.splitlines():
        if line and not line[0].isspace():
            label = line.removesuffix(":")
            current = label if label in PACKAGES and label not in data else None
            if current:
                data[current] = {"installed": None, "candidate": None}
            continue
        if current is None:
            continue
        entry = line.strip()
        field, sep, value = entry.partition(": ")
        if not sep:
            continue
        key = {"Installed": "installed", "Candidate": "candidate"}.get(field)
        if key is None:
            continue
        value = value.strip()
        if value != "(none)" and VERSION_RE.fullmatch(value):
            data[current][key] = value
    return data


def parse_installed(raw: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for line in raw.splitlines():
        name, separator, suffix = line.partition(":")
        if not separator or name not in PACKAGES or name in versions:
            continue
        version, sep2, status = suffix.rpartition(":")
        if sep2 and status == "install ok installed" and VERSION_RE.fullmatch(version):
            versions[name] = version
    return versions


def dpkg_version_at_least(version: str, baseline: str = SECURITY_BASELINE) -> bool:
    if not VERSION_RE.fullmatch(version) or not VERSION_RE.fullmatch(baseline):
        raise ValueError("Invalid Debian package version")
    try:
        result = subprocess.run(
            ("dpkg", "--compare-versions", version, "ge", baseline),
            check=False, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def assess(*, authorised_host: bool, policy_rc: int, policy_raw: str,
           installed_rc: int, installed_raw: str,
           compare=dpkg_version_at_least) -> dict:
    parsed = parse_apt_policy(policy_raw) if policy_rc == 0 else {}
    versions = parse_installed(installed_raw) if installed_rc in (0, 1) else {}
    libs = ("libvncserver1", "libvncclient1")
    minimums: dict[str, bool | None] = {}
    for name in libs:
        candidate = parsed.get(name, {}).get("candidate")
        minimums[name] = compare(candidate) if candidate else None

    return {
        "schema": "63d38-rfb-provider-read-only-v1",
        "target_verified": authorised_host,
        "policy_query_ok": policy_rc == 0,
        "installed_query_available": installed_rc in (0, 1),
        "installed_versions": versions,
        "candidate_versions": {
            p: parsed.get(p, {}).get("candidate") for p in PACKAGES
        },
        "library_candidate_at_least_usn_8494_1": minimums,
        "security_advisory": {
            "x11vnc": "CVE-2026-32853 needs evaluation for x11vnc on Ubuntu 26.04",
            "tigervnc-scraping-server": "CVE-2026-34352 needs evaluation on Ubuntu 26.04",
            "libvncserver": "USN-8494-1 minimum 0.9.15+dfsg-3ubuntu0.2 on Ubuntu 26.04",
        },
        "producer_approved": False,
        "activation_permitted": False,
        "filesystem_modified": False,
        "package_installation_performed": False,
        "reason": "STOP: package candidate versions alone cannot approve RFB producer",
    }


def main() -> int:
    authorised = target_ok(
        socket.gethostname(), os.geteuid(),
        read_file(IDENTITY), read_file(RELEASE),
    )
    if not authorised:
        print(json.dumps({
            "schema": "63d38-rfb-provider-read-only-v1",
            "target_verified": False, "activation_permitted": False,
            "filesystem_modified": False,
            "reason": "STOP: incorrect host, user, OS or ClientFlow identity",
        }, sort_keys=True, indent=2))
        return 2
    policy_rc, policy = readonly_command(APT_POLICY)
    installed_rc, installed = readonly_command(DPKG_INSTALLED)
    result = assess(
        authorised_host=authorised, policy_rc=policy_rc,
        policy_raw=policy, installed_rc=installed_rc,
        installed_raw=installed,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["policy_query_ok"] and result["installed_query_available"] else 2


if __name__ == "__main__":
    sys.exit(main())
