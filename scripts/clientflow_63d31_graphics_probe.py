#!/usr/bin/env python3
"""63D-31 guarded, local Xvfb FreeRDP graphic evidence; no desktop screenshots persisted."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

sys.dont_write_bytecode = True
PILOT_SHA = "78972f7c7173a4894abc22d4518b1fc4d3189c76e30dd463715af03ef069af69"
GUARD_SHA = "709a5d9b1eba3364dfd2ac21f4e24525b0dc3261236456a9127aac7cfd54c000"
PREFLIGHT_SHA = "40967aa92d658d8ecf1288ad22b5cde8f247835c2d2070f6d2e785b144f40cc4"
ROOT = Path(__file__).resolve().parent
PILOT = ROOT / "clientflow_63d30_local_rdp_pilot.py"
GUARD = ROOT / "clientflow_63d29_persistent_rdp_guard.py"
PREFLIGHT = ROOT / "clientflow_63d30_physical_preflight.py"
STAGED = Path("/var/lib/clientflow/rdp-pilot-bundle-63d30/clientflow_63d30_local_rdp_pilot.py")
STATE = Path("/var/lib/clientflow/rdp-pilot-63d30/state.json")
SECRET = Path("/run/clientflow-rdp-63d30/credentials")
GUARD_RESIDUALS = (
    Path("/etc/clientflow/rdp-guard-63d29"),
    Path("/etc/systemd/system/clientflow-63d29-rdp-guard.service"),
    Path("/etc/systemd/system/display-manager.service.d/clientflow-63d29-rdp-guard.conf"),
)
LOCK_RETRIES = 8  # strictly bounded: at most 3.5 seconds of retry delay


def check(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError("STOP: " + message)


def digest(path: Path) -> str:
    check(path.is_file() and not path.is_symlink(), "Missing or unsafe source")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> int:
    check(os.geteuid() == 0 and socket.gethostname() == "viborg1-NUC14MNK-B2",
          "Wrong physical client")
    identity = json.loads(Path("/etc/clientflow/identity.json").read_text())
    check(str(identity.get("CLIENT_ID", identity.get("client_id"))) == "3",
          "Wrong client identity")
    check(Path("/opt/clientflow/active").resolve().name == "clientflow-1.3.47-seq-1248",
          "Unexpected active release")
    for path, expected in ((PILOT, PILOT_SHA), (GUARD, GUARD_SHA),
                           (PREFLIGHT, PREFLIGHT_SHA)):
        check(digest(path) == expected, "Pinned source checksum mismatch")
    print("63D31_SOURCE_AND_IDENTITY=PASS", flush=True)
    return pwd.getpwnam("clientflow-kiosk").pw_uid


def idle_before_start_retry() -> bool:
    """Retry *only* an unstarted core command, never an uncertain RDP state."""
    if (not STAGED.is_file() or STAGED.is_symlink()
            or digest(STAGED) != PILOT_SHA):
        return False
    residuals = (STATE, SECRET, SECRET.parent, *GUARD_RESIDUALS)
    return not any(path.exists() or path.is_symlink() for path in residuals)


def cmd(path: Path, action: str, timeout: int = 120) -> bool:
    # A 10-second watchdog tick can briefly own the core's nonblocking
    # flock immediately after staging. Bounded reattempt is permissible
    # ONLY if no state, guard, or secret has been created; never retry a
    # partially started RDP operation or any non-lock failure.
    is_start = action == "start" and path == STAGED
    for attempt in range(LOCK_RETRIES if is_start else 1):
        r = subprocess.run([sys.executable, str(path), action], text=True,
                           capture_output=True, timeout=timeout, check=False)
        if r.returncode == 0:
            print(r.stdout, end="", flush=True)
            return True
        safe_lock_collision = (
            is_start
            and r.returncode == 2
            and "PILOT=STOP RuntimeError STOP: Anden pilotoperation kører allerede"
            in r.stdout.splitlines()
        )
        if not safe_lock_collision:
            print(r.stdout, end="", flush=True)
            return False
        if not idle_before_start_retry():
            print("63D31_LOCK_RETRY_BLOCKED_BY_STATE=True", flush=True)
            return False
        if attempt + 1 >= LOCK_RETRIES:
            print("63D31_LOCK_RETRY_EXHAUSTED=True", flush=True)
            return False
        print("63D31_WATCHDOG_LOCK_RETRY=", attempt + 1, flush=True)
        time.sleep(0.5)
    return False


def baseline() -> None:
    r = subprocess.run([sys.executable, str(PREFLIGHT)], text=True,
                       capture_output=True, timeout=90, check=False)
    check(r.returncode == 0 and "PHYSICAL_PREFLIGHT= PASS" in r.stdout,
          "63D-30 physical baseline not clean")
    print("63D31_PHYSICAL_PREFLIGHT=PASS", flush=True)


def readiness() -> None:
    verify()
    for program in ("Xvfb", "xvfb-run", "xauth"):
        check(shutil.which(program) is not None, "Missing Xvfb or Xauth")
    check(shutil.which("xfreerdp3") or shutil.which("xfreerdp"), "FreeRDP missing")
    C.CDLL("libX11.so.6")
    C.CDLL("libXtst.so.6")
    check(not STAGED.exists() and not STATE.exists() and not SECRET.exists(),
          "Existing unclean RDP pilot")
    baseline()
    print("63D31_READINESS=PASS", flush=True)
    print("HOST_MUTATED=False", flush=True)


class VirtualX:
    """Aggregate X11 pixel samples only, never saved or logged as images."""

    def __init__(self) -> None:
        self.x = C.CDLL("libX11.so.6")
        self.t = C.CDLL("libXtst.so.6")
        x = self.x
        x.XOpenDisplay.argtypes = [C.c_char_p]
        x.XOpenDisplay.restype = C.c_void_p
        x.XCloseDisplay.argtypes = [C.c_void_p]
        x.XDefaultRootWindow.argtypes = [C.c_void_p]
        x.XDefaultRootWindow.restype = C.c_ulong
        x.XGetImage.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_int,
                                 C.c_uint, C.c_uint, C.c_ulong, C.c_int]
        x.XGetImage.restype = C.c_void_p
        x.XGetPixel.argtypes = [C.c_void_p, C.c_int, C.c_int]
        x.XGetPixel.restype = C.c_ulong
        x.XDestroyImage.argtypes = [C.c_void_p]
        x.XQueryTree.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong),
                                 C.POINTER(C.c_ulong), C.POINTER(C.POINTER(C.c_ulong)),
                                 C.POINTER(C.c_uint)]
        x.XQueryTree.restype = C.c_int
        x.XFree.argtypes = [C.c_void_p]
        x.XFlush.argtypes = [C.c_void_p]
        x.XKeysymToKeycode.argtypes = [C.c_void_p, C.c_ulong]
        x.XKeysymToKeycode.restype = C.c_uint
        self.t.XTestFakeMotionEvent.argtypes = [
            C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong]
        self.t.XTestFakeMotionEvent.restype = C.c_int
        self.t.XTestFakeKeyEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
        self.t.XTestFakeKeyEvent.restype = C.c_int
        self.d = x.XOpenDisplay(None)
        check(bool(self.d), "Isolated Xvfb display unavailable")
        self.root = x.XDefaultRootWindow(self.d)

    def sample(self) -> tuple[int, ...]:
        picture = self.x.XGetImage(self.d, self.root, 0, 0, 1280, 720,
                                   C.c_ulong(-1).value, 2)
        check(bool(picture), "Xvfb aggregate pixel sampler failed")
        try:
            return tuple(self.x.XGetPixel(picture, x, y)
                         for y in range(8, 712, 24) for x in range(8, 1272, 24))
        finally:
            self.x.XDestroyImage(picture)

    def windows(self) -> int:
        root, parent = C.c_ulong(), C.c_ulong()
        children, count = C.POINTER(C.c_ulong)(), C.c_uint()
        check(self.x.XQueryTree(self.d, self.root, C.byref(root), C.byref(parent),
                                C.byref(children), C.byref(count)) != 0,
              "X11 window query failed")
        if children:
            self.x.XFree(children)
        return count.value

    def input(self) -> None:
        for x, y in ((440, 280), (520, 330)):
            check(self.t.XTestFakeMotionEvent(self.d, -1, x, y, 0) == 1,
                  "X11 pointer motion failed")
        shift = self.x.XKeysymToKeycode(self.d, 0xFFE1)
        check(bool(shift), "Shift key unavailable")
        for down in (1, 0):
            check(self.t.XTestFakeKeyEvent(self.d, shift, down, 0) == 1,
                  "X11 Shift tap failed")
        self.x.XFlush(self.d)

    def close(self) -> None:
        self.x.XCloseDisplay(self.d)


def graphic_child() -> None:
    uid = verify()
    check(os.environ.get("DISPLAY") and os.environ.get("XAUTHORITY"),
          "Must run in Xvfb child with Xauth")
    check(digest(STAGED) == PILOT_SHA, "Staged RDP core mismatch")
    from clientflow_63d30_local_rdp_pilot import (
        guard, deadline_expired, state_load, watchdog_verified,
    )
    state = state_load()
    check(state is not None and not deadline_expired(state), "Pilot inactive/expired")
    check(watchdog_verified() and guard.guard_verified(), "Firewall or timer absent")
    check(SECRET.is_file() and not SECRET.is_symlink(), "Root secret missing")
    st = SECRET.stat()
    check(st.st_uid == 0 and st.st_mode & 0o777 == 0o600,
          "Root credentials permissions mismatch")
    credentials = SECRET.read_text().splitlines()
    check(len(credentials) == 2 and re.fullmatch(r"cfpilot[0-9a-f]{8}", credentials[0])
          and len(credentials[1]) >= 40, "Malformed temporary credentials")
    cert = Path("/run/user") / str(uid) / "clientflow-rdp-pilot-63d30/tls.crt"
    check(cert.is_file() and not cert.is_symlink(), "Pilot certificate missing")
    result = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-outform", "DER"],
        capture_output=True, timeout=5, check=False,
    )
    check(result.returncode == 0 and bool(result.stdout), "TLS fingerprint missing")
    fingerprint = hashlib.sha256(result.stdout).hexdigest().upper()
    client = shutil.which("xfreerdp3") or shutil.which("xfreerdp")
    check(client is not None, "FreeRDP client missing")
    x = VirtualX()
    rd = None
    try:
        before = x.sample()
        args = [
            "/v:127.0.0.1:3389", "/u:" + credentials[0], "/p:" + credentials[1],
            "/cert:fingerprint:sha256:" + fingerprint,
            "/w:960", "/h:540", "/audio-mode:2", "-clipboard",
            "/log-level:ERROR",
        ]
        rd = subprocess.Popen(
            [client, "/args-from:stdin"], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=False,
        )
        check(rd.stdin is not None, "FreeRDP stdin missing")
        rd.stdin.write(("\n".join(args) + "\n").encode("ascii"))
        rd.stdin.flush()
        rd.stdin.close()
        start = time.monotonic()
        credible = False
        colors = changed = 0
        while time.monotonic() - start < 30 and rd.poll() is None:
            sample = x.sample()
            changed = sum(a != b for a, b in zip(before, sample))
            colors = len(set(sample))
            if x.windows() >= 1 and changed >= 120 and colors >= 8:
                credible = True
                break
            time.sleep(0.5)
        print("RDP_X11_WINDOW=", "PASS" if x.windows() >= 1 else "FAIL")
        print("RDP_X11_UNIQUE_COLORS=", colors)
        print("RDP_X11_CHANGED_SAMPLES=", changed)
        print("RDP_FIRST_GRAPHIC_MS=", round((time.monotonic() - start) * 1000))
        check(credible and rd.poll() is None, "No convincing graphical surface")
        x.input()
        print("RDP_LOCAL_POINTER_SHIFT_DISPATCH=PASS")
        print("RDP_REMOTE_INPUT_ACCEPTED=NOT_PROVEN")
        print("RDP_INPUT_TO_FRAME_MS=NOT_MEASURED")
        print("DISPLAY_FRONTEND_TRANSPORT=NOT_TESTED")
        print("SCREENSHOT_FILES_CREATED=False")
        print("63D31_GRAPHICS=PASS")
    finally:
        if rd is not None and rd.poll() is None:
            rd.terminate()
            try:
                rd.wait(timeout=5)
            except subprocess.TimeoutExpired:
                rd.kill()
                rd.wait(timeout=5)
        x.close()


ALLOWED_OUTPUT = (
    "63D31_SOURCE_AND_IDENTITY=", "RDP_X11_WINDOW=", "RDP_X11_UNIQUE_COLORS=",
    "RDP_X11_CHANGED_SAMPLES=", "RDP_FIRST_GRAPHIC_MS=",
    "RDP_LOCAL_POINTER_SHIFT_DISPATCH=", "RDP_REMOTE_INPUT_ACCEPTED=",
    "RDP_INPUT_TO_FRAME_MS=", "DISPLAY_FRONTEND_TRANSPORT=",
    "SCREENSHOT_FILES_CREATED=", "63D31_GRAPHICS=", "63D31=STOP",
)


def graphic_run() -> None:
    argv = [
        shutil.which("xvfb-run"), "-a", "-s",
        "-screen 0 1280x720x24 -nolisten tcp",
        sys.executable, str(Path(__file__).resolve()), "child",
    ]
    check(argv[0] is not None, "Xvfb-run missing")
    p = subprocess.Popen(
        argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        stdout, _ = p.communicate(timeout=65)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.communicate(timeout=8)
        raise RuntimeError("STOP: Xvfb graphic test timed out") from None
    for line in stdout.splitlines():
        if line.startswith(ALLOWED_OUTPUT):
            print(line, flush=True)
    check(p.returncode == 0 and "63D31_GRAPHICS=PASS" in stdout,
          "Xvfb FreeRDP graphical test failed")


def exercise() -> None:
    readiness()
    staged = False
    result = False
    try:
        check(cmd(PILOT, "stage"), "RDP timer staging failed")
        staged = True
        check(digest(STAGED) == PILOT_SHA, "Unexpected staged RDP script")
        check(cmd(STAGED, "start"), "RDP startup failed")
        graphic_run()
        result = True
    finally:
        # Only the reviewed core is authorized to disable RDP and remove guard.
        if STATE.is_file():
            check(cmd(STAGED, "stop"), "RDP rollback failed; keep guard and watchdog")
        elif staged and STAGED.exists():
            check(cmd(STAGED, "unstage"), "Safe watchdog unstaging failed")
        if staged:
            baseline()
    check(result, "Graphical trial was unsuccessful")
    print("63D31_GRAPHICS_AND_ROLLBACK=PASS", flush=True)


def main() -> int:
    try:
        check(len(sys.argv) == 2 and sys.argv[1] in {"readiness", "exercise", "child"},
              "Use readiness, exercise or child")
        {"readiness": readiness, "exercise": exercise, "child": graphic_child}[sys.argv[1]]()
        return 0
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        print("63D31=STOP", type(error).__name__, str(error), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
