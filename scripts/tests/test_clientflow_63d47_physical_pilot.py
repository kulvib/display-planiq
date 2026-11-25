"""63D-47 pinned physical operator: static and non-destructive regression tests."""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "clientflow_63d47_physical_pilot.py"


def load_operator(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/sbin:/usr/bin:/sbin:/bin")
    spec = importlib.util.spec_from_file_location("cf_63d47_tested_operator", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pinned_sources_and_executable_shadow_entrypoint(monkeypatch):
    pilot = load_operator(monkeypatch)
    assert pilot.CLIENT_ID == 3
    assert pilot.HOST == "viborg1-NUC14MNK-B2"
    assert pilot.ACTIVE_RELEASE == "clientflow-1.3.47-seq-1248"
    assert pilot.COMMIT == "e58a1f2a2fe52df79df5c0dc50649077d042ccc1"
    assert pilot.EXPECTED["client/runtime/clientflow_runtime/native_rdp_forwarder.py"] == (
        "52bfba4fc883854e47c67d75f7a19e70757a663b20b7ca1903eec43c947e4ee3"
    )
    assert pilot.EXPECTED["client/runtime/clientflow_runtime/remote_desktop_agent.py"] == (
        "a99dc405cd286ec19f70c9e0701a399aa677e2accfefeadda4010f7c39fd4f95"
    )
    assert all(len(digest) == 64 for digest in pilot.EXPECTED.values())
    compile(pilot.ENTRY, "shadow-entrypoint.py", "exec")
    assert pilot.BUNDLE.as_posix() in pilot.EXPECTED_DROPIN
    assert "compression=None" in pilot.ENTRY  # verifies hash-pinned source opts out of deflate
    assert "Path(module.__file__).resolve().parent != ROOT" in pilot.ENTRY
    assert "remote_desktop_agent.main()" in pilot.ENTRY


def test_source_watches_and_timeouts_fails_closed(monkeypatch):
    load_operator(monkeypatch)
    source = SCRIPT.read_text()
    assert '"--on-active=10m"' in source
    assert '"GNOME_START"' not in source  # named GNOME action, not a separate bypass
    assert 'gnome("start", staged=True)' in source
    assert 'check_file(GNOME_RUNNER,' in source
    assert 'browser("arm")' in source
    assert 'stop_physical_pilot()' in source
    assert 'rollback_agent(cancel_timer=True)' in source
    assert "RDP_WINDOW_MAX=6_MINUTES" in source
    assert "MANUAL_STOP=" in source
    assert '"/usr/sbin:/usr/bin:/sbin:/bin"' in source
    assert "RDP_LOGIN_FILE=" not in source  # no printed credentials
    assert '"password"' not in source


def test_exact_dropin_rollback_restores_original_agent(tmp_path, monkeypatch):
    pilot = load_operator(monkeypatch)
    dropin = tmp_path / "systemd" / "63d47-native-rdp.conf"
    dropin.parent.mkdir()
    dropin.write_text(pilot.EXPECTED_DROPIN)
    monkeypatch.setattr(pilot, "DROPIN", dropin)
    monkeypatch.setattr(pilot, "check_target", lambda: None)
    monkeypatch.setattr(pilot, "check_directory", lambda *_args, **_kw: None)
    monkeypatch.setattr(pilot, "active", lambda name: name == pilot.UNIT)
    calls = []

    def safe_run(label, argv, **_kw):
        calls.append((label, argv))
        if label == "ROLLBACK_VERIFY_EXEC":
            return "ExecStart=/opt/clientflow/active/runtime/bin/clientflow-remote-desktop-agent"
        return ""

    monkeypatch.setattr(pilot, "run", safe_run)
    pilot.rollback_agent(cancel_timer=True)
    assert not dropin.exists()
    assert [label for label, _argv in calls] == [
        "ROLLBACK_DAEMON_RELOAD",
        "ROLLBACK_RESTART_ORIGINAL_AGENT",
        "ROLLBACK_VERIFY_EXEC",
    ]


def test_unknown_override_is_never_removed(tmp_path, monkeypatch):
    pilot = load_operator(monkeypatch)
    dropin = tmp_path / "systemd" / "63d47-native-rdp.conf"
    dropin.parent.mkdir()
    dropin.write_text("[Service]\\nExecStart=/unknown/binary\\n")
    monkeypatch.setattr(pilot, "DROPIN", dropin)
    monkeypatch.setattr(pilot, "check_target", lambda: None)
    monkeypatch.setattr(pilot, "check_directory", lambda *_args, **_kw: None)
    monkeypatch.setattr(pilot, "active", lambda name: True)
    monkeypatch.setattr(pilot, "run", lambda *args, **kwargs: pytest.fail("unsafe command reached"))
    with pytest.raises(RuntimeError, match="UNKNOWN_AGENT_OVERRIDE_CONTENT"):
        pilot.rollback_agent()
    assert dropin.exists()
