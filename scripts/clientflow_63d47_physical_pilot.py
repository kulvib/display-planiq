#!/usr/bin/env python3
"""63D-47: bounded, fail-closed physical GNOME RDP and candidate agent pilot.

This is a ROOT-ONLY OPERATOR script, not part of the ClientFlow release.
It never changes an installed release, physical monitor resolution, backend,
frontend, FreeRDP WASM, RDP packet contents, nftables policy or auth secrets.

Only Viborg1, Client ID 3, ClientFlow 1248 and the SHA-pinned e58a1f2
candidate are accepted. The independent 63D-29/30 firewall + six-minute
GNOME watchdog is installed BEFORE the agent override. A second ten-minute
transient systemd timer restores the original agent even if the browser dies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import socket
import stat
import subprocess
import sys
import urllib.request

sys.dont_write_bytecode = True
# Ubuntu stores runuser under /usr/sbin, which a web terminal may not expose.
os.environ["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"

HOST = "viborg1-NUC14MNK-B2"
CLIENT_ID = 3
ACTIVE_RELEASE = "clientflow-1.3.47-seq-1248"
COMMIT = "e58a1f2a2fe52df79df5c0dc50649077d042ccc1"
OP = Path("/run/clientflow-63d47-operator")
BUNDLE = Path("/run/clientflow-native-rdp-63d47")
BASE_SHADOW = Path("/run/clientflow-native-rdp-63d42")
GNOME_RUNNER = Path("/var/lib/clientflow/rdp-pilot-bundle-63d30/clientflow_63d30_local_rdp_pilot.py")
GNOME_STATE = Path("/var/lib/clientflow/rdp-pilot-63d30/state.json")
BROWSER_GRANT = Path("/run/clientflow/native-rdp-approved")
UNIT = "clientflow-remote-desktop-agent.service"
TIMER = "clientflow-63d47-agent-rollback.timer"
DROPIN = Path("/run/systemd/system") / (UNIT + ".d") / "63d47-native-rdp.conf"
PYTHON = "/opt/clientflow/active/runtime/bin/python"
EXPECTED_DROPIN = "[Service]\nExecStart=\nExecStart=" + PYTHON + " -I -B " + str(BUNDLE / "entrypoint.py") + "\n"
EXPECTED = {
    "scripts/clientflow_63d29_persistent_rdp_guard.py": "709a5d9b1eba3364dfd2ac21f4e24525b0dc3261236456a9127aac7cfd54c000",
    "scripts/clientflow_63d30_local_rdp_pilot.py": "78972f7c7173a4894abc22d4518b1fc4d3189c76e30dd463715af03ef069af69",
    "scripts/clientflow_native_rdp_browser_pilot.py": "02c63fc10deb3c0329c5309bdcb19a0edf8fa694c1c0045257cd79c304849e7f",
    "scripts/clientflow_63d30_physical_preflight.py": "40967aa92d658d8ecf1288ad22b5cde8f247835c2d2070f6d2e785b144f40cc4",
    "client/runtime/clientflow_runtime/remote_desktop_agent.py": "a99dc405cd286ec19f70c9e0701a399aa677e2accfefeadda4010f7c39fd4f95",
    "client/runtime/clientflow_runtime/native_rdp_forwarder.py": "52bfba4fc883854e47c67d75f7a19e70757a663b20b7ca1903eec43c947e4ee3",
}
OLD_FORWARDER = "1038a07dd95abcc8cbe99e07a2603a319d031d1c7764f68436469c9b2d030c91"

ENTRY = '''#!/usr/bin/env python3
"""Pinned, read-only 63D-47 shadow agent. No credentials are logged."""
import hashlib
import os
from pathlib import Path
import socket
import sys
sys.dont_write_bytecode = True
ROOT = Path("/run/clientflow-native-rdp-63d47")
SOURCE = {
    "remote_desktop_agent.py": "a99dc405cd286ec19f70c9e0701a399aa677e2accfefeadda4010f7c39fd4f95",
    "native_rdp_forwarder.py": "52bfba4fc883854e47c67d75f7a19e70757a663b20b7ca1903eec43c947e4ee3",
}
if socket.gethostname() != "viborg1-NUC14MNK-B2":
    raise SystemExit("STOP: foreign host")
if Path("/opt/clientflow/active").resolve().name != "clientflow-1.3.47-seq-1248":
    raise SystemExit("STOP: unexpected release")
for name, expected in SOURCE.items():
    path = ROOT / name
    metadata = path.lstat()
    if not path.is_file() or path.is_symlink() or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise SystemExit("STOP: unsafe shadow file")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit("STOP: source mismatch")
import clientflow_runtime
clientflow_runtime.__path__ = [str(ROOT), *clientflow_runtime.__path__]
from clientflow_runtime import native_rdp_forwarder, remote_desktop_agent
for module in (native_rdp_forwarder, remote_desktop_agent):
    if Path(module.__file__).resolve().parent != ROOT:
        raise SystemExit("STOP: incorrect imported module")
if sys.argv[1:] == ["--check"]:
    print("63D47_SHADOW_IMPORT=PASS")
    print("RDP_COMPRESSION_DISABLED=" + str("compression" in native_rdp_forwarder.forward_native_rdp.__code__.co_names or "compression=None" in (ROOT / "native_rdp_forwarder.py").read_text()))
    raise SystemExit(0)
if sys.argv[1:]:
    raise SystemExit("STOP: bad arguments")
raise SystemExit(remote_desktop_agent.main())
'''


def out(message: str) -> None:
    print(message, flush=True)


def check_target() -> None:
    if os.geteuid() != 0 or socket.gethostname() != HOST:
        raise RuntimeError("TARGET_INVALID_HOST_OR_USER")
    data = json.loads(Path("/etc/clientflow/identity.json").read_text())
    if str(data.get("CLIENT_ID", data.get("client_id"))) != str(CLIENT_ID):
        raise RuntimeError("TARGET_INVALID_CLIENT_ID")
    if Path("/opt/clientflow/active").resolve().name != ACTIVE_RELEASE:
        raise RuntimeError("TARGET_INVALID_RELEASE")


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(65536):
            h.update(block)
    return h.hexdigest()


def check_file(path: Path, expected: str) -> None:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise RuntimeError("UNSAFE_FILE_" + path.name)
    if hash_file(path) != expected:
        raise RuntimeError("SOURCE_SHA_MISMATCH_" + path.name)


def check_directory(path: Path, *, private: bool = False) -> None:
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise RuntimeError("UNSAFE_DIRECTORY_" + path.name)
    if private and st.st_mode & 0o077:
        raise RuntimeError("DIRECTORY_NOT_PRIVATE_" + path.name)


def run(label: str, argv: list[str], *, timeout: int = 80) -> str:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(label + "_" + type(exc).__name__) from None
    if p.returncode:
        # GNOME control stdout and stderr can be credential-bearing. Never echo.
        raise RuntimeError(label + "_EXIT_" + str(p.returncode))
    return p.stdout


def active(name: str) -> bool:
    p = subprocess.run(["/usr/bin/systemctl", "is-active", name], capture_output=True, text=True, timeout=8)
    return p.stdout.strip() == "active"


def get_source_path(relpath: str) -> Path:
    return OP / Path(relpath).name


def install_new_file(path: Path, contents: bytes, *, mode: int) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(contents)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def ensure_download(relpath: str) -> Path:
    expected = EXPECTED[relpath]
    path = get_source_path(relpath)
    if not path.exists() and not path.is_symlink():
        url = "https://raw.githubusercontent.com/kulvib/display-planiq/" + COMMIT + "/" + relpath
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ClientFlow-63D47-Pinned-Pilot"}), timeout=20) as response:
                data = response.read(128 * 1024 + 1)
        except (OSError, TimeoutError):
            raise RuntimeError("SOURCE_DOWNLOAD_FAILED_" + path.name) from None
        if len(data) > 128 * 1024 or hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError("SOURCE_DOWNLOAD_SHA_MISMATCH_" + path.name)
        install_new_file(path, data, mode=0o600)
    check_file(path, expected)
    return path


def verify_preexisting_clean_state() -> None:
    if not active(UNIT):
        raise RuntimeError("ORIGINAL_AGENT_NOT_ACTIVE")
    if BUNDLE.exists() or BUNDLE.is_symlink() or DROPIN.exists() or DROPIN.is_symlink():
        raise RuntimeError("PREVIOUS_63D47_STAGING_EXISTS")
    if GNOME_STATE.exists() or GNOME_STATE.is_symlink() or BROWSER_GRANT.exists() or BROWSER_GRANT.is_symlink():
        raise RuntimeError("PREVIOUS_GNOME_RDP_OR_GRANT_EXISTS")
    if GNOME_RUNNER.exists() or GNOME_RUNNER.is_symlink() or active(TIMER):
        raise RuntimeError("PREVIOUS_TIMER_OR_GNOME_STAGE_EXISTS")
    value = run("ORIGINAL_AGENT_EXEC", ["/usr/bin/systemctl", "show", "--property=ExecStart", "--value", UNIT], timeout=12)
    if "/run/clientflow-native-rdp" in value or "clientflow-remote-desktop-agent" not in value:
        raise RuntimeError("ORIGINAL_AGENT_EXEC_MISMATCH")
    # A prior test left this old shadow source in memory. DO NOT overwrite it.
    old = BASE_SHADOW / "native_rdp_forwarder.py"
    if old.exists() or old.is_symlink():
        check_file(old, OLD_FORWARDER)
    for prefix in (Path("/run/systemd/system"), Path("/etc/systemd/system")):
        unit_dir = prefix / (UNIT + ".d")
        if unit_dir.is_symlink():
            raise RuntimeError("UNEXPECTED_AGENT_UNIT_DIR_SYMLINK")
        if unit_dir.is_dir() and any(unit_dir.glob("*native-rdp*.conf")):
            raise RuntimeError("OTHER_NATIVE_RDP_OVERRIDE_PRESENT")


def stage_source() -> None:
    OP.mkdir(mode=0o700, exist_ok=True)
    check_directory(OP, private=True)
    # The original operator file is checked before other file writes.
    # This script is itself pinned by the invoking bootstrap.
    for relpath in EXPECTED:
        ensure_download(relpath)
    BUNDLE.mkdir(mode=0o755, exist_ok=False)
    BUNDLE.chmod(0o755)  # sudo umask may be 077; service user must read this directory
    check_directory(BUNDLE)
    for name, relpath in (
        ("remote_desktop_agent.py", "client/runtime/clientflow_runtime/remote_desktop_agent.py"),
        ("native_rdp_forwarder.py", "client/runtime/clientflow_runtime/native_rdp_forwarder.py"),
    ):
        path = get_source_path(relpath)
        install_new_file(BUNDLE / name, path.read_bytes(), mode=0o644)
        check_file(BUNDLE / name, EXPECTED[relpath])
    install_new_file(BUNDLE / "entrypoint.py", ENTRY.encode(), mode=0o644)
    # Compile in memory: no pyc files in the immutable root shadow directory.
    compile(ENTRY, str(BUNDLE / "entrypoint.py"), "exec")
    # Python -I -B must use the exact venv that systemd will use.
    user = pwd.getpwnam("clientflow-remote-desktop-agent")
    try:
        p = subprocess.run([PYTHON, "-I", "-B", str(BUNDLE / "entrypoint.py"), "--check"],
                           user=user.pw_uid, group=user.pw_gid, extra_groups=[],
                           capture_output=True, text=True, timeout=40)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("SHADOW_IMPORT_" + type(exc).__name__) from None
    if p.returncode or "63D47_SHADOW_IMPORT=PASS" not in p.stdout or "RDP_COMPRESSION_DISABLED=True" not in p.stdout:
        raise RuntimeError("SHADOW_IMPORT_FAILED")
    out("NEW_FORWARDER_SHA256=PASS")
    out("SHADOW_AGENT_IMPORT=PASS")


def gnome(action: str, *, staged: bool = False) -> str:
    path = GNOME_RUNNER if staged else get_source_path("scripts/clientflow_63d30_local_rdp_pilot.py")
    return run("GNOME_" + action.upper(), ["/usr/bin/python3", str(path), action], timeout=105)


def browser(action: str) -> str:
    return run("BROWSER_" + action.upper(), ["/usr/bin/python3", str(get_source_path("scripts/clientflow_native_rdp_browser_pilot.py")), action], timeout=40)


def rollback_agent(*, cancel_timer: bool = False) -> None:
    """Only revoke the EXACT 63D-47 override; never edit release artifacts."""
    check_target()
    if DROPIN.is_symlink():
        raise RuntimeError("UNKNOWN_AGENT_OVERRIDE_SYMLINK")
    if DROPIN.exists():
        check_directory(DROPIN.parent)
        if DROPIN.read_text(encoding="ascii") != EXPECTED_DROPIN:
            raise RuntimeError("UNKNOWN_AGENT_OVERRIDE_CONTENT")
        DROPIN.unlink()
        run("ROLLBACK_DAEMON_RELOAD", ["/usr/bin/systemctl", "daemon-reload"], timeout=25)
        run("ROLLBACK_RESTART_ORIGINAL_AGENT", ["/usr/bin/systemctl", "restart", UNIT], timeout=40)
    if not active(UNIT):
        raise RuntimeError("ROLLBACK_ORIGINAL_AGENT_INACTIVE")
    original = run("ROLLBACK_VERIFY_EXEC", ["/usr/bin/systemctl", "show", "--property=ExecStart", "--value", UNIT], timeout=12)
    if "/run/clientflow-native-rdp" in original or "clientflow-remote-desktop-agent" not in original:
        raise RuntimeError("ROLLBACK_EXEC_UNEXPECTED")
    if cancel_timer and active(TIMER):
        run("ROLLBACK_CANCEL_TIMER", ["/usr/bin/systemctl", "stop", TIMER], timeout=18)
    out("AGENT_1248_RESTORED=PASS")


def stop_physical_pilot() -> None:
    check_target()
    if BROWSER_GRANT.exists() or BROWSER_GRANT.is_symlink():
        browser("disarm")
        out("BROWSER_GRANT_DISARMED=PASS")
    if GNOME_STATE.exists() or GNOME_STATE.is_symlink():
        if not GNOME_RUNNER.is_file() or GNOME_RUNNER.is_symlink():
            raise RuntimeError("GNOME_RUNNER_UNAVAILABLE_KEEP_FIREWALL")
        gnome("stop", staged=True)
        out("GNOME_RDP_CLEANUP=PASS")
    elif GNOME_RUNNER.is_file() and not GNOME_RUNNER.is_symlink():
        gnome("unstage", staged=True)
        out("GNOME_WATCHDOG_UNSTAGED=PASS")


def main_start() -> None:
    check_target()
    verify_preexisting_clean_state()
    out("63D47_PRECHECK=PASS")
    # Download and verify every source from the DEPLOYED, immutable commit.
    stage_source()
    clean = run("PHYSICAL_PREFLIGHT", ["/usr/bin/python3", str(get_source_path("scripts/clientflow_63d30_physical_preflight.py"))], timeout=95)
    if "PHYSICAL_PREFLIGHT= PASS" not in clean and "PHYSICAL_PREFLIGHT=PASS" not in clean:
        raise RuntimeError("PHYSICAL_PREFLIGHT_NO_PASS")
    out("63D30_PHYSICAL_PREFLIGHT=PASS")
    try:
        # The six-minute independent firewall watchdog is staged BEFORE GNOME.
        gnome("stage")
        check_file(GNOME_RUNNER, EXPECTED["scripts/clientflow_63d30_local_rdp_pilot.py"])
        check_file(GNOME_RUNNER.parent / "clientflow_63d29_persistent_rdp_guard.py", EXPECTED["scripts/clientflow_63d29_persistent_rdp_guard.py"])
        out("ROOT_GNOME_WATCHDOG=PASS")
        gnome("start", staged=True)
        if not GNOME_STATE.is_file() or GNOME_STATE.is_symlink():
            raise RuntimeError("GNOME_STATE_MISSING")
        out("GNOME_MIRROR_PRIMARY=STARTED")
        grant = browser("arm")
        if "NATIVE_RDP_BROWSER_GRANT=ARMED" not in grant:
            raise RuntimeError("BROWSER_GRANT_NOT_ARMED")
        for line in grant.splitlines():
            if line.startswith("GNOME_TLS_SHA256="):
                out(line)
        out("BROWSER_GRANT=PASS")
        # Rollback must be armed BEFORE changing systemd's active agent.
        run("ROLLBACK_TIMER_ARM", ["/usr/bin/systemd-run", "--unit=clientflow-63d47-agent-rollback",
                                   "--on-active=10m", "/usr/bin/python3", str(OP / "clientflow_63d47_physical_pilot.py"), "rollback-agent"], timeout=25)
        if not active(TIMER):
            raise RuntimeError("AGENT_ROLLBACK_TIMER_NOT_ARMED")
        DROPIN.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        check_directory(DROPIN.parent)
        install_new_file(DROPIN, EXPECTED_DROPIN.encode("ascii"), mode=0o644)
        run("AGENT_DAEMON_RELOAD", ["/usr/bin/systemctl", "daemon-reload"], timeout=25)
        run("AGENT_RESTART_CANDIDATE", ["/usr/bin/systemctl", "restart", UNIT], timeout=45)
        if not active(UNIT):
            raise RuntimeError("CANDIDATE_AGENT_INACTIVE")
        agent_exec = run("CANDIDATE_EXEC", ["/usr/bin/systemctl", "show", "--property=ExecStart", "--value", UNIT], timeout=12)
        if str(BUNDLE / "entrypoint.py") not in agent_exec or not active(TIMER):
            raise RuntimeError("CANDIDATE_AGENT_OR_TIMER_UNVERIFIED")
        stats = browser("status")
        for key in ("FIREWALL_VERIFIED= True", "WATCHDOG_VERIFIED= True", "BROWSER_GRANT_PRESENT= True", "BROWSER_GRANT_UNEXPIRED= True"):
            if key not in stats:
                raise RuntimeError("SAFETY_GATE_" + key.partition("=")[0])
        out("PILOT_READY_63D47=PASS")
        out("CLIENT_ID=3 RELEASE=1248 PHYSICAL_MONITOR=2560x1080@60Hz")
        out("BROWSER=https://display.planiq.dk")
        out("LOGIN_FILE=/run/clientflow-rdp-63d30/credentials (root-only; do not paste)")
        out("RDP_WINDOW_MAX=6_MINUTES AGENT_ROLLBACK_MAX=10_MINUTES")
        out("MANUAL_STOP=sudo /usr/bin/python3 /run/clientflow-63d47-operator/clientflow_63d47_physical_pilot.py stop")
    except Exception as exc:
        out("PILOT_START_FAILED=" + type(exc).__name__ + "_" + str(exc)[:110])
        # Revocation order: stop RDP first; keep firewall intact if it fails.
        try:
            stop_physical_pilot()
            out("GNOME_ROLLBACK=PASS")
        except Exception as error:
            out("GNOME_ROLLBACK=UNCERTAIN_" + type(error).__name__)
        try:
            rollback_agent(cancel_timer=True)
        except Exception as error:
            out("AGENT_ROLLBACK=UNCERTAIN_" + type(error).__name__ + "_KEEP_TIMER")
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "rollback-agent", "status"), nargs="?", default="start")
    args = parser.parse_args()
    out("===== CLIENTFLOW 63D-47 · VIBORG1 PHYSICAL PILOT =====")
    try:
        if args.action == "start":
            main_start()
        elif args.action == "stop":
            stop_physical_pilot()
            rollback_agent(cancel_timer=True)
            out("63D47_MANUAL_STOP=PASS")
        elif args.action == "rollback-agent":
            rollback_agent(cancel_timer=False)
        else:
            check_target()
            out("AGENT_ACTIVE=" + str(active(UNIT)))
            out("AGENT_ROLLBACK_TIMER_ACTIVE=" + str(active(TIMER)))
            out("GNOME_STATE_PRESENT=" + str(GNOME_STATE.is_file()))
            out("BROWSER_GRANT_PRESENT=" + str(BROWSER_GRANT.is_file()))
        return 0
    except Exception as exc:
        out("63D47_STOP=" + type(exc).__name__ + "_" + str(exc)[:140])
        return 2


if __name__ == "__main__":
    raise SystemExit(main())