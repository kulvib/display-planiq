#!/usr/bin/env python3
"""Physically bounded browser RDP grant for Viborg1 (client ID 3).

No network services are started here, no credentials are printed, no GNOME
settings are changed. This tool only permits outbound agent -> loopback RDP
while the independently accepted 63D-29/30 physical guard is active. It is
deliberately limited to the original six-minute, self-cleaning physical pilot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import stat
import sys
import time

sys.dont_write_bytecode = True
if __package__:
    from . import clientflow_63d29_persistent_rdp_guard as guard
    from . import clientflow_63d30_local_rdp_pilot as pilot
else:
    import clientflow_63d29_persistent_rdp_guard as guard
    import clientflow_63d30_local_rdp_pilot as pilot

MARKER = Path("/run/clientflow/native-rdp-approved")
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
CLIENT_ID = 3
HOSTNAME = "viborg1-NUC14MNK-B2"


def verify_host() -> tuple[int, Path]:
    if os.geteuid() != 0 or socket.gethostname() != HOSTNAME:
        raise RuntimeError("STOP: kun root på fysisk Viborg1 må godkende piloten")
    uid, runtime = pilot.target()
    if not guard.identity_verified(socket.gethostname(), os.geteuid(),
                                   json.loads(guard.IDENTITY.read_text())):
        raise RuntimeError("STOP: forkert klient-identitet")
    return uid, runtime


def check_physical_guard() -> tuple[int, dict]:
    uid, _ = verify_host()
    state = pilot.state_load()
    if state is None or pilot.deadline_expired(state):
        raise RuntimeError("STOP: fysisk GNOME-pilot er ikke aktiv")
    if not (guard.guard_verified() and pilot.watchdog_verified()):
        raise RuntimeError("STOP: firewall eller automatisk root-watchdog mangler")
    if (state.get("boot_id") != BOOT_ID.read_text().strip()
        or state.get("phase") != "63D-30"):
        raise RuntimeError("STOP: ikke samme opstart/fysiske pilot")
    if not (0 < state["deadline_wall"] - time.time() <= pilot.MAX_SECONDS
            and 0 < state["deadline_mono"] - time.monotonic() <= pilot.MAX_SECONDS):
        raise RuntimeError("STOP: fysisk RDP-vindue er ugyldigt")
    if pilot.listeners() != [3389]:
        raise RuntimeError("STOP: GNOME lytter ikke kun på forventet RDP-port")
    if pilot.get_setting(uid, "enable") != "true":
        raise RuntimeError("STOP: GNOME Desktop Sharing er ikke aktiveret")
    # Accepted 63D-29 guard verifies SYSTEM Remote Login is disabled
    # before starting Desktop Sharing. It cannot be switched on concurrently.
    system = pilot.run("systemctl", "is-active", "gnome-remote-desktop.service")
    if system.stdout.strip() != "inactive":
        raise RuntimeError("STOP: system-Remote-Login må ikke være aktiveret")
    return uid, state


def certificate_fingerprint(uid: int) -> str:
    cert = pilot.tls_directory(uid) / "tls.crt"
    if cert.is_symlink() or not cert.is_file():
        raise RuntimeError("STOP: GNOME RDP-certifikatet mangler")
    directory = cert.parent
    if directory.is_symlink():
        raise RuntimeError("STOP: RDP TLS-mappen må ikke være symlink")
    recorded = pilot.get_setting(uid, "tls-cert")
    if str(cert) not in recorded:
        raise RuntimeError("STOP: GNOME anvender ikke det godkendte TLS-certifikat")
    # Public certificate only. Never read or print the TLS PRIVATE key.
    data = cert.read_text(encoding="ascii")
    digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(data)).hexdigest().upper()
    return ":".join(digest[i:i+2] for i in range(0, len(digest), 2))


def ensure_marker_dir() -> None:
    folder = MARKER.parent
    if folder.is_symlink():
        raise RuntimeError("STOP: /run/clientflow er et symlink")
    if not folder.exists():
        folder.mkdir(mode=0o755, parents=False)
    meta = folder.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
        raise RuntimeError("STOP: /run/clientflow har usikre adgangsrettigheder")
    # Every unprivileged ClientFlow remote-desktop agent must be able to read
    # the non-secret approval file, but cannot create/alter it.
    if not meta.st_mode & 0o005 == 0o005:
        raise RuntimeError("STOP: root-godkendelsesmappen kan ikke læses af agent")


def arm() -> None:
    uid, state = check_physical_guard()
    ensure_marker_dir()
    if MARKER.exists() or MARKER.is_symlink():
        raise RuntimeError("STOP: eksisterende godkendelse - afvæbn først")
    fingerprint = certificate_fingerprint(uid)
    grant = {
        "schema": 1,
        "hostname": HOSTNAME,
        "client_id": CLIENT_ID,
        "boot_id": state["boot_id"],
        "expires_wall": state["deadline_wall"],
        "expires_mono": state["deadline_mono"],
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(MARKER), flags, 0o644)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(json.dumps(grant, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        MARKER.unlink(missing_ok=True)
        raise
    # Revalidate the physical firewall AFTER writing the unprivileged grant.
    try:
        check_physical_guard()
    except Exception:
        MARKER.unlink(missing_ok=True)
        raise
    print("NATIVE_RDP_BROWSER_GRANT=ARMED")
    print("CLIENT_ID=3")
    print("GNOME_TLS_SHA256=" + fingerprint)
    print("RDP_LOGIN_FILE=/run/clientflow-rdp-63d30/credentials (root only; do not paste into chat)")
    print("TIMEOUT_SECONDS_MAX=360")


def disarm() -> None:
    verify_host()
    if MARKER.is_symlink():
        raise RuntimeError("STOP: godkendelsesfilen er symlink")
    if MARKER.exists():
        meta = MARKER.lstat()
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0:
            raise RuntimeError("STOP: ukendt godkendelsesfil")
        MARKER.unlink()
    print("NATIVE_RDP_BROWSER_GRANT=DISARMED")
    print("STOP_63D30_PILOT_BEFORE_REMOVING_FIREWALL=True")


def status() -> None:
    verify_host()
    state = pilot.state_load()
    grant = None
    if MARKER.is_file() and not MARKER.is_symlink():
        try:
            grant = json.loads(MARKER.read_text(encoding="ascii"))
        except (UnicodeError, ValueError, OSError):
            pass
    print("GNOME_RDP_PILOT_ACTIVE=", state is not None and not pilot.deadline_expired(state))
    print("FIREWALL_VERIFIED=", guard.guard_verified())
    print("WATCHDOG_VERIFIED=", pilot.watchdog_verified())
    print("BROWSER_GRANT_PRESENT=", grant is not None)
    print("BROWSER_GRANT_UNEXPIRED=", bool(
        grant and grant.get("boot_id") == BOOT_ID.read_text().strip()
        and grant.get("expires_wall", 0) > time.time()
        and grant.get("expires_mono", 0) > time.monotonic()
    ))
    print("RDP_CREDENTIALS_PRINTED=False")


def main() -> int:
    parser = argparse.ArgumentParser(description="Viborg1 browser-GNOME RDP physical grant")
    parser.add_argument("action", choices=["arm", "disarm", "status"])
    args = parser.parse_args()
    try:
        {"arm": arm, "disarm": disarm, "status": status}[args.action]()
    except (OSError, RuntimeError, ValueError, KeyError, ssl.SSLError) as exc:
        print("NATIVE_RDP_BROWSER_GRANT=STOP", type(exc).__name__, str(exc))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
