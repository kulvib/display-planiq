"""63D-32 isolated simulation only: never starts real GTK, RDP or input injection."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import clientflow_63d32_input_to_frame as phase


def pixel(rgb):
    r, g, b = rgb
    return (r << 16) | (g << 8) | b


def test_marker_color_thresholds_and_false_positive_rejection():
    red = pixel(phase.COLORS[0])
    green = pixel(phase.COLORS[1])
    samples = (red,) * 200 + (green,) * 30 + (0,) * 200
    assert phase.marker_count(samples, phase.COLORS[0]) == 200
    assert phase.marker_count(samples, phase.COLORS[1]) == 30
    assert phase.marker_count((0,) * 1500, phase.COLORS[0]) == 0
    with pytest.raises(RuntimeError, match="Missing colored remote marker"):
        phase.marker_point((red,) * 100, phase.COLORS[0])


def test_marker_point_is_bounded_to_visible_color_samples():
    red = pixel(phase.COLORS[0])
    pts = (red,) * 260
    x, y = phase.marker_point(pts, phase.COLORS[0])
    assert 8 <= x < 1272
    assert 8 <= y < 712


def test_gtk_status_pipe_rejects_injected_text_and_duplicate_acks():
    reader, writer = os.pipe()
    try:
        status = phase.StatusPipe(reader)
        os.write(writer, b"63D32_WINDOW_READY=PASS\nCLICK_ACK_1=1234567890\n")
        status.pump(0.1)
        assert status.ready is True
        assert status.acks == {1: 1234567890}
        os.write(writer, b"CLICK_ACK_1=1234567891\n")
        with pytest.raises(RuntimeError, match="Duplicate"):
            status.pump(0.1)
    finally:
        os.close(reader)
        os.close(writer)


def test_gtk_status_pipe_never_accepts_unknown_log_content():
    reader, writer = os.pipe()
    try:
        status = phase.StatusPipe(reader)
        os.write(writer, b"PASSWORD=do_not_log\n")
        with pytest.raises(RuntimeError, match="Unexpected GTK status"):
            status.pump(0.1)
    finally:
        os.close(reader)
        os.close(writer)


def test_wayland_session_environment_uses_single_socket(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "bus").touch()
    # Path.is_socket() is verified by runtime, mocked here to avoid host sockets.
    monkeypatch.setattr(phase.Path, "is_socket", lambda path: path.name in {"bus", "wayland-0"})
    monkeypatch.setattr(phase.Path, "glob", lambda path, pat: [path / "wayland-0"])
    monkeypatch.setattr(phase.pwd, "getpwnam", lambda user: SimpleNamespace(pw_dir="/home/kiosk"))
    original = phase.Path
    monkeypatch.setattr(phase, "Path", lambda path: runtime
                        if str(path) == "/run/user" else original(path))
    values = phase.wayland_env(1001)
    assert "WAYLAND_DISPLAY=wayland-0" in values
    assert "GDK_BACKEND=wayland" in values
    assert all("password" not in v.lower() for v in values)


def test_readiness_checks_gtk_without_starting_any_service(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(phase, "verified", lambda: 1001)
    monkeypatch.setattr(phase.graphics, "readiness", lambda: calls.append("baseline"))
    monkeypatch.setattr(phase, "wayland_env", lambda uid: ["SAFE=1"])
    monkeypatch.setattr(
        phase.subprocess, "run",
        lambda args, **kwargs: SimpleNamespace(returncode=0, stdout="GTK_OK\n"),
    )
    phase.readiness()
    assert calls == ["baseline"]
    assert "63D32_READINESS=PASS" in capsys.readouterr().out


def test_exercise_calls_existing_guarded_core_and_rolls_back(monkeypatch, tmp_path):
    events = []
    script = tmp_path / "stage.py"
    script.write_text("ok")
    state = tmp_path / "state.json"
    monkeypatch.setattr(phase.graphics, "PILOT", script)
    monkeypatch.setattr(phase.graphics, "STAGED", script)
    monkeypatch.setattr(phase.graphics, "PILOT_SHA", phase.graphics.digest(script))
    monkeypatch.setattr(phase.graphics, "STATE", state)
    monkeypatch.setattr(phase, "readiness", lambda: events.append("readiness"))
    monkeypatch.setattr(phase.graphics, "baseline", lambda: events.append("postflight"))
    def fake_cmd(path, action, timeout=120):
        events.append(action)
        if action == "start":
            state.touch()
        if action == "stop":
            state.unlink()
        return True
    monkeypatch.setattr(phase.graphics, "cmd", fake_cmd)
    monkeypatch.setattr(phase, "remote_graphic_test", lambda: events.append("pixels"))
    phase.exercise()
    assert events == ["readiness", "stage", "start", "pixels", "stop", "postflight"]


def test_exercise_failure_still_calls_guarded_stop_before_postflight(
    monkeypatch, tmp_path,
):
    events = []
    script = tmp_path / "stage.py"
    script.write_text("ok")
    state = tmp_path / "state.json"
    monkeypatch.setattr(phase.graphics, "PILOT", script)
    monkeypatch.setattr(phase.graphics, "STAGED", script)
    monkeypatch.setattr(phase.graphics, "PILOT_SHA", phase.graphics.digest(script))
    monkeypatch.setattr(phase.graphics, "STATE", state)
    monkeypatch.setattr(phase, "readiness", lambda: None)
    monkeypatch.setattr(phase.graphics, "baseline", lambda: events.append("postflight"))
    def fake_cmd(path, action, timeout=120):
        events.append(action)
        if action == "start":
            state.touch()
        if action == "stop":
            state.unlink()
        return True
    monkeypatch.setattr(phase.graphics, "cmd", fake_cmd)
    monkeypatch.setattr(
        phase, "remote_graphic_test",
        lambda: (_ for _ in ()).throw(RuntimeError("No remote frame")),
    )
    with pytest.raises(RuntimeError, match="No remote frame"):
        phase.exercise()
    assert events == ["stage", "start", "stop", "postflight"]


def test_shutdown_failure_never_claims_safe_cleanup(monkeypatch, tmp_path):
    script = tmp_path / "stage.py"
    script.write_text("ok")
    state = tmp_path / "state.json"
    monkeypatch.setattr(phase.graphics, "PILOT", script)
    monkeypatch.setattr(phase.graphics, "STAGED", script)
    monkeypatch.setattr(phase.graphics, "PILOT_SHA", phase.graphics.digest(script))
    monkeypatch.setattr(phase.graphics, "STATE", state)
    monkeypatch.setattr(phase, "readiness", lambda: None)
    def fake_cmd(path, action, timeout=120):
        if action == "start":
            state.touch()
        return action != "stop"
    monkeypatch.setattr(phase.graphics, "cmd", fake_cmd)
    monkeypatch.setattr(phase, "remote_graphic_test", lambda: None)
    with pytest.raises(RuntimeError, match="shutdown unverified"):
        phase.exercise()
    assert state.exists()


def test_no_password_in_argv_and_no_persistent_screenshot():
    text = Path(phase.__file__).read_text()
    assert '"/args-from:stdin"' in text
    assert '"/v:127.0.0.1:3389"' in text
    assert "SCREENSHOTS_SAVED=False" in text
    assert "XTestFakeButtonEvent" in text
    assert "GTK" in text
    assert "gtk_worker_script()" in text
    assert '"/usr/bin/python3", "-u", "-"' in text
    assert "proc.stdin.write(gtk_worker_script())" in text
    assert "guard.guard_verified()" in text
    assert "time.monotonic_ns()" in text
    assert "marker_count" in text


def test_summary_requires_full_sample_count(capsys):
    with pytest.raises(RuntimeError, match="Missing latency"):
        phase.summarize([12.0], "TEST")
    phase.summarize([10, 20, 30, 40, 50], "TEST")
    output = capsys.readouterr().out
    assert "TEST_P50_MS= 30" in output
    assert "TEST_MAX_MS= 50" in output

def test_gtk_worker_script_contains_only_unprivileged_window_code():
    code = phase.gtk_worker_script().decode("utf-8")
    assert "def gtk_window()" in code
    assert "Gtk.GestureClick.new()" in code
    assert "gtk_window()" in code
    assert "from gi.repository import Gdk, GLib, Gtk" in code
    assert "Gtk.ApplicationWindow(" in code
    assert "app.run([])" in code
    assert "GLib.MainLoop()" not in code
    assert "63D32_GTK_STAGE=LOOP_RUNNING" in code
    assert "from clientflow_63d30_local_rdp_pilot" not in code
    assert "RDP_LOCAL_PORT" not in code
    assert "SECRET.read_text" not in code
    assert "CLIENT_ID" not in code

def test_gtk_pipe_accepts_only_fixed_progress_stages():
    reader, writer = os.pipe()
    try:
        status = phase.StatusPipe(reader)
        os.write(writer, (
            b"63D32_GTK_STAGE=INITIALIZED\n"
            b"63D32_GTK_STAGE=APPLICATION_RUN\n"
            b"63D32_GTK_STAGE=APPLICATION_ACTIVATED\n"
            b"63D32_GTK_STAGE=WINDOW_CREATED\n"
            b"63D32_GTK_STAGE=LOOP_RUNNING\n"
            b"63D32_GTK_STAGE=PRESENT_CALLED\n"
            b"63D32_GTK_STAGE=MAPPED\n"
            b"63D32_GTK_STAGE=FRAME_DRAWN\n"
            b"63D32_WINDOW_READY=PASS\n"
        ))
        status.pump(0.1)
        assert status.ready and status.stage == "FRAME_DRAWN"
        os.write(writer, b"63D32_GTK_STAGE=PASSWORD_LEAK\n")
        with pytest.raises(RuntimeError, match="Unexpected GTK status"):
            status.pump(0.1)
    finally:
        os.close(reader)
        os.close(writer)


def test_gtk_smoke_without_rdp_always_cleans(monkeypatch):
    events = []
    monkeypatch.setattr(phase, "readiness", lambda: events.append("readiness"))
    monkeypatch.setattr(phase, "verified", lambda: 1001)
    monkeypatch.setattr(phase, "gtk_launch", lambda uid: (object(), object()))
    monkeypatch.setattr(phase, "gtk_wait_draw",
                        lambda *args, **kwargs: events.append("draw"))
    monkeypatch.setattr(phase, "terminate_group",
                        lambda proc: events.append("terminated"))
    monkeypatch.setattr(phase.graphics, "baseline",
                        lambda: events.append("postflight"))
    monkeypatch.setattr(phase.graphics, "cmd",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("No RDP operations allowed")))
    phase.gtk_smoke()
    assert events == ["readiness", "draw", "terminated", "postflight"]


def test_gtk_smoke_failure_still_terminates_and_checks_postflight(monkeypatch):
    events = []
    monkeypatch.setattr(phase, "readiness", lambda: None)
    monkeypatch.setattr(phase, "verified", lambda: 1001)
    monkeypatch.setattr(phase, "gtk_launch", lambda uid: (object(), object()))
    monkeypatch.setattr(phase, "gtk_wait_draw",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            RuntimeError("No paint")))
    monkeypatch.setattr(phase, "terminate_group",
                        lambda proc: events.append("terminated"))
    monkeypatch.setattr(phase.graphics, "baseline",
                        lambda: events.append("postflight"))
    with pytest.raises(RuntimeError, match="No paint"):
        phase.gtk_smoke()
    assert events == ["terminated", "postflight"]


def test_gtk_wait_draw_reports_fixed_stage_not_raw_error(monkeypatch, capsys):
    class Worker:
        def poll(self):
            return None
    class Status:
        ready = False
        stage = "PRESENT_CALLED"
        def pump(self, timeout):
            pass
    iterator = iter((0, 16))
    monkeypatch.setattr(phase.time, "monotonic", lambda: next(iterator))
    with pytest.raises(RuntimeError, match="did not render"):
        phase.gtk_wait_draw(Worker(), Status(), seconds=15)
    assert "63D32_GTK_LAST_STAGE= PRESENT_CALLED" in capsys.readouterr().out
