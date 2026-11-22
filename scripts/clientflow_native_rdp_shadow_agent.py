#!/usr/bin/env python3
"""Temporary, auto-reverting native RDP agent overlay on physical Viborg1.

Use BEFORE building ClientFlow 1249. No production release, database,
credential, kiosk or other ClientFlow service is overwritten. On reboot the
systemd override disappears. A transient root timer restores 1248 after 25m.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import time
import urllib.request

SOURCE_SHA = "44e5d5093fb409b4ebf38c968013b4608d62e7ad"
SOURCE_FILES = {
    "native_rdp_forwarder.py": "6673244871041dc3bc7cf5a055f821662d71c3bb984f167e05d3143da6d1dc14",
    "remote_desktop_agent.py": "a99dc405cd286ec19f70c9e0701a399aa677e2accfefeadda4010f7c39fd4f95",
}
ROOT = Path("/run/clientflow-native-rdp-shadow-408")
UNIT = "clientflow-remote-desktop-agent.service"
DROPIN_DIR = Path("/run/systemd/system") / f"{UNIT}.d"
DROPIN = DROPIN_DIR / "90-viborg1-shadow-rdp.conf"
ROLLBACK_TIMER = "clientflow-native-rdp-shadow-rollback-408.timer"
PYTHON = Path("/opt/clientflow/active/runtime/bin/python")
LAUNCHER = ROOT / "launch.py"
ROLLBACK = ROOT / "rollback.py"
ORIGINAL_BINARY = Path("/opt/clientflow/active/runtime/bin/clientflow-remote-desktop-agent")
EXPECTED_RELEASE = "clientflow-1.3.47-seq-1248"
OVERRIDE = (
    "[Service]\nExecStart=\nExecStart="
    f"{PYTHON} -B {LAUNCHER}\n"
)


def call(*argv: str, timeout: int = 25) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), capture_output=True, text=True,
                          timeout=timeout, check=False)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError("STOP: " + message)


def check_host() -> None:
    require(os.geteuid() == 0 and socket.gethostname() == "viborg1-NUC14MNK-B2",
            "root på fysisk Viborg1 er påkrævet")
    identity = json.loads(Path("/etc/clientflow/identity.json").read_text())
    require(str(identity.get("CLIENT_ID", identity.get("client_id"))) == "3",
            "forkert klient-ID")
    active = Path("/opt/clientflow/active")
    require(active.exists() and active.resolve().name == EXPECTED_RELEASE,
            "den godkendte 1248-base er ikke længere aktiv")
    require(PYTHON.is_file() and os.access(PYTHON, os.X_OK),
            "den installerede Python-venv mangler")
    require(ORIGINAL_BINARY.is_file(), "den eksisterende agent mangler")


def status() -> None:
    check_host()
    active = call("systemctl", "is-active", UNIT)
    watchdog = call("systemctl", "is-active", "clientflow-63d30-rdp-watchdog.timer")
    rollback = call("systemctl", "is-active", ROLLBACK_TIMER)
    print("ACTIVE_RELEASE=1248")
    print("RDP_AGENT_ACTIVE=", active.stdout.strip() == "active")
    print("PHYSICAL_WATCHDOG_ACTIVE=", watchdog.stdout.strip() == "active")
    print("SHADOW_OVERRIDE_PRESENT=", DROPIN.is_file())
    print("SHADOW_ROLLBACK_TIMER_ACTIVE=", rollback.stdout.strip() == "active")
    print("NATIVE_RDP_BROWSER_GRANT_PRESENT=", Path("/run/clientflow/native-rdp-approved").exists())


def write_new(path: Path, content: bytes, mode: int = 0o644) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def prepare() -> None:
    require(not ROOT.exists() and not ROOT.is_symlink(), "midlertidig agentmappe eksisterer")
    require(not DROPIN.exists() and not DROPIN.is_symlink(), "systemd-override eksisterer")
    require(call("systemctl", "is-active", UNIT).stdout.strip() == "active",
            "1248 Remote Desktop-agent er ikke aktiv")
    require(call("systemctl", "is-active", "clientflow-63d30-rdp-watchdog.timer").stdout.strip() == "active",
            "fysisk GNOME RDP-watchdog er ikke aktiv")
    require(call("systemctl", "is-active", ROLLBACK_TIMER).stdout.strip() != "active",
            "en tidligere rollback-timer er stadig aktiv")
    old = call("systemctl", "show", UNIT, "-p", "ExecStart", "--value")
    require(old.returncode == 0 and str(ORIGINAL_BINARY) in old.stdout,
            "en ukendt agent-ExecStart eksisterer; må ikke overskrives")
    ROOT.mkdir(mode=0o755)
    ROOT.chmod(0o755)
    for name, digest in SOURCE_FILES.items():
        uri = (f"https://raw.githubusercontent.com/kulvib/display-planiq/{SOURCE_SHA}"
               f"/client/runtime/clientflow_runtime/{name}")
        req = urllib.request.Request(uri, headers={"User-Agent": "Viborg1-native-RDP-shadow-408"})
        with urllib.request.urlopen(req, timeout=25) as response:
            contents = response.read(200001)
        require(0 < len(contents) <= 200000 and hashlib.sha256(contents).hexdigest() == digest,
                "sourceintegritet fejlede for " + name)
        write_new(ROOT / name, contents)
        print("PINNED_SOURCE_VERIFIED=", name, flush=True)

    # Import only two main-branch modules, using all OTHER packages and their
    # pinned dependencies from the original 1248 release. The original venv,
    # installed package and systemd credentials stay unchanged.
    launch = '''from __future__ import annotations
import hashlib
import importlib.util
from pathlib import Path
import sys
import clientflow_runtime
BASE = Path("/run/clientflow-native-rdp-shadow-408")
HASHES = __HASHES__
def load(name, file):
    path = BASE / file
    if hashlib.sha256(path.read_bytes()).hexdigest() != HASHES[file]:
        raise SystemExit("STOP: kildefil er ændret")
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise SystemExit("STOP: kildefil kan ikke importeres")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
load("clientflow_runtime.native_rdp_forwarder", "native_rdp_forwarder.py")
agent = load("clientflow_runtime.remote_desktop_agent", "remote_desktop_agent.py")
if sys.argv[1:] == ["--check"]:
    assert callable(agent.main)
    assert hasattr(agent.RemoteDesktopAgent, "_start_native_rdp")
    print("SHADOW_AGENT_IMPORT=PASS")
else:
    raise SystemExit(agent.main())
'''.replace("__HASHES__", repr(SOURCE_FILES))
    write_new(LAUNCHER, launch.encode("utf-8"))

    rollback = f'''from pathlib import Path
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
    write_new(ROLLBACK, rollback.encode("utf-8"), mode=0o700)
    imported = call(str(PYTHON), "-B", str(LAUNCHER), "--check")
    require(imported.returncode == 0 and "SHADOW_AGENT_IMPORT=PASS" in imported.stdout,
            "den nye agent kan ikke importeres med 1248's installerede runtime")
    print("SHADOW_AGENT_COMPATIBILITY=PASS", flush=True)


def install() -> None:
    check_host()
    prepare()
    # Start the independent rollback timer BEFORE modifying systemd's live
    # agent command. On reboot both /run override and /run source vanish.
    planned = call(
        "systemd-run", "--unit=clientflow-native-rdp-shadow-rollback-408",
        "--on-active=25min", "/usr/bin/python3", str(ROLLBACK), timeout=30,
    )
    require(planned.returncode == 0 and
            call("systemctl", "is-active", ROLLBACK_TIMER).stdout.strip() == "active",
            "automatisk 1248-rollback blev ikke etableret")
    print("AUTO_ROLLBACK_AFTER_MINUTES=25", flush=True)
    DROPIN_DIR.mkdir(parents=True, exist_ok=True, mode=0o755)
    write_new(DROPIN, OVERRIDE.encode("utf-8"))
    try:
        require(call("systemctl", "daemon-reload").returncode == 0,
                "systemd kunne ikke opdatere override")
        require(call("systemctl", "restart", UNIT).returncode == 0,
                "midlertidig agent kunne ikke startes")
        time.sleep(3)
        require(call("systemctl", "is-active", UNIT).stdout.strip() == "active",
                "midlertidig agent forblev ikke aktiv")
        installed = call("systemctl", "show", UNIT, "-p", "ExecStart", "--value")
        require(installed.returncode == 0 and str(LAUNCHER) in installed.stdout,
                "systemd anvender ikke shadow-launcheren")
        print("NATIVE_RDP_SHADOW_AGENT=ACTIVE")
        print("RELEASE_1248_UNCHANGED=True")
        print("GNOME_RDP_NOT_STARTED_BY_THIS_SCRIPT=True")
        print("ROLLBACK_COMMAND=sudo python3 " + str(ROLLBACK))
    except Exception:
        # Restore even if the new agent crashes or the probe fails.
        if DROPIN.is_file() and DROPIN.read_text() == OVERRIDE:
            DROPIN.unlink()
            call("systemctl", "daemon-reload")
            call("systemctl", "restart", UNIT)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Viborg1 native RDP shadow agent")
    parser.add_argument("action", choices=["install", "status", "rollback"])
    args = parser.parse_args()
    try:
        check_host()
        if args.action == "install":
            install()
        elif args.action == "status":
            status()
        else:
            require(ROLLBACK.is_file(), "ingen rollback-kode er installeret")
            cp = call("/usr/bin/python3", str(ROLLBACK), timeout=45)
            require(cp.returncode == 0, "rollback blev afbrudt")
            print(cp.stdout.strip())
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print("SHADOW_AGENT=STOP", type(exc).__name__, str(exc), flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
