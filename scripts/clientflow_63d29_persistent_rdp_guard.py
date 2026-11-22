#!/usr/bin/env python3
"""63D-29: persistent, boot-ordered, IPv4/IPv6 RDP containment on Viborg1.

This tool NEVER configures, starts or enables GNOME RDP. It provides only
install/status/remove of a dedicated nftables INPUT guard, retaining all
unrelated networking. It may be used before a separately approved GNOME
RDP pilot, whose watchdog must disable RDP before removing this guard.

Only run against a physical, verified Viborg1 (CLIENT_ID=3) as root.
The operator must use a locally verified, pinned copy of the script.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess

IDENTITY = Path("/etc/clientflow/identity.json")
DIRECTORY = Path("/etc/clientflow/rdp-guard-63d29")
RULE_PATH = DIRECTORY / "guard.nft"
UNIT_NAME = "clientflow-63d29-rdp-guard.service"
UNIT_PATH = Path("/etc/systemd/system") / UNIT_NAME
DROPIN_DIR = Path("/etc/systemd/system/display-manager.service.d")
DROPIN_PATH = DROPIN_DIR / "clientflow-63d29-rdp-guard.conf"
DROPIN = f"""[Unit]\nRequires={UNIT_NAME}\nAfter={UNIT_NAME}\n"""
TABLE_NAME = "clientflow_63d29_rdp_guard"
PORT_LOW, PORT_HIGH = 3389, 3398

RULES = f"""table inet {TABLE_NAME} {{
    chain inbound {{
        type filter hook input priority -150; policy accept;
        iifname != "lo" tcp dport {PORT_LOW}-{PORT_HIGH} drop
        iifname != "lo" udp dport {PORT_LOW}-{PORT_HIGH} drop
    }}
}}
"""

UNIT = f"""[Unit]
Description=ClientFlow 63D-29 fail-closed RDP pilot network guard (TCP/UDP)
DefaultDependencies=no
After=local-fs.target
Before=sysinit.target network-pre.target display-manager.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f {RULE_PATH}

[Install]
WantedBy=sysinit.target
"""


def run(*args: str, timeout: int = 10, input: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), capture_output=True, text=True,
        input=input, timeout=timeout, check=False,
    )


def identity_verified(host: str, uid: int, data: object) -> bool:
    return (
        host == "viborg1-NUC14MNK-B2"
        and uid == 0
        and isinstance(data, dict)
        and str(data.get("CLIENT_ID", data.get("client_id"))) == "3"
    )


def contains_rdp_listener(ss_text: str) -> bool:
    for line in ss_text.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] not in {"LISTEN", "UNCONN"}:
            continue
        address = parts[3]
        if ":" not in address:
            continue
        port = address.rsplit(":", 1)[1]
        if port.isdigit() and PORT_LOW <= int(port) <= PORT_HIGH:
            return True
    return False


def canonical_installed_rules(text: str) -> bool:
    """Verify exact text form of the expected two kernel drop rules.

    nft may print ordering/handles; do not accept a mere substring that could
    appear inside a comment or an unrelated chain. Require full rule lines.
    """
    if not re.search(rf"\btable inet {TABLE_NAME}\s*\{{", text):
        return False
    if not re.search(
        r"\btype filter hook input priority (?:-150|mangle|raw \+ 150); policy accept;",
        text,
    ):
        return False
    rules = set()
    for line in text.splitlines():
        normalized = re.sub(r"\s+# handle \d+.*$", "", line.strip())
        if normalized:
            rules.add(normalized)
    return (
        f'iifname != "lo" tcp dport {PORT_LOW}-{PORT_HIGH} drop' in rules
        and f'iifname != "lo" udp dport {PORT_LOW}-{PORT_HIGH} drop' in rules
    )


def kiosk(*argv: str, uid: str) -> subprocess.CompletedProcess[str]:
    path = Path("/run/user") / uid / "bus"
    return run(
        "runuser", "-u", "clientflow-kiosk", "--", "env",
        f"XDG_RUNTIME_DIR=/run/user/{uid}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={path}",
        *argv,
    )


def target() -> str:
    try:
        identity = json.loads(IDENTITY.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("STOP: Klientidentitet kan ikke læses") from exc
    if not identity_verified(socket.gethostname(), os.geteuid(), identity):
        raise RuntimeError("STOP: Forkert maskine, klient eller ikke root")
    uid_result = run("id", "-u", "clientflow-kiosk")
    if uid_result.returncode != 0 or not uid_result.stdout.strip().isdigit():
        raise RuntimeError("STOP: Ingen kioskbruger")
    uid = uid_result.stdout.strip()
    if not (Path("/run/user") / uid / "bus").is_socket():
        raise RuntimeError("STOP: Ingen aktiv kiosksession")
    return uid


def ensure_rdp_off(uid: str) -> None:
    system = run("systemctl", "is-active", "gnome-remote-desktop.service")
    if system.stdout.strip() != "inactive":
        raise RuntimeError("STOP: System Remote Login ikke bevisligt inaktiv")
    system_enable = run("systemctl", "is-enabled", "gnome-remote-desktop.service")
    if system_enable.stdout.strip() != "disabled":
        raise RuntimeError("STOP: System Remote Login er ikke bevisligt disabled")
    user = kiosk(
        "systemctl", "--user", "is-active", "gnome-remote-desktop.service",
        uid=uid,
    )
    if user.stdout.strip() != "inactive":
        raise RuntimeError("STOP: GNOME Desktop Sharing ikke bevisligt inaktiv")
    user_enable = kiosk(
        "systemctl", "--user", "is-enabled", "gnome-remote-desktop.service",
        uid=uid,
    )
    if user_enable.stdout.strip() != "disabled":
        raise RuntimeError("STOP: GNOME Desktop Sharing er ikke bevisligt disabled")
    enabled = kiosk(
        "gsettings", "get", "org.gnome.desktop.remote-desktop.rdp", "enable",
        uid=uid,
    )
    if enabled.returncode != 0 or enabled.stdout.strip() != "false":
        raise RuntimeError("STOP: RDP gsettings enable skal være false")
    for args in (("ss", "-H", "-ltn"), ("ss", "-H", "-lun")):
        p = run(*args)
        if p.returncode != 0 or contains_rdp_listener(p.stdout):
            raise RuntimeError("STOP: En RDP-port 3389-3398 lytter allerede")


def guard_exists() -> bool:
    p = run("nft", "list", "table", "inet", TABLE_NAME)
    if p.returncode == 0:
        return True
    if p.returncode == 1 and "No such file" in p.stderr:
        return False
    raise RuntimeError("STOP: nft tilstand ukendt")


def guard_verified() -> bool:
    p = run("nft", "list", "table", "inet", TABLE_NAME)
    return p.returncode == 0 and canonical_installed_rules(p.stdout)


def require_clean_install() -> None:
    if DIRECTORY.exists() or UNIT_PATH.exists() or UNIT_PATH.is_symlink():
        raise RuntimeError("STOP: Guard-filer eksisterer allerede")
    if DROPIN_PATH.exists() or DROPIN_PATH.is_symlink() or DROPIN_DIR.is_symlink():
        raise RuntimeError("STOP: Display manager drop-in eksisterer allerede")
    display_manager = run("systemctl", "show", "--property=LoadState", "--value", "display-manager.service")
    if display_manager.returncode != 0 or display_manager.stdout.strip() != "loaded":
        raise RuntimeError("STOP: Display manager service er ikke verificeret")
    if guard_exists():
        raise RuntimeError("STOP: Guard-tabel eksisterer allerede")
    if shutil.which("nft") != "/usr/sbin/nft":
        raise RuntimeError("STOP: nft-sti afviger fra forventet")
    if run("nft", "--check", "--file", "-", input=RULES).returncode != 0:
        raise RuntimeError("STOP: nft syntax")
    if not canonical_installed_rules(RULES):
        raise RuntimeError("STOP: Uventet firewallregler")
    # Never overlay an existing OS nftables boot service which could flush tables.
    boot = run("systemctl", "is-enabled", "nftables.service")
    if boot.stdout.strip() not in {"disabled", "masked", "not-found", "static"}:
        raise RuntimeError("STOP: nftables.service har ukendt boot-kontrakt")


def write_exclusive(path: Path, content: str, mode: int) -> None:
    with path.open("x", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), mode)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def install_guard(uid: str) -> None:
    ensure_rdp_off(uid)
    require_clean_install()
    print("PREFLIGHT=PASS", flush=True)
    DIRECTORY.mkdir(mode=0o700, parents=False, exist_ok=False)
    write_exclusive(RULE_PATH, RULES, 0o600)
    write_exclusive(UNIT_PATH, UNIT, 0o644)
    DROPIN_DIR.mkdir(mode=0o755, parents=True, exist_ok=True)
    write_exclusive(DROPIN_PATH, DROPIN, 0o644)
    if run("systemctl", "daemon-reload").returncode != 0:
        raise RuntimeError("STOP: systemd daemon-reload fejlede")
    # Enable on sysinit.target, BEFORE display-manager and the kiosk login.
    unit_result = run("systemctl", "enable", "--now", UNIT_NAME, timeout=20)
    if unit_result.returncode != 0:
        raise RuntimeError("STOP: boot-guard kan ikke aktiveres")
    enabled = run("systemctl", "is-enabled", UNIT_NAME)
    active = run("systemctl", "is-active", UNIT_NAME)
    if enabled.stdout.strip() != "enabled" or active.stdout.strip() != "active":
        raise RuntimeError("STOP: Guard er ikke aktiv og enabled")
    if not guard_verified():
        raise RuntimeError("STOP: Kernereglerne matcher ikke expected TCP/UDP drop")
    dependency = run("systemctl", "show", "--property=DropInPaths", "--value", "display-manager.service")
    if dependency.returncode != 0 or str(DROPIN_PATH) not in dependency.stdout.split():
        raise RuntimeError("STOP: Display manager fail-closed dependency ikke aktiveret")
    print("BOOT_GUARD_ENABLED=True")
    print("DISPLAY_MANAGER_REQUIRES_GUARD=True")
    print("KERNEL_IPV4_IPV6_TCP_UDP_GUARD=VERIFIED")
    print("RDP_ENABLED_BY_TEST=False")
    print("GUARD_PERSISTS_UNTIL_EXPLICIT_SAFE_REMOVE=True")
    print("=== 63D-29 GUARD INSTALLED ===")


def remove_guard(uid: str) -> None:
    # On any failure: keep blocking RDP; don't uninstall boot protection.
    ensure_rdp_off(uid)
    if not guard_verified():
        raise RuntimeError("STOP: Guard mismatch; manual safety inspection required")
    if not UNIT_PATH.is_file() or UNIT_PATH.is_symlink():
        raise RuntimeError("STOP: Ukendt guard service")
    if UNIT_PATH.read_text(encoding="utf-8") != UNIT:
        raise RuntimeError("STOP: Guard service ikke identisk")
    if RULE_PATH.read_text(encoding="utf-8") != RULES:
        raise RuntimeError("STOP: Guard regler ikke identiske")
    if not DROPIN_PATH.is_file() or DROPIN_PATH.is_symlink():
        raise RuntimeError("STOP: Display manager dependency mangler")
    if DROPIN_PATH.read_text(encoding="utf-8") != DROPIN:
        raise RuntimeError("STOP: Display manager dependency er ændret")
    # Verify off AGAIN immediately before unprotecting network.
    ensure_rdp_off(uid)
    # Make sure the session service is active before touching dependencies.
    manager_before = run("systemctl", "is-active", "display-manager.service")
    if manager_before.stdout.strip() != "active":
        raise RuntimeError("STOP: display-manager er ikke aktiv før guard-oprydning")
    # Remove the strong dependency first. Otherwise stopping the guard can
    # stop the running display manager via Requires=, disrupting the kiosk.
    DROPIN_PATH.unlink()
    if run("systemctl", "daemon-reload").returncode != 0:
        raise RuntimeError("STOP: Kunne ikke genindlæse display manager dependency")
    # Explicitly prove that systemd unloaded the dependency before stopping
    # the guard. On uncertainty retain the active guard and stop.
    manager_requires = run(
        "systemctl", "show", "--property=Requires", "--value", "display-manager.service",
    )
    if manager_requires.returncode != 0 or UNIT_NAME in manager_requires.stdout.split():
        raise RuntimeError("STOP: display-manager kræver stadig guard; beholder firewall")
    manager_after = run("systemctl", "is-active", "display-manager.service")
    if manager_after.stdout.strip() != "active":
        raise RuntimeError("STOP: display-manager er ikke aktiv efter daemon-reload")
    ensure_rdp_off(uid)
    if run("systemctl", "disable", "--now", UNIT_NAME, timeout=20).returncode != 0:
        raise RuntimeError("STOP: Kunne ikke deaktivere boot-guard")
    delete = run("nft", "delete", "table", "inet", TABLE_NAME)
    if delete.returncode != 0:
        raise RuntimeError("STOP: Kunne ikke fjerne guard-tabel")
    UNIT_PATH.unlink()
    RULE_PATH.unlink()
    DIRECTORY.rmdir()
    try:
        DROPIN_DIR.rmdir()
    except OSError:
        pass  # Preserve any other existing display-manager drop-ins.
    run("systemctl", "daemon-reload")
    print("RDP_VERIFIED_OFF=True")
    print("FIREWALL_GUARD_REMOVED=True")
    print("=== 63D-29 GUARD REMOVED ===")


def status(uid: str) -> None:
    enabled = run("systemctl", "is-enabled", UNIT_NAME).stdout.strip()
    active = run("systemctl", "is-active", UNIT_NAME).stdout.strip()
    try:
        guard = guard_verified()
    except (OSError, subprocess.TimeoutExpired):
        guard = False
    print("BOOT_GUARD_ENABLED=", enabled == "enabled")
    print("BOOT_GUARD_ACTIVE=", active == "active")
    print("KERNEL_DROP_RULES_MATCH=", guard)
    dep = run("systemctl", "show", "--property=DropInPaths", "--value", "display-manager.service")
    print("DISPLAY_MANAGER_REQUIRES_GUARD=", dep.returncode == 0 and str(DROPIN_PATH) in dep.stdout.split())
    try:
        ensure_rdp_off(uid)
        print("GNOME_RDP_OFF= True")
    except (RuntimeError, subprocess.TimeoutExpired):
        print("GNOME_RDP_OFF= NOT_VERIFIED")
    print("CONFIGURATION_CHANGED_BY_STATUS= False")


def main() -> int:
    parser = argparse.ArgumentParser(description="63D-29: persistent RDP network guard")
    parser.add_argument("action", choices=["install", "status", "remove", "drill"])
    args = parser.parse_args()
    print("===== 63D-29 · PERSISTENT RDP NETWORK GUARD =====", flush=True)
    try:
        uid = target()
        if args.action == "install":
            install_guard(uid)
        elif args.action == "drill":
            # Guard-only drill: no RDP activation, remove after kernel verification.
            # If any unexpected state blocks removal, fail closed and retain guard.
            install_guard(uid)
            status(uid)
            remove_guard(uid)
        elif args.action == "remove":
            remove_guard(uid)
        else:
            status(uid)
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print("STOP=", type(exc).__name__, str(exc), flush=True)
        print("NO_RDP_SERVICE_WAS_STARTED_BY_THIS_TOOL=True", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
