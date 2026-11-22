#!/usr/bin/env python3
"""63D-25: guarded nftables installation/rollback drill. Does NOT start RDP.

Run only on physical Viborg1 (client 3) as root. Installs a single short-lived
inet INPUT drop table for TCP 3389/3390 on non-loopback interfaces; verifies
the kernel rule and removes exactly this table. A systemd timer is armed BEFORE
the rule is installed to recover if the Python process is interrupted.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import uuid

TABLE = "clientflow_63d25_rdp_guard"
UNIT = "clientflow-63d25-rollback-"
IDENTITY = Path("/etc/clientflow/identity.json")
RULES = f"""
table inet {TABLE} {{
    chain inbound {{
        type filter hook input priority -100; policy accept;
        iifname != "lo" tcp dport {{ 3389, 3390 }} drop
    }}
}}
"""


def run(*argv: str, input: str | None = None, timeout: int = 12) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), input=input, capture_output=True, text=True,
        timeout=timeout, check=False,
    )


def validated_identity(*, host: str, root_uid: int, document: dict) -> None:
    if host != "viborg1-NUC14MNK-B2" or root_uid != 0:
        raise RuntimeError("STOP: Forkert vært eller ikke root")
    if str(document.get("CLIENT_ID", document.get("client_id"))) != "3":
        raise RuntimeError("STOP: Forkert ClientFlow identitet")


def validate_table_output(output: str) -> bool:
    """Check actual nft output; a dry-run alone cannot meet the pilot gate."""
    normalized = re.sub(r"\s+", " ", output)
    return all((
        f"table inet {TABLE}" in normalized,
        "hook input priority" in normalized,
        "policy accept;" in normalized,
        'iifname != "lo"' in normalized,
        "tcp dport" in normalized,
        "3389" in normalized and "3390" in normalized,
        "drop" in normalized,
    ))


def no_rdp_listener(ss_output: str) -> bool:
    for line in ss_output.splitlines():
        parts = line.split()
        if len(parts) > 4 and parts[0] == "LISTEN":
            local_address = parts[3]
            if ":" in local_address and local_address.rsplit(":", 1)[1] in ("3389", "3390"):
                return False
    return True


def run_preflight() -> None:
    document = json.loads(IDENTITY.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("STOP: Ugyldig identitetsfil")
    validated_identity(host=socket.gethostname(), root_uid=os.geteuid(), document=document)
    services = ("gnome-remote-desktop.service",)
    for unit in services:
        state = run("systemctl", "is-active", unit)
        if state.returncode is None or state.stdout.strip() not in ("inactive", "failed"):
            raise RuntimeError("STOP: GNOME system RDP skal være inaktiv")
    uid_result = run("id", "-u", "clientflow-kiosk")
    if uid_result.returncode != 0 or not uid_result.stdout.strip().isdigit():
        raise RuntimeError("STOP: kioskbruger mangler")
    runtime = Path("/run/user") / uid_result.stdout.strip()
    if not (runtime / "bus").is_socket():
        raise RuntimeError("STOP: Kiosk D-Bus mangler")
    user_state = run(
        "runuser", "-u", "clientflow-kiosk", "--", "env",
        f"XDG_RUNTIME_DIR={runtime}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime / 'bus'}",
        "systemctl", "--user", "is-active", "gnome-remote-desktop.service",
    )
    if user_state.stdout.strip() != "inactive":
        raise RuntimeError("STOP: GNOME user-RDP skal være inaktiv")
    sockets = run("ss", "-H", "-ltn")
    if sockets.returncode != 0 or not no_rdp_listener(sockets.stdout):
        raise RuntimeError("STOP: Der lytter allerede en RDP-tjeneste")
    current_table = run("nft", "list", "table", "inet", TABLE)
    if current_table.returncode == 0:
        raise RuntimeError("STOP: Beskyt eksisterende nft-tabel")
    if current_table.returncode != 1 or "No such file" not in current_table.stderr:
        raise RuntimeError("STOP: Kunne ikke bevise fravær af guard-tabel")
    check = run("nft", "--check", "--file", "-", input=RULES)
    if check.returncode != 0:
        raise RuntimeError("STOP: nft syntaksvalidering fejlede")


def main() -> int:
    print("===== 63D-25 · LIVE NFT FIREWALL GUARD-ONLY DRILL =====", flush=True)
    try:
        run_preflight()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("PREFLIGHT=STOP", type(exc).__name__, str(exc), flush=True)
        return 2

    token = UNIT + uuid.uuid4().hex[:8]
    scheduled = False
    installed = False
    removed = False
    try:
        # The rollback timer must exist before installing any filter table.
        timer = run(
            "systemd-run", "--unit=" + token, "--on-active=120s",
            "/usr/sbin/nft", "delete", "table", "inet", TABLE,
        )
        if timer.returncode:
            raise RuntimeError("Kunne ikke armere tidsstyret rollback")
        scheduled = True
        check_timer = run("systemctl", "is-active", token + ".timer")
        if check_timer.stdout.strip() != "active":
            raise RuntimeError("Rollback-timer blev ikke verificeret")
        print("ROLLBACK_TIMER=ARMED_120_SECONDS", flush=True)

        installed_command = run("nft", "--file", "-", input=RULES)
        if installed_command.returncode:
            raise RuntimeError("nft kunne ikke installere guard")
        installed = True

        observed = run("nft", "list", "table", "inet", TABLE)
        if observed.returncode or not validate_table_output(observed.stdout):
            raise RuntimeError("STOP: Installeret firewallregel matcher ikke forventning")

        print("KERNEL_RULE_INSTALLED_AND_VERIFIED=True", flush=True)
        print("RDP_ENABLED=False", flush=True)
        print("RDP_CONNECTION_TESTED=False", flush=True)
        time.sleep(4)
        return_code = 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("GUARD_DRILL=STOP", type(exc).__name__, str(exc), flush=True)
        return_code = 3
    finally:
        # Never start or enable GNOME RDP in this drill.
        if installed:
            deleted = run("nft", "delete", "table", "inet", TABLE)
            removed = deleted.returncode == 0
        else:
            # Ensure a partially installed table is not left behind.
            current = run("nft", "list", "table", "inet", TABLE)
            if current.returncode == 0:
                removed = run("nft", "delete", "table", "inet", TABLE).returncode == 0
            else:
                removed = True
        if scheduled and removed:
            run("systemctl", "stop", token + ".timer")
        print("NFT_GUARD_REMOVED=", removed, flush=True)
        print("ROLLBACK_FAILSAFE_ARMED=", scheduled and not removed, flush=True)
        print("RDP_NEVER_ENABLED=True", flush=True)
        print("===== FÆRDIG =====", flush=True)
        if not removed:
            return_code = 4
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
