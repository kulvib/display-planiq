"""63D-48 one-shot: GNOME RDP must always stop before removing its watchdog."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "clientflow_63d48_native_oneshot.py"


def module():
    spec = importlib.util.spec_from_file_location("cf_63d48_oneshot", SCRIPT)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
    return obj


def simulated(tmp_path, monkeypatch, *, fail_native=False, fail_start=False):
    m = module()
    monkeypatch.setattr(m, "OP", tmp_path / "operator")
    monkeypatch.setattr(m, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(m, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(m, "target", lambda: SimpleNamespace(pw_uid=1000))
    monkeypatch.setattr(m, "monitor_readonly", lambda _u: None)
    monkeypatch.setattr(m, "get", lambda name: tmp_path / Path(name).name)
    progress = {"staged": False}
    events = []

    def command(label, _args, timeout=80):
        if label == "NATIVE_CAPABILITY":
            return (
                "HOST_AND_ID_3_RELEASE_1248=PASS\n"
                "FREERDP_REFERENCE=xfreerdp3\n"
                "X11_ISOLATION=xvfb-run\nX11_SERVER=Xvfb\n"
                "XAUTH_PROGRAM=xauth\nRDP_TLS_PIN_TOOL=openssl\n"
            )
        if label == "PHYSICAL_PREFLIGHT":
            return "PHYSICAL_PREFLIGHT=PASS\n"
        pytest.fail("unexpected external command: " + label)

    def staged_runner_trusted():
        return progress["staged"]

    def gnome(action, staged):
        events.append(action)
        if action == "stage":
            assert not staged
            progress["staged"] = True
        elif action == "start":
            assert staged
            m.STATE.write_text("{}")
            if fail_start:
                raise RuntimeError("SIMULATED_GNOME_START")
        elif action == "stop":
            assert staged and m.STATE.exists()
            m.STATE.unlink()
        elif action == "unstage":
            assert staged
            assert not m.STATE.exists()
        else:
            pytest.fail("unknown GNOME action")

    def native_reference():
        events.append("native")
        if fail_native:
            raise RuntimeError("SIMULATED_NATIVE_FAILURE")
        return "NATIVE_RDP_SESSION=ALIVE_THROUGH_WINDOW"

    monkeypatch.setattr(m, "command", command)
    monkeypatch.setattr(m, "staged_runner_trusted", staged_runner_trusted)
    monkeypatch.setattr(m, "gnome", gnome)
    monkeypatch.setattr(m, "native_reference", native_reference)
    return m, events


def test_one_shot_creates_and_revokes_exactly_one_guarded_rdp_window(tmp_path, monkeypatch):
    m, events = simulated(tmp_path, monkeypatch)
    assert m.main() == 0
    assert events == ["stage", "start", "native", "stop", "unstage"]
    assert not m.STATE.exists()


@pytest.mark.parametrize("fail_native,fail_start", [(True, False), (False, True)])
def test_native_or_gnome_start_failure_stops_rdp_before_unstaging(
    tmp_path, monkeypatch, fail_native, fail_start
):
    m, events = simulated(tmp_path, monkeypatch, fail_native=fail_native, fail_start=fail_start)
    assert m.main() == 2
    assert events[-2:] == ["stop", "unstage"]
    assert not m.STATE.exists()


def test_monitor_or_identity_failure_prevents_all_staging(tmp_path, monkeypatch):
    m, events = simulated(tmp_path, monkeypatch)
    monkeypatch.setattr(m, "monitor_readonly",
                        lambda _u: (_ for _ in ()).throw(RuntimeError("MONITOR_MISMATCH")))
    assert m.main() == 2
    assert events == []


def test_production_and_physical_safety_contracts():
    source = SCRIPT.read_text()
    assert 'RELEASE = "clientflow-1.3.47-seq-1248"' in source
    assert 'HOST = "viborg1-NUC14MNK-B2"' in source
    assert "GNOME_PILOT_ALREADY_ACTIVE" in source
    assert "OLD_AGENT_ROLLBACK_ACTIVE" in source
    assert "UNEXPECTED_AGENT_OVERRIDE" in source
    assert "ROOT_FIREWALL_WATCHDOG_STAGE" in source
    assert "GNOME_MONITOR_MODE_NOT_VERIFIED" in source
    assert "NATIVE_REFERENCE_DEPENDENCY_MISSING" in source
    assert "STAGED_GUARD" in source
    assert "clientflow_63d30_local_rdp_pilot.py" in source
    assert "GNOME_RDP_STOP" in source
    assert "GNOME_ROOT_WATCHDOG_UNSTAGED" in source
    assert "GNOME_PILOT_CLEANUP" in source
    assert "CLIENTFLOW_RELEASE_CHANGED" in source
    assert "RENDER_CHANGED" in source
    assert '"start", staged=True' in source
    assert '"stop", staged=True' in source
    assert '"unstage", staged=True' in source
    assert '"/usr/bin/python3"' in source
    assert '"tls.key"' not in source
    assert '"password"' not in source
    assert '"/cert:ignore"' not in source
    assert "systemctl restart" not in source
    assert "0.0.0.0" not in source
