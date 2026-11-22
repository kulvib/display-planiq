#!/usr/bin/env python3
"""63D-32 local guarded GNOME GTK input-to-FreeRDP-pixel latency acceptance.

Not a production transport: no service, network relay, screenshots or release changes.
A temporary full-screen GTK4 Wayland window receives RDP click events. A private
Xvfb FreeRDP client proves both GTK callback ACK and RDP-rendered pixel transitions.
All temporary desktop processes and RDP are rolled back in the 63D-30 guard.
"""
from __future__ import annotations

import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import select
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import time

sys.dont_write_bytecode = True
import clientflow_63d31_graphics_probe as graphics

GRAPHICS_SHA = "c23339d98cca2336b673a96be8617b4f229d5196ee882a5d511801494ddba66c"
ROOT = Path(__file__).resolve().parent
GRAPHICS_SOURCE = ROOT / "clientflow_63d31_graphics_probe.py"
COLORS = ((219, 39, 55), (31, 192, 108))  # saturated red -> green
SAMPLE_COUNT = 5
MIN_MATCHING_SAMPLES = 150
MAX_WINDOW_SECONDS = 80


def check(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError("STOP: " + message)


def verified() -> int:
    check(graphics.digest(GRAPHICS_SOURCE) == GRAPHICS_SHA, "63D-31 source mismatch")
    return graphics.verify()


def wayland_env(uid: int) -> list[str]:
    account = pwd.getpwnam("clientflow-kiosk")
    runtime = Path("/run/user") / str(uid)
    check((runtime / "bus").is_socket(), "GNOME user D-Bus missing")
    screens = [p.name for p in runtime.glob("wayland-*") if p.is_socket()]
    check(len(screens) == 1, "Wayland socket ambiguity")
    return [
        "PATH=/usr/bin:/bin", f"HOME={account.pw_dir}",
        "USER=clientflow-kiosk", "LOGNAME=clientflow-kiosk",
        "LANG=C.UTF-8", f"XDG_RUNTIME_DIR={runtime}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
        "XDG_SESSION_TYPE=wayland", "XDG_CURRENT_DESKTOP=GNOME",
        f"WAYLAND_DISPLAY={screens[0]}", "GDK_BACKEND=wayland",
    ]


def readiness() -> None:
    uid = verified()
    graphics.readiness()
    wayland_env(uid)
    r = subprocess.run(
        ["runuser", "-u", "clientflow-kiosk", "--", "env", "-i",
         *wayland_env(uid), "/usr/bin/python3", "-c",
         "import gi;gi.require_version('Gtk','4.0');"
         "from gi.repository import Gtk,Gdk;"
         "print('GTK_OK' if Gtk.init_check() and Gdk.Display.get_default() "
         "else 'GTK_MISSING')"],
        capture_output=True, text=True, timeout=18, check=False,
    )
    check(r.returncode == 0 and r.stdout.strip() == "GTK_OK",
          "GTK4 Wayland connection unavailable")
    print("63D32_GTK4_WAYLAND=PASS", flush=True)
    print("63D32_READINESS=PASS", flush=True)
    print("PERSISTENT_CHANGES=False", flush=True)


def active_guard() -> None:
    verified()
    from clientflow_63d30_local_rdp_pilot import (
        guard, state_load, deadline_expired, watchdog_verified,
    )
    state = state_load()
    check(state is not None and not deadline_expired(state), "RDP pilot inactive")
    check(watchdog_verified() and guard.guard_verified(),
          "Guard or root watchdog missing")


def gtk_window() -> None:
    """Execute only as the GNOME kiosk account, with its actual Wayland display."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, GLib, Gtk

    check(os.geteuid() != 0 and pwd.getpwuid(os.geteuid()).pw_name == "clientflow-kiosk",
          "Window must be a kiosk-user process")
    check(os.environ.get("GDK_BACKEND") == "wayland", "Window backend not Wayland")
    check(Gtk.init_check() and Gdk.Display.get_default() is not None, "GTK init failed")

    window = Gtk.Window(title="ClientFlow local input latency acceptance")
    window.set_decorated(False)
    area = Gtk.DrawingArea()
    area.set_content_width(960)
    area.set_content_height(540)
    state = {"n": 0, "ready": False}
    def paint(_area, cr, width, height):
        red, green, blue = COLORS[state["n"] % 2]
        cr.set_source_rgb(red / 255, green / 255, blue / 255)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        if not state["ready"]:
            state["ready"] = True
            print("63D32_WINDOW_READY=PASS", flush=True)
    area.set_draw_func(paint)
    gesture = Gtk.GestureClick.new()
    gesture.set_button(1)
    def clicked(_gesture, n_press, x, y):
        if n_press != 1:
            return
        state["n"] += 1
        stamp = time.monotonic_ns()
        area.queue_draw()
        print(f"CLICK_ACK_{state['n']}={stamp}", flush=True)
    gesture.connect("pressed", clicked)
    area.add_controller(gesture)
    window.set_child(area)
    window.fullscreen()
    window.present()
    loop = GLib.MainLoop()
    GLib.timeout_add_seconds(MAX_WINDOW_SECONDS, lambda: (loop.quit(), False)[1])
    loop.run()
    window.destroy()


def marker_count(values: tuple[int, ...], color: tuple[int, int, int]) -> int:
    # Xvfb depth 24 TrueColor; compare with a tolerance for RDP compression.
    return sum(
        all(abs(((pixel >> shift) & 255) - component) <= 32
            for shift, component in zip((16, 8, 0), color))
        for pixel in values
    )


def marker_point(values: tuple[int, ...], color: tuple[int, int, int]) -> tuple[int, int]:
    width = len(range(8, 1272, 24))
    points = [
        (8 + (index % width) * 24, 8 + (index // width) * 24)
        for index, pixel in enumerate(values)
        if marker_count((pixel,), color)
    ]
    check(len(points) >= MIN_MATCHING_SAMPLES, "Missing colored remote marker")
    # The median matching point is inside the GTK fullscreen marker,
    # not in the browser/kiosk UI or the FreeRDP window decoration.
    points.sort(key=lambda point: point[0])
    x = points[len(points) // 2][0]
    points.sort(key=lambda point: point[1])
    y = points[len(points) // 2][1]
    return x, y


class StatusPipe:
    def __init__(self, descriptor: int):
        self.fd = descriptor
        self.pending = b""
        self.ready = False
        self.acks: dict[int, int] = {}

    def pump(self, timeout: float = 0.01) -> None:
        available, _, _ = select.select([self.fd], [], [], timeout)
        if not available:
            return
        data = os.read(self.fd, 4096)
        check(data, "GTK test window terminated unexpectedly")
        self.pending += data
        check(len(self.pending) <= 8192, "Unbounded GTK status output")
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            if line == b"63D32_WINDOW_READY=PASS":
                self.ready = True
            elif re.fullmatch(rb"CLICK_ACK_[1-5]=[0-9]{8,25}", line):
                key, value = line.split(b"=")
                sequence = int(key.split(b"_")[-1])
                check(sequence not in self.acks, "Duplicate GTK click")
                self.acks[sequence] = int(value)
            else:
                raise RuntimeError("STOP: Unexpected GTK status line")


def terminate_group(proc: subprocess.Popen[object] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)


def x11_click(x: graphics.VirtualX, point: tuple[int, int]) -> int:
    # This can be dispatched only after a genuine remote GTK color marker
    # is seen inside FreeRDP. No typing/pasting or unverified UI interaction.
    x.t.XTestFakeButtonEvent.argtypes = [
        ct.c_void_p, ct.c_uint, ct.c_int, ct.c_ulong,
    ]
    x.t.XTestFakeButtonEvent.restype = ct.c_int
    check(x.t.XTestFakeMotionEvent(x.d, -1, *point, 0) == 1,
          "X11 pointer dispatch failed")
    x.x.XFlush(x.d)
    t0 = time.monotonic_ns()
    check(x.t.XTestFakeButtonEvent(x.d, 1, 1, 0) == 1,
          "X11 click-down dispatch failed")
    check(x.t.XTestFakeButtonEvent(x.d, 1, 0, 0) == 1,
          "X11 click-up dispatch failed")
    x.x.XFlush(x.d)
    return t0


def summarize(ms: list[float], name: str) -> None:
    check(len(ms) == SAMPLE_COUNT, "Missing latency measurements")
    print(name + "_P50_MS=", round(statistics.median(ms), 1), flush=True)
    print(name + "_MAX_MS=", round(max(ms), 1), flush=True)


def graphic_child() -> None:
    uid = verified()
    active_guard()
    check(os.environ.get("DISPLAY") and os.environ.get("XAUTHORITY"),
          "Isolated Xvfb environment missing")

    window = None
    rd = None
    x = None
    try:
        window = subprocess.Popen(
            ["runuser", "-u", "clientflow-kiosk", "--", "env", "-i",
             *wayland_env(uid), "/usr/bin/python3", str(Path(__file__).resolve()), "window"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        check(window.stdout is not None, "GTK status pipe unavailable")
        status = StatusPipe(window.stdout.fileno())
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not status.ready:
            check(window.poll() is None, "GTK window exited before ready")
            status.pump(0.2)
        check(status.ready, "GTK window did not render")

        check(graphics.SECRET.is_file() and not graphics.SECRET.is_symlink(),
              "Pilot credentials missing")
        st = graphics.SECRET.stat()
        check(st.st_uid == 0 and st.st_mode & 0o777 == 0o600, "Unsafe secret permissions")
        values = graphics.SECRET.read_text().splitlines()
        check(len(values) == 2 and re.fullmatch(r"cfpilot[0-9a-f]{8}", values[0])
              and len(values[1]) >= 40, "Invalid temporary secret format")
        cert = Path(f"/run/user/{uid}/clientflow-rdp-pilot-63d30/tls.crt")
        check(cert.is_file() and not cert.is_symlink(), "TLS certificate missing")
        der = subprocess.run(["openssl", "x509", "-in", str(cert), "-outform", "DER"],
                             capture_output=True, timeout=5, check=False)
        check(der.returncode == 0 and der.stdout, "Pinned certificate unavailable")
        fingerprint = hashlib.sha256(der.stdout).hexdigest().upper()
        client = shutil.which("xfreerdp3") or shutil.which("xfreerdp")
        check(client is not None, "FreeRDP missing")

        x = graphics.VirtualX()
        args = ["/v:127.0.0.1:3389", "/u:" + values[0], "/p:" + values[1],
                "/cert:fingerprint:sha256:" + fingerprint, "/w:960", "/h:540",
                "/audio-mode:2", "-clipboard", "/log-level:ERROR"]
        rd = subprocess.Popen(
            [client, "/args-from:stdin"], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        check(rd.stdin is not None, "FreeRDP stdin missing")
        rd.stdin.write(("\n".join(args) + "\n").encode("ascii"))
        rd.stdin.close()

        deadline = time.monotonic() + 22
        samples = None
        while time.monotonic() < deadline:
            check(rd.poll() is None, "Graphical RDP client exited")
            current = x.sample()
            if marker_count(current, COLORS[0]) >= MIN_MATCHING_SAMPLES:
                samples = current
                break
            time.sleep(0.15)
        check(samples is not None, "GNOME GTK initial marker not visible in FreeRDP")
        point = marker_point(samples, COLORS[0])
        print("63D32_GTK_MARKER_VISIBLE_IN_RDP=PASS", flush=True)

        to_gtk, to_pixels = [], []
        for n in range(1, SAMPLE_COUNT + 1):
            check(rd.poll() is None and window.poll() is None,
                  "RDP or GTK process exited unexpectedly")
            active_guard()
            clicked_at = x11_click(x, point)
            target = COLORS[n % 2]
            ack_at = None
            painted_at = None
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                check(rd.poll() is None and window.poll() is None,
                      "Graphical client stopped before round-trip")
                status.pump(0.01)
                ack_at = status.acks.get(n)
                if painted_at is None and marker_count(x.sample(), target) >= MIN_MATCHING_SAMPLES:
                    painted_at = time.monotonic_ns()
                if ack_at is not None and painted_at is not None:
                    break
                time.sleep(0.03)
            check(ack_at is not None and ack_at >= clicked_at,
                  "GTK did not confirm actual remote click")
            check(painted_at is not None and painted_at >= clicked_at,
                  "FreeRDP did not display the GTK color transition")
            to_gtk.append((ack_at - clicked_at) / 1e6)
            to_pixels.append((painted_at - clicked_at) / 1e6)
        print("63D32_REAL_GTK_REMOTE_CLICKS=", SAMPLE_COUNT, flush=True)
        print("63D32_VISIBLE_REMOTE_FRAMES=", SAMPLE_COUNT, flush=True)
        summarize(to_gtk, "63D32_INPUT_TO_GTK")
        summarize(to_pixels, "63D32_INPUT_TO_FREERDP_PIXEL")
        print("63D32_FRONTEND_RELAY=NOT_TESTED", flush=True)
        print("63D32_LIVESTREAM_HLS=NOT_TESTED", flush=True)
        print("63D32_SCREENSHOTS_SAVED=False", flush=True)
        print("63D32_REAL_INPUT_AND_VISIBLE_FRAMES=PASS", flush=True)
    finally:
        if rd is not None and rd.poll() is None:
            rd.terminate()
            try:
                rd.wait(timeout=4)
            except subprocess.TimeoutExpired:
                rd.kill()
                rd.wait(timeout=4)
        terminate_group(window)
        if x is not None:
            x.close()


PRINT_PREFIXES = (
    "63D32_GTK_MARKER_VISIBLE_IN_RDP=", "63D32_REAL_GTK_REMOTE_CLICKS=",
    "63D32_VISIBLE_REMOTE_FRAMES=", "63D32_INPUT_TO_GTK_",
    "63D32_INPUT_TO_FREERDP_PIXEL_", "63D32_FRONTEND_RELAY=",
    "63D32_LIVESTREAM_HLS=", "63D32_SCREENSHOTS_SAVED=",
    "63D32_REAL_INPUT_AND_VISIBLE_FRAMES=", "63D32=STOP",
)


def remote_graphic_test() -> None:
    check(shutil.which("xvfb-run") is not None, "Xvfb missing")
    argv = [
        shutil.which("xvfb-run"), "-a", "-s",
        "-screen 0 1280x720x24 -nolisten tcp",
        sys.executable, str(Path(__file__).resolve()), "child",
    ]
    proc = subprocess.Popen(
        argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        output, _ = proc.communicate(timeout=115)
    except subprocess.TimeoutExpired:
        terminate_group(proc)
        raise RuntimeError("STOP: Graphical input pilot timed out") from None
    # Output is a whitelist of numeric results and fixed statuses only.
    for line in output.splitlines():
        if line.startswith(PRINT_PREFIXES):
            print(line, flush=True)
    check(proc.returncode == 0 and "63D32_REAL_INPUT_AND_VISIBLE_FRAMES=PASS" in output,
          "Real remote input/paint pilot failed")


def exercise() -> None:
    readiness()
    staged = False
    passed = False
    try:
        check(graphics.cmd(graphics.PILOT, "stage"), "Watchdog staging failed")
        staged = True
        check(graphics.digest(graphics.STAGED) == graphics.PILOT_SHA,
              "Unexpected staged pilot source")
        check(graphics.cmd(graphics.STAGED, "start"), "Guarded GNOME RDP startup failed")
        remote_graphic_test()
        passed = True
    finally:
        # Safety ownership remains entirely inside the 63D-30 audited core.
        if graphics.STATE.is_file():
            check(graphics.cmd(graphics.STAGED, "stop", timeout=115),
                  "RDP shutdown unverified; firewall/watchdog must remain")
        elif staged and graphics.STAGED.exists():
            check(graphics.cmd(graphics.STAGED, "unstage", timeout=75),
                  "Safe watchdog unstaging failed")
        if staged:
            graphics.baseline()
    check(passed, "Remote input-to-pixels pilot failed")
    print("63D32_PHYSICAL_INPUT_AND_ROLLBACK=PASS", flush=True)


def main() -> int:
    try:
        check(len(sys.argv) == 2 and sys.argv[1] in
              ("readiness", "exercise", "child", "window"), "Unknown action")
        action = sys.argv[1]
        if action == "readiness":
            readiness()
        elif action == "exercise":
            exercise()
        elif action == "child":
            graphic_child()
        else:
            gtk_window()
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        # Never display raw subprocess stderr, raw pixel buffers or secrets.
        print("63D32=STOP", type(exc).__name__, str(exc), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
