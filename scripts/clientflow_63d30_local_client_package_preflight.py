#!/usr/bin/env python3
"""63D-30: read-only apt simulation for loopback-only FreeRDP test dependencies.

Does NOT run apt install/update, enable SSH, launch GNOME RDP, open ports,
or modify any system state. Designed for physical Viborg1 (test client ID 3).
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import socket
import subprocess

HOST = "viborg1-NUC14MNK-B2"
PACKAGES = ("freerdp-x11", "xvfb", "xauth")
MIN_FREE_BYTES = 512 * 1024 * 1024


def call(*args: str, timeout: int = 20):
    try:
        p = subprocess.run(
            args, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None, ""


def candidate(output: str) -> str | None:
    match = re.search(r"(?m)^\s*Candidate:\s*(\S+)\s*$", output)
    if not match or match.group(1) in {"(none)", "none"}:
        return None
    return match.group(1)


def simulation_summary(output: str) -> dict[str, int]:
    return {
        "installs": len(re.findall(r"(?m)^Inst\s+", output)),
        "removals": len(re.findall(r"(?m)^Remv\s+", output)),
        "upgrades": len(re.findall(r"(?m)^Inst\s+\S+\s+\[[^]]+\]", output)),
    }


def main() -> int:
    print("===== 63D-30 · READ-ONLY LOCAL CLIENT DEPENDENCY PREFLIGHT =====", flush=True)
    try:
        ident = json.loads(Path("/etc/clientflow/identity.json").read_text())
        assert socket.gethostname() == HOST
        assert os.geteuid() == 0
        assert str(ident.get("CLIENT_ID", ident.get("client_id"))) == "3"
    except (OSError, ValueError, AssertionError, AttributeError):
        print("VERIFIED_TEST_CLIENT=STOP")
        return 2

    print("VERIFIED_TEST_CLIENT=PASS")
    checks = []
    code, active = call("systemctl", "is-active", "gnome-remote-desktop.service")
    sys_off = active == "inactive"
    print("GNOME_SYSTEM_RDP_INACTIVE=", sys_off)
    checks.append(sys_off)

    # No package installation until the existing kiosk state is safe.
    code, ss = call("ss", "-H", "-ltn")
    listening = (
        code != 0 or any(
            (port := x.split()[3].rsplit(":", 1)[-1]).isdecimal()
            and 3389 <= int(port) <= 3398
            for x in ss.splitlines()
            if len(x.split()) >= 5
        )
    )
    print("NO_TCP_RDP_LISTENERS=", not listening)
    checks.append(not listening)

    proposed = {}
    for pkg in PACKAGES:
        code, output = call("apt-cache", "policy", pkg)
        value = candidate(output) if code == 0 else None
        proposed[pkg] = value
        print("PACKAGE_" + pkg.replace("-", "_").upper() + "_CANDIDATE=", value or "UNAVAILABLE")
        checks.append(value is not None)

    sim = call(
        "apt-get", "-s", "-o", "Debug::NoLocking=1",
        "install", "--no-install-recommends", *PACKAGES,
        timeout=35,
    )
    summary = simulation_summary(sim[1])
    print("APT_INSTALL_SIMULATION=", "PASS" if sim[0] == 0 else "STOP")
    print("SIMULATED_INSTALL_COUNT=", summary["installs"])
    print("SIMULATED_REMOVAL_COUNT=", summary["removals"])
    print("SIMULATED_UPGRADE_COUNT=", summary["upgrades"])
    checks.extend((sim[0] == 0, summary["removals"] == 0))

    stat = os.statvfs("/")
    available = stat.f_bavail * stat.f_frsize
    print("ROOT_FREE_SPACE_MIB=", round(available / (1024 ** 2)))
    checks.append(available >= MIN_FREE_BYTES)
    print("ROOT_FREE_SPACE_OK=", available >= MIN_FREE_BYTES)

    print("SSH_ENABLED_BY_TEST=False")
    print("RDP_ENABLED_BY_TEST=False")
    print("PACKAGES_INSTALLED_BY_TEST=False")
    print("APT_SOURCES_UPDATED_BY_TEST=False")
    print("FIREWALL_CHANGED=False")
    print("READ_ONLY=True")
    print("LOCAL_CLIENT_PACKAGE_PREFLIGHT=", "PASS" if all(checks) else "STOP")
    return 0 if all(checks) else 2


if __name__ == "__main__":
    raise SystemExit(main())
