#!/usr/bin/env python3
"""63D-48 one-shot physical source A/B native FreeRDP reference, Viborg1 only.

Fail closed. The official 63D-29/30 root watchdog and nftables guard protect
an already-approved six-minute desktop sharing session. This script never
modifies the installed ClientFlow agent, Render, kiosk display, release files,
public network configuration or human authentication.
The experiment runs a native FreeRDP X11 client in a private Xvfb, then
guarantees STOP attempts before reporting a complete result.
"""
from __future__ import annotations

import fcntl
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
os.environ["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"

HOST = "viborg1-NUC14MNK-B2"
RELEASE = "clientflow-1.3.47-seq-1248"
OP = Path("/run/clientflow-63d48-reference")
LOCK = Path("/run/clientflow-63d48-reference.lock")
STAGED = Path("/var/lib/clientflow/rdp-pilot-bundle-63d30/clientflow_63d30_local_rdp_pilot.py")
STAGED_GUARD = STAGED.parent / "clientflow_63d29_persistent_rdp_guard.py"
STATE = Path("/var/lib/clientflow/rdp-pilot-63d30/state.json")
COMMIT_GNOME = "e58a1f2a2fe52df79df5c0dc50649077d042ccc1"
COMMIT_NATIVE = "845a20af310bb1cbc9b5ebe7169a2f02e0d7af6e"
PATHS = {
    "scripts/clientflow_63d29_persistent_rdp_guard.py":
        (COMMIT_GNOME, "709a5d9b1eba3364dfd2ac21f4e24525b0dc3261236456a9127aac7cfd54c000"),
    "scripts/clientflow_63d30_local_rdp_pilot.py":
        (COMMIT_GNOME, "78972f7c7173a4894abc22d4518b1fc4d3189c76e30dd463715af03ef069af69"),
    "scripts/clientflow_63d30_physical_preflight.py":
        (COMMIT_GNOME, "40967aa92d658d8ecf1288ad22b5cde8f247835c2d2070f6d2e785b144f40cc4"),
    "scripts/clientflow_63d48_native_reference.py":
        (COMMIT_NATIVE, "afb3b875a28b7f5d9c476bf5e6609da58b77bd336558e292ba89ff3a1f204ca3"),
}
TIMERS = ("clientflow-63d47-agent-rollback.timer", "clientflow-63d42-agent-rollback.timer")
AGENT = "clientflow-remote-desktop-agent.service"


def emit(key: str, value: str) -> None:
    print(f"{key}={value}", flush=True)


def command(label: str, args: list[str], timeout: int = 80) -> str:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(label + "_" + type(error).__name__) from None
    # Do not log arbitrary output; GNOME scripts can touch one-time secrets.
    if p.returncode:
        raise RuntimeError(label + "_EXIT_" + str(p.returncode))
    return p.stdout


def root_file(path: Path, expected_sha: str) -> None:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise RuntimeError("UNSAFE_SOURCE_" + path.name)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
        raise RuntimeError("SOURCE_SHA_MISMATCH_" + path.name)


def target() -> pwd.struct_passwd:
    if os.geteuid() != 0 or socket.gethostname() != HOST:
        raise RuntimeError("WRONG_HOST_OR_PRIVILEGES")
    identity = Path("/etc/clientflow/identity.json")
    if identity.is_symlink():
        raise RuntimeError("IDENTITY_SYMLINK")
    doc = json.loads(identity.read_text())
    if str(doc.get("CLIENT_ID", doc.get("client_id"))) != "3":
        raise RuntimeError("NOT_VIBORG1_ID3")
    if Path("/opt/clientflow/active").resolve().name != RELEASE:
        raise RuntimeError("RELEASE_NOT_1248")
    for timer in TIMERS:
        status = subprocess.run(
            ["/usr/bin/systemctl", "is-active", timer],
            capture_output=True, text=True, timeout=8, check=False
        )
        if status.stdout.strip() == "active":
            raise RuntimeError("OLD_AGENT_ROLLBACK_ACTIVE")
    if command("AGENT_ACTIVE", ["/usr/bin/systemctl", "is-active", AGENT], timeout=8).strip() != "active":
        raise RuntimeError("ORIGINAL_AGENT_NOT_ACTIVE")
    original = command(
        "ORIGINAL_AGENT_EXEC",
        ["/usr/bin/systemctl", "show", "--property=ExecStart", "--value", AGENT],
        timeout=10
    )
    if "/run/clientflow-native-rdp" in original or "clientflow-remote-desktop-agent" not in original:
        raise RuntimeError("UNEXPECTED_AGENT_OVERRIDE")
    if STATE.exists() or STATE.is_symlink():
        raise RuntimeError("GNOME_PILOT_ALREADY_ACTIVE")
    return pwd.getpwnam("clientflow-kiosk")


def monitor_readonly(user: pwd.struct_passwd) -> None:
    bus = Path(f"/run/user/{user.pw_uid}/bus")
    if not bus.is_socket():
        raise RuntimeError("KIOSK_GNOME_SESSION_BUS_ABSENT")
    script = r'''
from gi.repository import Gio
c=Gio.bus_get_sync(Gio.BusType.SESSION,None)
r=c.call_sync("org.gnome.Mutter.DisplayConfig","/org/gnome/Mutter/DisplayConfig",
"org.gnome.Mutter.DisplayConfig","GetCurrentState",None,None,Gio.DBusCallFlags.NONE,10000,None)
_,mon,logic,_=r.unpack()
p=[v for v in logic if v[4] is True]
if len(p)!=1 or len(p[0][5])!=1: raise RuntimeError("NOT_ONE_PRIMARY")
connector=p[0][5][0][0]
screens=[v for v in mon if v[0][0]==connector]
if len(screens)!=1: raise RuntimeError("INVALID_CONNECTOR")
def v(x): return x.unpack() if hasattr(x,"unpack") else x
m=[x for x in screens[0][1] if v(x[6].get("is-current",False)) is True]
if len(m)!=1: raise RuntimeError("INVALID_DISPLAY_MODE")
w,h=int(m[0][1]),int(m[0][2])
hz=float(m[0][3])
scale=float(p[0][2])
if (w,h)!=(2560,1080) or not (59.0<=hz<=61.0) or scale!=1.0:
    raise RuntimeError("PHYSICAL_DISPLAY_CHANGED")
print("PHYSICAL_2560X1080_60HZ_SCALE1=PASS")
'''
    env = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8",
        "HOME": user.pw_dir, "XDG_RUNTIME_DIR": f"/run/user/{user.pw_uid}",
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={bus}",
    }
    try:
        p = subprocess.run(
            ["/usr/bin/python3", "-c", script], user=user.pw_uid,
            group=user.pw_gid, extra_groups=[], env=env,
            capture_output=True, text=True, timeout=18, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("GNOME_MONITOR_CHECK_UNAVAILABLE") from None
    if p.returncode or "PHYSICAL_2560X1080_60HZ_SCALE1=PASS" not in p.stdout:
        raise RuntimeError("GNOME_MONITOR_MODE_NOT_VERIFIED")
    emit("MONITOR_READONLY", "PASS_2560x1080_60HZ_SCALE_1")


def get(relpath: str) -> Path:
    commit, expected = PATHS[relpath]
    path = OP / Path(relpath).name
    if not path.exists() and not path.is_symlink():
        url = "https://raw.githubusercontent.com/kulvib/display-planiq/" + commit + "/" + relpath
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "PlanIQ-63D48-Pinned-Native-Reference"}),
                timeout=20
            ) as response:
                raw = response.read(128 * 1024 + 1)
        except (OSError, TimeoutError):
            raise RuntimeError("SOURCE_DOWNLOAD_FAILED_" + path.name) from None
        if len(raw) > 128 * 1024 or hashlib.sha256(raw).hexdigest() != expected:
            raise RuntimeError("PINNED_DOWNLOAD_FAILED_" + path.name)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
    root_file(path, expected)
    return path


def staged_runner_trusted() -> bool:
    if STAGED.exists() or STAGED.is_symlink():
        root_file(STAGED, PATHS["scripts/clientflow_63d30_local_rdp_pilot.py"][1])
        root_file(STAGED_GUARD, PATHS["scripts/clientflow_63d29_persistent_rdp_guard.py"][1])
        return True
    if STAGED_GUARD.exists() or STAGED_GUARD.is_symlink():
        raise RuntimeError("INCOMPLETE_EXISTING_GNOME_STAGE")
    return False


def gnome(action: str, staged: bool) -> str:
    runner = STAGED if staged else get("scripts/clientflow_63d30_local_rdp_pilot.py")
    return command("GNOME_" + action.upper(), ["/usr/bin/python3", str(runner), action], timeout=110)


def native_reference() -> str:
    script = get("scripts/clientflow_63d48_native_reference.py")
    result = command("NATIVE_REFERENCE", ["/usr/bin/python3", str(script), "native", "14"], timeout=105)
    for line in result.splitlines():
        if line.startswith(("NATIVE_RDP_AUTHENTICATION=", "NATIVE_RDP_SESSION=",
                            "NATIVE_REFERENCE_SECONDS=", "LOCAL_X11_FRAME_CHANGE=",
                            "RDP_DESKTOP_REQUEST=", "NATIVE_INPUT_TO_PIXEL_LATENCY=",
                            "NATIVE_REFERENCE_TOTAL_SECONDS=", "NO_SCREEN_PIXELS_SAVED=")):
            print(line, flush=True)
    if ("NATIVE_RDP_AUTHENTICATION=PASS" not in result or
            "NATIVE_RDP_SESSION=ALIVE_THROUGH_WINDOW" not in result):
        raise RuntimeError("NATIVE_REFERENCE_INCOMPLETE")
    return result


def main() -> int:
    emit("63D48_NATIVE_ONE_SHOT", "START")
    new_stage = False
    started = False
    cleanup_errors = []
    try:
        lockfd = os.open(str(LOCK), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(lockfd, "w") as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            user = target()
            monitor_readonly(user)
            if OP.is_symlink():
                raise RuntimeError("OPERATOR_SYMLINK")
            OP.mkdir(mode=0o700, exist_ok=True)
            op_stat = OP.lstat()
            if op_stat.st_uid != os.geteuid() or op_stat.st_mode & 0o077:
                raise RuntimeError("OPERATOR_DIRECTORY_UNSAFE")
            emit("VIBORG1_ID3_RELEASE1248", "PASS")
            for relpath in PATHS:
                get(relpath)
            native_preflight = command(
                "NATIVE_CAPABILITY",
                ["/usr/bin/python3", str(get("scripts/clientflow_63d48_native_reference.py")), "preflight"],
                timeout=20,
            )
            for required in ("HOST_AND_ID_3_RELEASE_1248=PASS", "FREERDP_REFERENCE=",
                             "X11_ISOLATION=", "X11_SERVER=", "XAUTH_PROGRAM=",
                             "RDP_TLS_PIN_TOOL="):
                if required not in native_preflight:
                    raise RuntimeError("NATIVE_PREFLIGHT_INCOMPLETE")
            if "=NOT_INSTALLED" in native_preflight:
                raise RuntimeError("NATIVE_REFERENCE_DEPENDENCY_MISSING")
            emit("NATIVE_FREERDP_XVFB_XAUTH_CAPABILITY", "PASS")
            preflight = command(
                "PHYSICAL_PREFLIGHT",
                ["/usr/bin/python3", str(get("scripts/clientflow_63d30_physical_preflight.py"))],
                timeout=100,
            )
            if "PHYSICAL_PREFLIGHT=PASS" not in preflight and "PHYSICAL_PREFLIGHT= PASS" not in preflight:
                raise RuntimeError("PHYSICAL_PREFLIGHT_NOT_PASSED")
            emit("GNOME_63D30_PREFLIGHT", "PASS")
            if not staged_runner_trusted():
                new_stage = True  # partial stage still needs explicit cleanup
                gnome("stage", staged=False)
            if not staged_runner_trusted():
                raise RuntimeError("GNOME_STAGE_SOURCE_MISMATCH")
            emit("ROOT_FIREWALL_WATCHDOG_STAGE", "PASS")
            # stage/start/stop are implemented by the audited source-pinned
            # 63D-30 operator, never reimplemented or bypassed here.
            started = True  # even partial start must enter cleanup
            gnome("start", staged=True)
            emit("GNOME_MIRROR_PRIMARY_PILOT", "ACTIVE")
            native_reference()
            emit("NATIVE_REFERENCE_COMPARISON", "CAPTURED")
    except Exception as exc:
        emit("63D48_FAILURE", type(exc).__name__ + "_" + str(exc)[:85])
        returncode = 2
    else:
        returncode = 0
    finally:
        # Safe path is RDP STOP before root watchdog unstage. A failure must
        # keep the existing firewall or watchdog in place, never remove both.
        if started and (STATE.exists() or STATE.is_symlink()):
            try:
                gnome("stop", staged=True)
                emit("GNOME_RDP_STOP", "PASS")
            except Exception as exc:
                cleanup_errors.append("RDP_STOP_" + type(exc).__name__)
        if new_stage and not (STATE.exists() or STATE.is_symlink()):
            try:
                gnome("unstage", staged=True)
                emit("GNOME_ROOT_WATCHDOG_UNSTAGED", "PASS")
            except Exception as exc:
                cleanup_errors.append("UNSTAGE_" + type(exc).__name__)
        if cleanup_errors:
            for code in cleanup_errors:
                emit("CLEANUP_STOP", code)
            returncode = 2
        elif started:
            emit("GNOME_PILOT_CLEANUP", "PASS")
        emit("CLIENTFLOW_RELEASE_CHANGED", "FALSE")
        emit("RENDER_CHANGED", "FALSE")
    emit("63D48_NATIVE_ONE_SHOT", "PASS" if returncode == 0 else "STOP")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
