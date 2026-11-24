#!/usr/bin/env python3
"""ClientFlow 63D-48: guarded native FreeRDP comparison against physical GNOME.

This operator does NOT create a GNOME RDP server, alter the monitor, write
credentials, publish ports, change any ClientFlow service or modify Render.
Run 'preflight' anytime; run 'native' ONLY within the existing independent
six-minute GNOME 63D-30 root-guarded session.

Native reference: xfreerdp3 -> 127.0.0.1:3389 via a private Xvfb.
RDP credentials are passed through /args-from:stdin, not argv or environment.
Only timing and local X11-change indicators are shown; no desktop pixels.
A running X11 window alone is NOT proof of responsive GNOME input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time

HOST = "viborg1-NUC14MNK-B2"
RELEASE = "clientflow-1.3.47-seq-1248"
STATE = Path("/var/lib/clientflow/rdp-pilot-63d30/state.json")
GNOME_RUNNER = Path(
    "/var/lib/clientflow/rdp-pilot-bundle-63d30/clientflow_63d30_local_rdp_pilot.py"
)
LOGIN = Path("/run/clientflow-rdp-63d30/credentials")
DISPLAY_MODE = "2560x1080"
MAX_NATIVE_SECONDS = 25
ENV_KEYS = ("PATH", "HOME", "XDG_RUNTIME_DIR", "LANG")


class PreflightError(RuntimeError):
    pass


def announce(name: str, value: str | int) -> None:
    print(f"{name}={value}", flush=True)


def checked_target() -> pwd.struct_passwd:
    if os.geteuid() != 0 or socket.gethostname() != HOST:
        raise PreflightError("WRONG_HOST_OR_PRIVILEGE")
    identity = Path("/etc/clientflow/identity.json")
    if identity.is_symlink():
        raise PreflightError("UNSAFE_CLIENT_IDENTITY")
    data = json.loads(identity.read_text(encoding="utf-8"))
    if str(data.get("CLIENT_ID", data.get("client_id"))) != "3":
        raise PreflightError("WRONG_CLIENT_ID")
    if Path("/opt/clientflow/active").resolve().name != RELEASE:
        raise PreflightError("WRONG_RELEASE")
    return pwd.getpwnam("clientflow-kiosk")


def require_executable(names: tuple[str, ...]) -> str:
    for name in names:
        found = shutil.which(name, path="/usr/sbin:/usr/bin:/sbin:/bin")
        if found:
            return found
    raise PreflightError("MISSING_PROGRAM_" + names[0].replace("-", "_"))


def validate_guard() -> float:
    # Both the kernel-level nftables guard and independent root watchdog are
    # verified by the approved staged GNOME pilot code, not reimplemented here.
    if GNOME_RUNNER.is_symlink() or not GNOME_RUNNER.is_file():
        raise PreflightError("NO_PINNED_GNOME_RUNNER")
    result = subprocess.run(
        ["/usr/bin/python3", str(GNOME_RUNNER), "status"],
        capture_output=True, text=True, timeout=15, check=False,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if result.returncode:
        raise PreflightError("GNOME_STATUS_FAILED")
    expected = (
        "PILOT_STATE_EXISTS= True",
        "GUARD_KERNEL_VERIFIED= True",
        "ROOT_WATCHDOG_VERIFIED= True",
        "GNOME_RDP_SETTING= true",
        "RDP_LISTENERS_3389_3398= [3389]",
        "PILOT_EXPIRED= False",
    )
    for item in expected:
        if item not in result.stdout:
            raise PreflightError("GNOME_GUARD_OR_SESSION_NOT_READY")

    if STATE.is_symlink() or not STATE.is_file():
        raise PreflightError("NO_GNOME_STATE")
    st = STATE.stat()
    if st.st_uid != 0 or st.st_mode & 0o022 or st.st_size > 8192:
        raise PreflightError("UNSAFE_GNOME_STATE")
    data = json.loads(STATE.read_text(encoding="utf-8"))
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if data.get("boot_id") != boot_id:
        raise PreflightError("WRONG_BOOT")
    wall = float(data.get("deadline_wall", 0)) - time.time()
    mono = float(data.get("deadline_mono", 0)) - time.monotonic()
    remaining = min(wall, mono)
    if not (20 < remaining <= 360):
        raise PreflightError("GNOME_RDP_EXPIRING_OR_EXPIRED")
    return remaining


def private_login(user: pwd.struct_passwd) -> tuple[str, str, str]:
    if LOGIN.is_symlink() or not LOGIN.is_file():
        raise PreflightError("NO_GNOME_TEST_CREDENTIALS")
    st = LOGIN.stat()
    if st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o600 or st.st_size > 512:
        raise PreflightError("UNSAFE_GNOME_TEST_CREDENTIALS")
    lines = LOGIN.read_text(encoding="utf-8").splitlines()
    if len(lines) != 2:
        raise PreflightError("INVALID_GNOME_TEST_CREDENTIALS")
    username, password = lines
    if not re.fullmatch(r"cfpilot[0-9a-f]{8}", username) or len(password) < 40:
        raise PreflightError("INVALID_GNOME_TEST_CREDENTIALS")
    cert = Path(f"/run/user/{user.pw_uid}/clientflow-rdp-pilot-63d30/tls.crt")
    if cert.is_symlink() or not cert.is_file():
        raise PreflightError("NO_GNOME_TEST_CERT")
    result = subprocess.run(
        ["/usr/bin/openssl", "x509", "-in", str(cert), "-outform", "DER"],
        capture_output=True, timeout=8, check=False,
    )
    if result.returncode or not result.stdout or len(result.stdout) > 32768:
        raise PreflightError("CANNOT_PIN_RDP_CERT")
    fingerprint = hashlib.sha256(result.stdout).hexdigest().upper()
    return username, password, fingerprint


def xwd_sample() -> str | None:
    xwd = shutil.which("xwd", path="/usr/bin:/bin")
    if not xwd:
        return None
    try:
        result = subprocess.run(
            [xwd, "-root", "-silent"],
            capture_output=True, timeout=6, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode or not (1024 < len(result.stdout) <= 24 * 1024 * 1024):
        return None
    # Raw desktop bitmap is never persisted, transmitted or logged.
    return hashlib.sha256(result.stdout).hexdigest()


def isolated_worker(seconds: int) -> int:
    """Runs only inside xvfb-run as the unprivileged kiosk user."""
    if os.geteuid() != pwd.getpwnam("clientflow-kiosk").pw_uid:
        raise PreflightError("UNPRIVILEGED_WORKER_REQUIRED")
    if not re.fullmatch(r":[0-9]+(?:\.[0-9]+)?", os.environ.get("DISPLAY", "")):
        raise PreflightError("X11_REFERENCE_DISPLAY_REQUIRED")
    if seconds < 5 or seconds > MAX_NATIVE_SECONDS:
        raise PreflightError("BAD_DURATION")
    raw = sys.stdin.read(2048)
    params = raw.splitlines()
    if len(params) != 3:
        raise PreflightError("WORKER_ARGUMENT_FORMAT")
    username, password, fingerprint = params
    if not re.fullmatch(r"cfpilot[0-9a-f]{8}", username):
        raise PreflightError("WORKER_USER_INVALID")
    if len(password) < 40 or not re.fullmatch(r"[A-F0-9]{64}", fingerprint):
        raise PreflightError("WORKER_SECRET_FORMAT")

    client = require_executable(("xfreerdp3", "xfreerdp"))
    args = [
        "/v:127.0.0.1:3389", "/u:" + username, "/p:" + password,
        "/cert:fingerprint:sha256:" + fingerprint,
        "/size:" + DISPLAY_MODE, "/log-level:ERROR",
    ]
    # X11 frame changes can include window decoration. Never claim that an
    # X11 screenshot proves GNOME's actual negotiated source resolution.
    baseline = xwd_sample()
    start = time.monotonic()
    proc = subprocess.Popen(
        [client, "/args-from:stdin"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
    )
    ever_changed = False
    elapsed = 0.0
    try:
        assert proc.stdin is not None
        proc.stdin.write(("\n".join(args) + "\n").encode("utf-8"))
        proc.stdin.close()
        username = password = fingerprint = ""
        args.clear()
        last_sample = 0.0
        while (elapsed := time.monotonic() - start) < seconds:
            if proc.poll() is not None:
                announce("NATIVE_RDP_SESSION", "EARLY_EXIT")
                announce("NATIVE_REFERENCE_SECONDS", int(elapsed))
                return 2
            if baseline and elapsed >= 3 and elapsed - last_sample >= 2:
                sample = xwd_sample()
                ever_changed |= sample is not None and sample != baseline
                last_sample = elapsed
            time.sleep(0.25)
        announce("NATIVE_RDP_SESSION", "ALIVE_THROUGH_WINDOW")
        announce("NATIVE_REFERENCE_SECONDS", int(elapsed))
        announce("LOCAL_X11_FRAME_CHANGE", "YES" if ever_changed else "UNKNOWN")
        announce("RDP_DESKTOP_REQUEST", DISPLAY_MODE)
        announce("NATIVE_INPUT_TO_PIXEL_LATENCY", "NOT_MEASURED")
        return 0
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=4)


def preflight() -> int:
    checked_target()
    announce("HOST_AND_ID_3_RELEASE_1248", "PASS")
    for label, names in (
        ("FREERDP_REFERENCE", ("xfreerdp3", "xfreerdp")),
        ("X11_ISOLATION", ("xvfb-run",)),
        ("RDP_TLS_PIN_TOOL", ("openssl",)),
        ("X11_SCREEN_SAMPLER", ("xwd",)),
    ):
        try:
            result = require_executable(names)
            announce(label, Path(result).name)
        except PreflightError:
            announce(label, "NOT_INSTALLED")
    announce("GNOME_REAL_PRIMARY", "2560x1080@60Hz_READONLY_MEASURED")
    announce("EXTERNAL_RDP_PORTS", "UNCHANGED")
    return 0


def native(seconds: int) -> int:
    user = checked_target()
    if seconds < 5 or seconds > MAX_NATIVE_SECONDS:
        raise PreflightError("BAD_DURATION")
    remaining = validate_guard()
    if remaining < seconds + 20:
        raise PreflightError("NOT_ENOUGH_GUARDED_TIME")
    xvfb = require_executable(("xvfb-run",))
    require_executable(("xfreerdp3", "xfreerdp"))
    require_executable(("openssl",))
    username, password, fingerprint = private_login(user)

    # Wrapper runs as an unprivileged kiosk user. No password in argv, env,
    # disks or stdout; Xvfb has no TCP listener and a per-run Xauthority file.
    argv = [
        xvfb, "-a", "-s", "-screen 0 2560x1080x24 -nolisten tcp",
        "/usr/bin/python3", "-I", "-B",
        str(Path(__file__).resolve()), "isolated-worker", str(seconds),
    ]
    env = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": user.pw_dir,
        "XDG_RUNTIME_DIR": f"/run/user/{user.pw_uid}",
        "LANG": "C.UTF-8",
    }
    started = time.monotonic()
    run = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True,
        user=user.pw_uid, group=user.pw_gid, extra_groups=[],
        env=env, start_new_session=True, close_fds=True,
    )
    try:
        output, _ = run.communicate(
            input=username + "\n" + password + "\n" + fingerprint + "\n",
            timeout=seconds + 28,
        )
        # Only allow-list emitted measurement tokens. No raw worker output.
        allowed = ("NATIVE_RDP_SESSION=", "NATIVE_REFERENCE_SECONDS=",
                   "LOCAL_X11_FRAME_CHANGE=", "RDP_DESKTOP_REQUEST=",
                   "NATIVE_INPUT_TO_PIXEL_LATENCY=")
        for line in output.splitlines():
            if line.startswith(allowed):
                print(line, flush=True)
        if run.returncode:
            raise PreflightError("NATIVE_REFERENCE_PROCESS_FAILED")
    except subprocess.TimeoutExpired:
        os.killpg(run.pid, signal.SIGKILL)
        run.communicate()
        raise PreflightError("NATIVE_REFERENCE_TIMED_OUT") from None
    finally:
        username = password = fingerprint = ""
    announce("NATIVE_REFERENCE_TOTAL_SECONDS", int(time.monotonic() - started))
    announce("NO_REMOTE_DESKTOP_SETTINGS_CHANGED", "TRUE")
    announce("NO_SCREEN_PIXELS_SAVED", "TRUE")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "native", "isolated-worker"))
    parser.add_argument("seconds", nargs="?", type=int, default=14)
    args = parser.parse_args()
    try:
        if args.action == "preflight":
            return preflight()
        if args.action == "native":
            return native(args.seconds)
        return isolated_worker(args.seconds)
    except (PreflightError, OSError, ValueError, KeyError,
            subprocess.TimeoutExpired) as exc:
        code = str(exc) if isinstance(exc, PreflightError) else type(exc).__name__
        announce("63D48_STOP", code[:100])
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
