"""Offline installer contracts; no real systemd, GNOME or network mutations."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from scripts import clientflow_63d54_managed_pilot as pilot

ROOT = Path(__file__).resolve().parents[2]


def test_pins_match_already_green_source_tree():
    assert pilot.COMMIT == "a194579ca1dc31988e8d82de52738a9d05a9adf7"
    assert len(pilot.PINS) == 15
    for path, expected in pilot.PINS.items():
        raw = (ROOT / path).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected
        assert pilot.require_pin(path, raw) == raw
        with pytest.raises(pilot.Stop, match="SOURCE_SHA_MISMATCH"):
            pilot.require_pin(path, raw + b"x")


def test_shadow_covers_all_three_runtime_modules():
    ast.parse(pilot.ENTRY_BYTES)
    assert set(pilot.MODULES) == {
        "remote_desktop_agent.py", "native_rdp_forwarder.py", "native_rdp_autologin.py"}
    assert str(pilot.SHADOW).encode() in pilot.DROPIN_BYTES
    assert pilot.DROPIN.parent.parent == Path("/run/systemd/system")
    assert "1248" in pilot.RELEASE


def test_no_install_on_failed_preflight(monkeypatch):
    calls = []
    monkeypatch.setattr(pilot, "target", lambda: calls.append("target"))
    monkeypatch.setattr(pilot, "verify_clean", lambda: calls.append("clean"))

    def denied():
        calls.append("crypto")
        raise pilot.Stop("SYSTEM_CRYPTO_FAILED")

    monkeypatch.setattr(pilot, "crypto_preflight", denied)
    monkeypatch.setattr(pilot, "download_all", lambda: pytest.fail("download"))
    monkeypatch.setattr(pilot, "stage", lambda _: pytest.fail("stage"))
    with pytest.raises(pilot.Stop, match="SYSTEM_CRYPTO_FAILED"):
        pilot.install()
    assert calls == ["target", "clean", "crypto"]


def test_rollback_refuses_foreign_state_before_stopping_services(monkeypatch):
    monkeypatch.setattr(pilot, "target", lambda: None)

    def denied():
        raise pilot.Stop("FOREIGN_UNIT_CONTENT")

    monkeypatch.setattr(pilot, "verify_owned_installation", denied)
    monkeypatch.setattr(pilot, "systemctl", lambda *a, **k: pytest.fail("mutation"))
    with pytest.raises(pilot.Stop, match="FOREIGN_UNIT_CONTENT"):
        pilot.rollback()


def test_install_orders_timer_before_runtime_units_and_agent():
    src = (ROOT / "scripts/clientflow_63d54_managed_pilot.py").read_text()
    tree = ast.parse(src)
    install = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "install")
    body = ast.get_source_segment(src, install)
    assert body.index('"ARM_ROLLBACK"') < body.index("stage(sources)")
    assert body.index('"SYSTEMD_VERIFY"') < body.index('"START_LOCAL_SOCKETS"')
    assert body.index('"START_LOCAL_SOCKETS"') < body.index("write_new(DROPIN")
    assert body.index("write_new(DROPIN") < body.index('"START_CANDIDATE_AGENT"')
    assert '"enable"' not in body
    assert 'physical_paths()' in body


def test_rollback_waits_for_root_cleanup_before_removing_sources():
    src = (ROOT / "scripts/clientflow_63d54_managed_pilot.py").read_text()
    tree = ast.parse(src)
    rollback = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "rollback")
    body = ast.get_source_segment(src, rollback)
    assert body.index('"STOP_NEW_LEASES"') < body.index('"RESTORE_AGENT"')
    assert body.index("while active_instances()") < body.index('"STOP_SEALER"')
    assert body.index("PHYSICAL_CLEANUP_PENDING_KEEP_WATCHDOG") < body.index("path.unlink()")
    assert "physical_paths()" in body
