#!/usr/bin/env python3
"""63D-37: READ-ONLY future RFB producer feasibility/security inventory.

No package manager writes, systemd changes, process starts, nft commands that
change rules, disk writes or service activation. Output is intentionally a STOP
until Ubuntu 26.04 x11vnc/TigerVNC CVEs have been independently approved.
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
CLIENT = "3"
IDENTITY_PATH = Path("/etc/clientflow/identity.json")
OS_RELEASE = Path("/etc/os-release")
RUNTIME_DIR = Path("/run/clientflow/native-rfb")

# Independently re-evaluate; do not convert package availability to approval.
BLOCKED_CVES = {
    "x11vnc": "CVE-2026-32853",
    "tigervnc-scraping-server": "CVE-2026-34352",
}
PACKAGES = ("x11vnc", "tigervnc-scraping-server", "freerdp-x11", "xvfb", "xauth")
_READ_ONLY_COMMANDS = (
    ("dpkg-query", "-W", "-f=${Package}:${Version}:${Status}\\n", *PACKAGES),
    ("ss", "-H", "-lntup"),
    ("nft", "list", "table", "inet", "clientflow_63d29_rdp_guard"),
)


def safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")[:4096]
    except (OSError, UnicodeError):
        return ""


def run_readonly(args: tuple[str, ...]) -> tuple[int, str]:
    if args not in _READ_ONLY_COMMANDS:
        raise ValueError("disallowed command outside read-only preflight")
    try:
        done = subprocess.run(
            args, capture_output=True, text=True, timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""
    return int(done.returncode), done.stdout[:8192]


def read_identity(raw: str) -> str | None:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if type(data) is not dict:
        return None
    return str(data.get("CLIENT_ID", data.get("client_id", "")))


def parse_os_release(text: str) -> tuple[str, str]:
    props = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        props[name] = value.strip().strip('"')
    return props.get("ID", ""), props.get("VERSION_ID", "")


def external_tcp_vnc_listener(text: str) -> bool:
    """Detect externally bound TCP or UDP RDP/VNC ports from ss -lntup."""
    for raw in text.splitlines():
        columns = raw.split()
        if not columns:
            continue
        if columns[0] in {"tcp", "udp"}:
            if len(columns) < 5:
                return True
            _protocol, state, local = columns[0], columns[1], columns[4]
        elif columns[0] in {"LISTEN", "UNCONN"}:
            if len(columns) < 4:
                return True
            _protocol, state, local = "tcp", columns[0], columns[3]
        else:
            continue
        if state not in {"LISTEN", "UNCONN"}:
            continue
        match = re.search(r":(\d+)$", local)
        if match is None:
            return True
        port = int(match.group(1))
        if (3389 <= port <= 3398 or 5900 <= port <= 5999) and not (
            local.startswith("127.0.0.1:") or local.startswith("[::1]:")
        ):
            return True
    return False


def installed_versions(raw: str) -> dict[str, str]:
    """Only expose simple package versions; never execute or trust output."""
    found = {}
    for line in raw.splitlines():
        name, first_colon, tail = line.partition(":")
        if not first_colon:
            continue
        # Debian package versions may contain an epoch (e.g. Xvfb 2:21).
        # Preserve it: package name is before the first colon, status after
        # the last colon. Never trust output from a shell or an unknown pkg.
        version, last_colon, status = tail.rpartition(":")
        if not last_colon:
            continue
        if (
            name in PACKAGES and name not in found
            and re.fullmatch(r"[A-Za-z0-9.+:~_-]{1,100}", version)
            and status == "install ok installed"
        ):
            found[name] = version
    return found


def assess(
    *, hostname: str, euid: int, identity: str | None, distro: str,
    version: str, commands: dict[tuple[str, ...], tuple[int, str]],
    runtime_dir_present: bool,
) -> dict:
    pkg_code, pkg_text = commands.get(_READ_ONLY_COMMANDS[0], (-1, ""))
    ss_code, ss_text = commands.get(_READ_ONLY_COMMANDS[1], (-1, ""))
    nft_code, nft_text = commands.get(_READ_ONLY_COMMANDS[2], (-1, ""))
    target_ok = (hostname == HOST and euid == 0 and identity == CLIENT)
    os_ok = (distro == "ubuntu" and version == "26.04")
    guard_seen = (nft_code == 0 and "clientflow_63d29_rdp_guard" in nft_text)
    network_ok = (ss_code == 0 and not external_tcp_vnc_listener(ss_text))
    return {
        "schema": "63d37-rfb-readonly-v1",
        "target_verified": target_ok,
        "ubuntu_26_04_verified": os_ok,
        "guard_table_visible": guard_seen,
        "external_rdp_vnc_ports_clear": network_ok,
        "package_inventory_available": pkg_code in (0, 1),
        "native_rfb_runtime_present": runtime_dir_present,
        "candidate_packages": sorted(PACKAGES),
        "installed_versions": installed_versions(pkg_text),
        "known_blockers": dict(BLOCKED_CVES),
        "producer_security_approved": False,
        "activation_permitted": False,
        "filesystem_modified": False,
        "reason": "STOP: RFB producer CVE review and root supervision not accepted",
    }


def main() -> int:
    outputs = {cmd: run_readonly(cmd) for cmd in _READ_ONLY_COMMANDS}
    distro, version = parse_os_release(safe_read(OS_RELEASE))
    result = assess(
        hostname=socket.gethostname(),
        euid=os.geteuid(),
        identity=read_identity(safe_read(IDENTITY_PATH)),
        distro=distro, version=version,
        commands=outputs,
        runtime_dir_present=RUNTIME_DIR.exists(),
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    # Invalid host/environment is an error; a valid host still reports STOP.
    return 0 if result["target_verified"] and result["ubuntu_26_04_verified"] else 2


if __name__ == "__main__":
    sys.exit(main())
