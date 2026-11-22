#!/usr/bin/env python3
"""63D-24: read-only GNOME RDP feasibility inventory on physical Viborg1.

No service starts/stops, connections, configuration writes, credential reads,
package installation, firewall changes, network probes, or daemon reloads.
This is evidence collection, NOT permission to expose RDP or deploy Guacamole.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from typing import Any

EXPECTED_HOST = "viborg1-NUC14MNK-B2"
EXPECTED_CLIENT_ID = "3"
KIOSK_USER = "clientflow-kiosk"
IDENTITY = Path("/etc/clientflow/identity.json")


def validate_target(host: str, uid: int, identity: dict[str, Any]) -> None:
    if host != EXPECTED_HOST or uid != 0:
        raise ValueError("STOP: kun root på den fysiske Viborg1 er tilladt")
    client_id = identity.get("CLIENT_ID", identity.get("client_id"))
    if str(client_id) != EXPECTED_CLIENT_ID:
        raise ValueError("STOP: forkert ClientFlow-klientidentitet")


def command(*args: str, timeout: int = 5, env: dict[str, str] | None = None) -> tuple[int | None, str]:
    """Never invoke shell; bound time and emit only an allowlisted command result."""
    try:
        p = subprocess.run(
            list(args), capture_output=True, text=True,
            check=False, timeout=timeout, env=env,
        )
        return (p.returncode, p.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return (None, "")


def service_active(*args: str) -> str:
    code, out = command(*args)
    if code is None:
        return "unknown"
    if code == 0 and out == "active":
        return "active"
    if out in {"inactive", "failed", "activating", "deactivating"}:
        return out
    return "unknown"


def rdp_listener_summary(ss_output: str) -> dict[str, Any]:
    """No addresses/port banners are included in the report."""
    seen = 0
    non_loopback = False
    for row in ss_output.splitlines():
        fields = row.split()
        if len(fields) < 5 or fields[0] != "LISTEN":
            continue
        address = fields[3]
        if ":" not in address:
            continue
        host, port = address.rsplit(":", 1)
        if port not in {"3389", "3390"}:
            continue
        seen += 1
        if host.strip("[]") not in {"127.0.0.1", "::1", "localhost"}:
            non_loopback = True
    return {
        "rdp_listener_count": seen,
        "rdp_nonloopback_listener_present": non_loopback,
    }


def snapshot() -> dict[str, Any]:
    identity = json.loads(IDENTITY.read_text(encoding="utf-8"))
    if not isinstance(identity, dict):
        raise ValueError("STOP: uventet identity-format")
    validate_target(socket.gethostname(), os.geteuid(), identity)

    uid_code, uid_text = command("id", "-u", KIOSK_USER)
    if uid_code != 0 or not uid_text.isdigit():
        raise ValueError("STOP: kioskbrugeren mangler")

    uid = int(uid_text)
    runtime = Path(f"/run/user/{uid}")
    bus = runtime / "bus"
    bus_present = bus.is_socket()

    pkg_status, pkg_output = command(
        "dpkg-query", "-W", "-f=${Status}", "gnome-remote-desktop",
    )
    installed = pkg_status == 0 and pkg_output == "install ok installed"

    os_release = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith(("ID=", "VERSION_ID=")):
                k, v = line.split("=", 1)
                os_release[k] = v.strip('"')
    except OSError:
        pass

    if bus_present:
        user_service = service_active(
            "runuser", "-u", KIOSK_USER, "--", "env",
            f"XDG_RUNTIME_DIR={runtime}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path={bus}",
            "systemctl", "--user", "is-active", "gnome-remote-desktop.service",
        )
    else:
        user_service = "unknown"

    ss_code, ss_output = command("ss", "-H", "-ltn")
    ports = rdp_listener_summary(ss_output) if ss_code == 0 else {
        "rdp_listener_count": None,
        "rdp_nonloopback_listener_present": None,
    }

    return {
        "phase": "63D-24",
        "read_only": True,
        "host_verified": True,
        "client_id_verified": 3,
        "system": os_release,
        "gnome_remote_desktop_installed": installed,
        "grdctl_available": bool(shutil.which("grdctl")),
        "kiosk_user_runtime_available": runtime.is_dir(),
        "kiosk_user_dbus_available": bus_present,
        "gnome_remote_assistance_user_service": user_service,
        "current_clientflow_rd_agent": service_active(
            "systemctl", "is-active", "clientflow-remote-desktop-agent.service",
        ),
        **ports,
        "rdp_connection_tested": False,
        "https_443_reverse_transport_tested": False,
        "render_capacity_tested": False,
        "kiosk_configuration_changed": False,
        "interpretation": (
            "Inventory only; disabled GNOME RDP is not evidence of incompatibility. "
            "Remote Login/headless mode MUST NOT replace the active kiosk session."
        ),
    }


def main() -> int:
    try:
        result = snapshot()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("PREFLIGHT=STOP", type(exc).__name__, str(exc))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
