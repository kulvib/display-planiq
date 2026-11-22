#!/usr/bin/env python3
"""Physical Viborg1 only: re-arm the 6-minute native RDP browser test.

No changes to ClientFlow release 1248, Render, database, or credentials.
Safely reactivates the pinned shadow agent after its automatic rollback,
retains the 17-minute shadow rollback, and uses the existing fail-closed
6-minute GNOME/firewall watchdog. Any uncertain state causes STOP.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import time

HOST = "viborg1-NUC14MNK-B2"
RELEASE = "clientflow-1.3.47-seq-1248"
SOURCE_ROOT = Path("/run/clientflow-native-rdp-pilot-408")
PILOT_SRC = SOURCE_ROOT / "clientflow_63d30_local_rdp_pilot.py"
PILOT_STAGED = Path("/var/lib/clientflow/rdp-pilot-bundle-63d30/clientflow_63d30_local_rdp_pilot.py")
GUARD_SRC = SOURCE_ROOT / "clientflow_63d29_persistent_rdp_guard.py"
APPROVAL_SRC = SOURCE_ROOT / "clientflow_native_rdp_browser_pilot.py"
SOURCE_HASHES = {
    PILOT_SRC: "78972f7c7173a4894abc22d4518b1fc4d3189c76e30dd463715af03ef069",
    GUARD_SRC: "709a5d9b1eba3364dfd2ac21f4e24525b0dc3261236456a9127aac7cfd54c000",
    APPROVAL_SRC: "02c63fc10deb3c0329c5309bdcb19a0edf8fa694c1c0045257cd79c304849e7f",
}
SHADOW_ROOT = Path("/run/clientflow-native-rdp-shadow-408")
SHADOW_LAUNCH = SHADOW_ROOT / "launch.py"
SHADOW_ROLLBACK = SHADOW_ROOT / "rollback.py"
SHADOW_FILES = {
    SHADOW_ROOT / "native_rdp_forwarder.py": "6673244871041dc3bc7cf5a055f821662d71c3bb984f167e05d3143da6d1dc14",
    SHADOW_ROOT / "remote_desktop_agent.py": "a99dc405cd286ec19f70c9e0701a399aa677e2accfefeadda4010f7c39fd4f95",
}
UNIT = "clientflow-remote-desktop-agent.service"
DROPIN = Path("/run/systemd/system/clientflow-remote-desktop-agent.service.d/90-viborg1-shadow-rdp.conf")
OVERRIDE = (
    "[Service]\nExecStart=\n"
    "ExecStart=/opt/clientflow/active/runtime/bin/python -B "
    "/run/clientflow-native-rdp-shadow-408/launch.py\n"
)
TIMER = "clientflow-native-rdp-rearm-rollback-409.timer"
OLD_TIMER = "clientflow-native-rdp-shadow-rollback-408.timer"
PYTHON = "/usr/bin/python3"
RUNTIME_PYTHON = "/opt/clientflow/active/runtime/bin/python"


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RuntimeError("STOP: " + reason)


def process(args: list[str], *, timeout: int = 40) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def call(*args: str, timeout: int = 40, check: bool = True) -> str:
    result = process(list(args), timeout=timeout)
    if check and result.returncode:
        raise RuntimeError("STOP: Kommando fejlede: " + args[0] + " " + args[1])
    return result.stdout.strip()


def valid_source(path: Path, expected_sha: str) -> None:
    require(path.is_file() and not path.is_symlink(), "kilde mangler: " + path.name)
    stat_data = path.stat()
    require(stat_data.st_uid == 0 and stat.S_ISREG(stat_data.st_mode) and not stat_data.st_mode & 0o022,
            "kildens rettigheder er usikre")
    require(stat_data.st_size < 210000 and hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha,
            "kildens SHA-256 afviger: " + path.name)


def verify() -> None:
    require(os.geteuid() == 0 and socket.gethostname() == HOST, "kun root på fysisk Viborg1")
    identity = json.loads(Path("/etc/clientflow/identity.json").read_text())
    require(str(identity.get("CLIENT_ID", identity.get("client_id"))) == "3", "forkert klient-id")
    require(Path("/opt/clientflow/active").resolve().name == RELEASE, "release 1248 er ikke aktiv")
    for file, digest in {**SOURCE_HASHES, **SHADOW_FILES}.items():
        valid_source(file, digest)
    for file in (SHADOW_LAUNCH, SHADOW_ROLLBACK):
        require(file.is_file() and not file.is_symlink() and file.stat().st_uid == 0
                and not file.stat().st_mode & 0o022, "launcher/rollback mangler eller er usikker")
    expected_rollback = f'''from pathlib import Path
import subprocess
OVERRIDE = {OVERRIDE!r}
DROPIN = Path({str(DROPIN)!r})
UNIT = {UNIT!r}
if not DROPIN.is_file() or DROPIN.is_symlink() or DROPIN.read_text() != OVERRIDE:
    raise SystemExit("STOP: afviser ukendt systemd-override")
DROPIN.unlink()
subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=20)
subprocess.run(["systemctl", "restart", UNIT], check=True, timeout=30)
print("VIBORG1_1248_AGENT_RESTORED=True")
'''
    require(SHADOW_ROLLBACK.read_text() == expected_rollback, "rollback-script er ændret")
    check = call(RUNTIME_PYTHON, "-B", str(SHADOW_LAUNCH), "--check")
    require("SHADOW_AGENT_IMPORT=PASS" in check, "shadow-agent inkompatibel")
    print("VERIFIED_PINNED_SOURCES=PASS", flush=True)


def is_active(name: str) -> bool:
    return call("systemctl", "is-active", name, check=False) == "active"


def current_agent() -> str:
    require(is_active(UNIT), "Remote Desktop-agent inaktiv")
    start = call("systemctl", "show", UNIT, "-p", "ExecStart", "--value")
    if str(SHADOW_LAUNCH) in start:
        require(DROPIN.is_file() and not DROPIN.is_symlink() and DROPIN.read_text() == OVERRIDE,
                "ukendt shadow-override")
        return "shadow"
    if "/opt/clientflow/active/runtime/bin/clientflow-remote-desktop-agent" in start:
        require(not DROPIN.exists() and not DROPIN.is_symlink(), "rest-override eksisterer")
        return "original"
    raise RuntimeError("STOP: Ukendt agent-ExecStart")


def rearm_agent() -> None:
    if current_agent() == "shadow":
        require(is_active(TIMER) or is_active(OLD_TIMER), "ingen aktiv rollback-timer")
        print("SHADOW_AGENT=ALREADY_ACTIVE", flush=True)
        return
    if is_active(OLD_TIMER):
        call("systemctl", "stop", OLD_TIMER)
        require(not is_active(OLD_TIMER), "gammel timer kunne ikke stoppes")
    require(not is_active(TIMER), "ny rollback-timer findes allerede")
    require(call("systemctl", "show", TIMER, "-p", "LoadState", "--value", check=False)
            in ("", "not-found"), "rollback-timer-navn er optaget")
    # A fresh, separate rollback timer is armed BEFORE changing ExecStart.
    call("systemd-run", "--unit=clientflow-native-rdp-rearm-rollback-409",
         "--on-active=17min", PYTHON, str(SHADOW_ROLLBACK))
    require(is_active(TIMER), "ny rollback-timer blev ikke aktiv")
    DROPIN.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    try:
        fd = os.open(DROPIN, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(OVERRIDE)
            output.flush()
            os.fsync(output.fileno())
        call("systemctl", "daemon-reload")
        call("systemctl", "restart", UNIT)
        time.sleep(2)
        require(current_agent() == "shadow", "shadow-agent forblev ikke aktiv")
        print("SHADOW_AGENT=ACTIVE; ROLLBACK_MINUTES=17", flush=True)
    except Exception:
        if DROPIN.is_file() and not DROPIN.is_symlink() and DROPIN.read_text() == OVERRIDE:
            DROPIN.unlink()
            call("systemctl", "daemon-reload", check=False)
            call("systemctl", "restart", UNIT, check=False)
        raise


def physical(action: str, *, staged: bool = True, timeout: int = 95) -> None:
    source = PILOT_STAGED if staged else PILOT_SRC
    if staged:
        valid_source(source, SOURCE_HASHES[PILOT_SRC])
    result = process([PYTHON, str(source), action], timeout=timeout)
    if result.stdout:
        print(result.stdout.strip(), flush=True)
    require(result.returncode == 0, "fysisk " + action + " fejlede")


def approve(action: str) -> None:
    result = process([PYTHON, str(APPROVAL_SRC), action], timeout=30)
    if result.stdout:
        print(result.stdout.strip(), flush=True)
    require(result.returncode == 0, "browsergodkendelse " + action + " fejlede")


def start_pilot() -> None:
    state = Path("/var/lib/clientflow/rdp-pilot-63d30/state.json")
    require(not state.exists() and not state.is_symlink(), "tidligere pilot er ikke ryddet op")
    # An expired approval marker is root-owned but persists after watchdog
    # cleanup; explicitly disarm before starting the new six-minute pilot.
    approve("disarm")
    if not PILOT_STAGED.is_file():
        physical("stage", staged=False)
    physical("start")
    try:
        approve("arm")
        physical("probe")
    except Exception:
        try:
            approve("disarm")
        finally:
            physical("stop")
        raise
    print("VIBORG1_NATIVE_RDP_BROWSER_TEST=READY", flush=True)
    print("WINDOW_SECONDS_MAX=360", flush=True)
    print("BROWSER_URL=https://display.planiq.dk/remote-desktop/3?native_rdp=1", flush=True)
    print("CREDENTIAL_FILE=/run/clientflow-rdp-63d30/credentials (vis ikke i chat)", flush=True)
    print("CLIENTFLOW_RELEASE_1248_UNCHANGED=True", flush=True)


def main() -> int:
    try:
        verify()
        rearm_agent()
        start_pilot()
        return 0
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print("PHYSICAL_TEST=STOP", type(exc).__name__, str(exc), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
