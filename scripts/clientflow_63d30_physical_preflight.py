#!/usr/bin/env python3
"""63D-30 physical GNOME RDP readiness preflight, strictly read-only.

Prints only allowlisted state, not raw grdctl credentials, TLS paths, usernames
or contents of firewall/service files. Does not execute the pilot. Run as root
on the test kiosk only. All subprocess calls are read-only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess

HOST = "viborg1-NUC14MNK-B2"
CLIENT_ID = "3"
KIOSK = "clientflow-kiosk"
SCHEMA = "org.gnome.desktop.remote-desktop.rdp"
RDP_KEYS = {
    "port": "uint16 3389",
    "negotiate-port": "true",
    "screen-share-mode": "'mirror-primary'",
    "view-only": "true",
    "enable": "false",
    "auth-methods": "['credentials']",
    "tls-cert": "''",
    "tls-key": "''",
}
REQUIRED_HELP = (
    "set-credentials", "clear-credentials", "set-tls-key",
    "set-tls-cert", "enable-view-only", "disable-view-only",
    "disable-port-negotiation", "enable-port-negotiation",
    "enable", "disable",
)
GUARD_UNIT = "clientflow-63d29-rdp-guard.service"
GUARD_TABLE = "clientflow_63d29_rdp_guard"
WATCHDOG_TIMER = "clientflow-63d30-rdp-watchdog.timer"
WATCHDOG_SERVICE = "clientflow-63d30-rdp-watchdog.service"
CALENDAR = "*-*-* *:*:0/10"


def call(*args: str, timeout: int = 8) -> tuple[int | None, str, str]:
    try:
        process = subprocess.run(
            args, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return process.returncode, process.stdout.strip(), process.stderr.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None, "", ""


def valid_target(host: str, uid: int, data: object) -> bool:
    return (
        host == HOST and uid == 0 and isinstance(data, dict)
        and str(data.get("CLIENT_ID", data.get("client_id"))) == CLIENT_ID
    )


def rdp_status_section(stdout: str) -> str | None:
    """Return the user-mode RDP block only; ignore VNC Password fields."""
    sections = 0
    inside = False
    captured = []
    for line in stdout.splitlines():
        if line == "RDP:":
            sections += 1
            inside = True
            continue
        if inside and line and not line.startswith((" ", "\t")):
            inside = False
        if inside:
            captured.append(line)
    return "\n".join(captured) if sections == 1 else None

def credential_state(stdout: str) -> str:
    """Fail closed unless both RDP-only credential fields are uniquely empty."""
    rdp = rdp_status_section(stdout)
    if rdp is None:
        return "UNKNOWN"
    for key in ("Username", "Password"):
        values = re.findall(
            rf"(?m)^[ \t]*{key}:[ \t]*([^\r\n]*)$", rdp
        )
        if len(values) != 1:
            return "UNKNOWN"
        if values[0].strip(" \t") != "(empty)":
            return "NOT_EMPTY_OR_UNEXPECTED"
    return "EMPTY"

def listened_ports(output: str) -> list[int]:
    found = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        address = parts[3]
        if ":" not in address:
            continue
        port = address.rsplit(":", 1)[-1]
        if port.isdecimal() and 3389 <= int(port) <= 3398:
            found.add(int(port))
    return sorted(found)


def main() -> int:
    print("===== 63D-30 · FYSISK READ-ONLY PREFLIGHT =====", flush=True)
    try:
        data = json.loads(Path("/etc/clientflow/identity.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("IDENTITY_VERIFIED= FAIL")
        return 2
    if not valid_target(socket.gethostname(), os.geteuid(), data):
        print("IDENTITY_VERIFIED= FAIL")
        return 2
    print("IDENTITY_VERIFIED= PASS")

    checks = {}
    def record(name: str, good: bool, detail: str | None = None) -> None:
        checks[name] = good
        print(name + "=", "PASS" if good else "FAIL", flush=True)
        if detail is not None:
            print(name + "_DETAIL=", detail, flush=True)

    active = Path("/opt/clientflow/active").resolve()
    record("CLIENTFLOW_RELEASE_1248", active.name == "clientflow-1.3.47-seq-1248")
    code, pkg, _ = call("dpkg-query", "-W", "-f=${Version}", "gnome-remote-desktop")
    record("GNOME_RDP_50_2", code == 0 and pkg.startswith("50.2-"), pkg if code == 0 else "unknown")

    code, uid, _ = call("id", "-u", KIOSK)
    if code != 0 or not uid.isdecimal():
        print("KIOSK_USER= FAIL")
        return 2
    bus = Path("/run/user") / uid / "bus"
    if not bus.is_socket():
        print("KIOSK_DBUS= FAIL")
        return 2
    print("KIOSK_DBUS= PASS")
    prefix = (
        "runuser", "-u", KIOSK, "--", "env", "LC_ALL=C",
        f"XDG_RUNTIME_DIR=/run/user/{uid}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={bus}",
    )
    def kiosk(*args: str) -> tuple[int | None, str, str]:
        return call(*(prefix + args))

    code, help_text, _ = kiosk("grdctl", "--help")
    # Some GLib tools emit option text to stderr, but we deliberately never print it.
    record(
        "GRDCTL_REQUIRED_COMMANDS",
        code == 0 and all(token in help_text for token in REQUIRED_HELP),
    )
    settings_ok = True
    for key, expected in RDP_KEYS.items():
        c, v, _ = kiosk("gsettings", "get", SCHEMA, key)
        if c != 0 or v != expected:
            settings_ok = False
        print("RDP_" + key.replace("-", "_").upper() + "_BASELINE=", "PASS" if c == 0 and v == expected else "FAIL")
    checks["GNOME_RDP_SETTINGS_BASELINE"] = settings_ok

    code, raw, _ = kiosk("grdctl", "status")
    query_state = (
        "OK" if code == 0
        else ("TIMEOUT_OR_EXEC_ERROR" if code is None else "EXIT_NONZERO")
    )
    record("GRDCTL_CREDENTIAL_STATUS_QUERY", code == 0, query_state)
    rdp_block = rdp_status_section(raw) if code == 0 else None
    record("GRDCTL_RDP_STATUS_BLOCK_PRESENT", rdp_block is not None)
    state = credential_state(raw) if code == 0 else "UNKNOWN"
    record("RDP_CREDENTIALS_EMPTY", state == "EMPTY", state)

    for label, argv, expected in (
        ("SYSTEM_RDP_INACTIVE", ("systemctl", "is-active", "gnome-remote-desktop.service"), "inactive"),
        ("SYSTEM_RDP_DISABLED", ("systemctl", "is-enabled", "gnome-remote-desktop.service"), "disabled"),
        ("USER_RDP_INACTIVE", ("user", "systemctl", "--user", "is-active", "gnome-remote-desktop.service"), "inactive"),
        ("USER_RDP_DISABLED", ("user", "systemctl", "--user", "is-enabled", "gnome-remote-desktop.service"), "disabled"),
    ):
        if argv[0] == "user":
            c, result, _ = kiosk(*argv[1:])
        else:
            c, result, _ = call(*argv)
        record(label, result == expected)

    for protocol, argv in (
        ("TCP", ("ss", "-H", "-ltn")),
        ("UDP", ("ss", "-H", "-lun")),
    ):
        c, output, _ = call(*argv)
        ports = listened_ports(output) if c == 0 else [0]
        record("NO_" + protocol + "_RDP_LISTENERS", c == 0 and ports == [], str(ports))

    c, _, error = call("nft", "list", "table", "inet", GUARD_TABLE)
    record("NO_63D29_KERNEL_GUARD", c == 1 and "No such file" in error)
    artifacts = (
        "/etc/clientflow/rdp-guard-63d29",
        "/etc/systemd/system/clientflow-63d29-rdp-guard.service",
        "/etc/systemd/system/display-manager.service.d/clientflow-63d29-rdp-guard.conf",
        "/var/lib/clientflow/rdp-pilot-63d30",
        "/var/lib/clientflow/rdp-pilot-bundle-63d30",
        "/etc/systemd/system/" + WATCHDOG_TIMER,
        "/etc/systemd/system/" + WATCHDOG_SERVICE,
        "/run/clientflow-rdp-63d30",
    )
    record("NO_RESIDUAL_PILOT_FILES", all(not Path(x).exists() and not Path(x).is_symlink() for x in artifacts))
    c, _, _ = call("systemd-analyze", "calendar", CALENDAR)
    record("TEN_SECOND_SYSTEMD_CALENDAR_VALID", c == 0)

    c, requires, _ = call(
        "systemctl", "show", "--property=Requires", "--value", "display-manager.service"
    )
    record("DISPLAY_MANAGER_GUARD_DEP_REMOVED", c == 0 and GUARD_UNIT not in requires.split())
    c, state, _ = call("systemctl", "is-active", "display-manager.service")
    record("DISPLAY_MANAGER_ACTIVE", c == 0 and state == "active")

    c, ssh_status, _ = call("systemctl", "is-active", "ssh.service")
    print("SSH_SERVER_RUNNING=", c == 0 and ssh_status == "active")
    print("FREERDP_CLIENT_INSTALLED=", bool(shutil.which("xfreerdp3") or shutil.which("xfreerdp")))
    print("SSH_OR_FREERDP_CONNECTIVITY_TESTED=False")
    print("RDP_CHANGED=False")
    print("SYSTEMD_CHANGED=False")
    print("NETWORK_CHANGED=False")
    print("READ_ONLY=True")
    print("PHYSICAL_PREFLIGHT=", "PASS" if all(checks.values()) else "STOP")
    print("===== FÆRDIG =====")
    return 0 if all(checks.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
