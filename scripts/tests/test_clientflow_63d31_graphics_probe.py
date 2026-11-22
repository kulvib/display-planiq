"""63D31 purely simulated checks; never starts GNOME RDP or changes firewall."""
from pathlib import Path
import pytest
from scripts import clientflow_63d31_graphics_probe as probe


def test_source_pins_and_no_insecure_gui_channels():
    assert len(probe.PILOT_SHA) == len(probe.GUARD_SHA) == len(probe.PREFLIGHT_SHA) == 64
    text = Path(probe.__file__).read_text()
    assert "-nolisten tcp" in text
    assert '"/args-from:stdin"' in text
    assert '"/v:127.0.0.1:3389"' in text
    assert "XTestFakeButtonEvent" not in text
    assert "XTestFakeMotionEvent" in text
    assert "RDP_INPUT_TO_FRAME_MS=NOT_MEASURED" in text
    assert "SCREENSHOT_FILES_CREATED=False" in text
    assert "subprocess.DEVNULL" in text
    assert "start_new_session=False" in text  # GUI child remains in Xvfb group
    assert "rd.terminate()" in text


def test_readiness_is_read_only_and_fails_on_existing_pilot(monkeypatch, tmp_path):
    event = []
    monkeypatch.setattr(probe, "verify", lambda: event.append("verified"))
    monkeypatch.setattr(probe.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(probe.C, "CDLL", lambda lib: object())
    monkeypatch.setattr(probe, "baseline", lambda: event.append("baseline"))
    monkeypatch.setattr(probe, "STAGED", tmp_path / "staged")
    monkeypatch.setattr(probe, "STATE", tmp_path / "state")
    monkeypatch.setattr(probe, "SECRET", tmp_path / "secret")
    probe.readiness()
    assert event == ["verified", "baseline"]
    (tmp_path / "state").touch()
    with pytest.raises(RuntimeError, match="unclean"):
        probe.readiness()
    assert event == ["verified", "baseline", "verified"]


def test_graphics_rollback_is_always_delegated_to_pinned_core(monkeypatch, tmp_path):
    staged = tmp_path / "pilot.py"
    staged.write_text("pilot")
    marker = tmp_path / "state"
    events = []
    monkeypatch.setattr(probe, "STAGED", staged)
    monkeypatch.setattr(probe, "STATE", marker)
    monkeypatch.setattr(probe, "PILOT_SHA", probe.digest(staged))
    monkeypatch.setattr(probe, "readiness", lambda: events.append("ready"))
    monkeypatch.setattr(probe, "baseline", lambda: events.append("postflight"))
    def fake_cmd(path, action, timeout=120):
        events.append(action)
        if action == "start":
            marker.touch()
        if action == "stop":
            marker.unlink()
        return True
    monkeypatch.setattr(probe, "cmd", fake_cmd)
    monkeypatch.setattr(probe, "graphic_run", lambda: events.append("graphic"))
    probe.exercise()
    assert events == ["ready", "stage", "start", "graphic", "stop", "postflight"]


def test_graphics_failure_keeps_core_stop_and_postflight(monkeypatch, tmp_path):
    staged = tmp_path / "pilot.py"
    staged.write_text("pilot")
    marker = tmp_path / "state"
    events = []
    monkeypatch.setattr(probe, "STAGED", staged)
    monkeypatch.setattr(probe, "STATE", marker)
    monkeypatch.setattr(probe, "PILOT_SHA", probe.digest(staged))
    monkeypatch.setattr(probe, "readiness", lambda: None)
    monkeypatch.setattr(probe, "baseline", lambda: events.append("postflight"))
    def fake_cmd(path, action, timeout=120):
        events.append(action)
        if action == "start":
            marker.touch()
        if action == "stop":
            marker.unlink()
        return True
    monkeypatch.setattr(probe, "cmd", fake_cmd)
    monkeypatch.setattr(
        probe, "graphic_run",
        lambda: (_ for _ in ()).throw(RuntimeError("no screen")),
    )
    with pytest.raises(RuntimeError, match="no screen"):
        probe.exercise()
    assert events == ["stage", "start", "stop", "postflight"]


def test_graphics_rejects_unsafe_rollback(monkeypatch, tmp_path):
    staged = tmp_path / "pilot.py"
    staged.write_text("pilot")
    marker = tmp_path / "state"
    monkeypatch.setattr(probe, "STAGED", staged)
    monkeypatch.setattr(probe, "STATE", marker)
    monkeypatch.setattr(probe, "PILOT_SHA", probe.digest(staged))
    monkeypatch.setattr(probe, "readiness", lambda: None)
    def fake_cmd(path, action, timeout=120):
        if action == "start":
            marker.touch()
        return action != "stop"
    monkeypatch.setattr(probe, "cmd", fake_cmd)
    monkeypatch.setattr(probe, "graphic_run", lambda: None)
    with pytest.raises(RuntimeError, match="rollback failed"):
        probe.exercise()
    assert marker.exists()


def test_xvfb_status_redacts_untrusted_output(monkeypatch, capsys):
    class Process:
        returncode = 0
        def communicate(self, timeout):
            return (
                "63D31_GRAPHICS=PASS\n"
                "PASSWORD_DO_NOT_PRINT\n"
                "RDP_REMOTE_INPUT_ACCEPTED=NOT_PROVEN\n", ""
            )
    monkeypatch.setattr(probe.shutil, "which", lambda name: "/usr/bin/xvfb-run")
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *args, **kwargs: Process())
    probe.graphic_run()
    output = capsys.readouterr().out
    assert "63D31_GRAPHICS=PASS" in output
    assert "PASSWORD_DO_NOT_PRINT" not in output

def test_watchdog_lock_collision_retries_only_when_core_is_pristine(
    monkeypatch, tmp_path, capsys,
):
    from types import SimpleNamespace
    staged = tmp_path / "core.py"
    staged.write_text("pinned")
    monkeypatch.setattr(probe, "STAGED", staged)
    monkeypatch.setattr(probe, "PILOT_SHA", probe.digest(staged))
    monkeypatch.setattr(probe, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(probe, "SECRET", tmp_path / "secrets" / "credentials")
    monkeypatch.setattr(probe, "GUARD_RESIDUALS", (tmp_path / "guard",))
    monkeypatch.setattr(probe.time, "sleep", lambda amount: None)
    calls = []
    def fake_run(*args, **kwargs):
        calls.append(args[0][-1])
        if len(calls) <= 2:
            return SimpleNamespace(
                returncode=2,
                stdout="===== PILOT =====\n"
                       "PILOT=STOP RuntimeError STOP: Anden pilotoperation kører allerede\n",
            )
        return SimpleNamespace(returncode=0, stdout="RDP_FIREWALL_VERIFIED=True\n")
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.cmd(staged, "start")
    assert len(calls) == 3
    output = capsys.readouterr().out
    assert output.count("63D31_WATCHDOG_LOCK_RETRY=") == 2
    assert "RDP_FIREWALL_VERIFIED=True" in output


def test_watchdog_collision_never_retries_if_pilot_state_exists(monkeypatch, tmp_path):
    from types import SimpleNamespace
    staged = tmp_path / "core.py"
    staged.write_text("pinned")
    marker = tmp_path / "state.json"
    marker.write_text("{}")
    monkeypatch.setattr(probe, "STAGED", staged)
    monkeypatch.setattr(probe, "PILOT_SHA", probe.digest(staged))
    monkeypatch.setattr(probe, "STATE", marker)
    monkeypatch.setattr(probe, "SECRET", tmp_path / "secrets" / "credentials")
    monkeypatch.setattr(probe, "GUARD_RESIDUALS", (tmp_path / "guard",))
    calls = []
    def fake_run(*args, **kwargs):
        calls.append(True)
        return SimpleNamespace(
            returncode=2,
            stdout="PILOT=STOP RuntimeError STOP: Anden pilotoperation kører allerede\n",
        )
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert not probe.cmd(staged, "start")
    assert len(calls) == 1


def test_other_start_failures_never_trigger_lock_retry(monkeypatch, tmp_path):
    from types import SimpleNamespace
    staged = tmp_path / "core.py"
    staged.write_text("pinned")
    monkeypatch.setattr(probe, "STAGED", staged)
    monkeypatch.setattr(probe, "PILOT_SHA", probe.digest(staged))
    calls = []
    def fake_run(*args, **kwargs):
        calls.append(True)
        return SimpleNamespace(
            returncode=2,
            stdout="PILOT=STOP RuntimeError STOP: GNOME user operation failed\n",
        )
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert not probe.cmd(staged, "start")
    assert len(calls) == 1


def test_lock_collision_retry_is_bounded(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace
    staged = tmp_path / "core.py"
    staged.write_text("pinned")
    monkeypatch.setattr(probe, "STAGED", staged)
    monkeypatch.setattr(probe, "PILOT_SHA", probe.digest(staged))
    monkeypatch.setattr(probe, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(probe, "SECRET", tmp_path / "secrets" / "credentials")
    monkeypatch.setattr(probe, "GUARD_RESIDUALS", (tmp_path / "guard",))
    monkeypatch.setattr(probe.time, "sleep", lambda amount: None)
    calls = []
    def fake_run(*args, **kwargs):
        calls.append(True)
        return SimpleNamespace(
            returncode=2,
            stdout="PILOT=STOP RuntimeError STOP: Anden pilotoperation kører allerede\n",
        )
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert not probe.cmd(staged, "start")
    assert len(calls) == probe.LOCK_RETRIES == 8
    assert "63D31_LOCK_RETRY_EXHAUSTED=True" in capsys.readouterr().out
