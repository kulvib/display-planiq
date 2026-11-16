"""61B-2 isolated, host-free system update maintenance safety contracts.

No APT, fwupd, real Chrome, real boot or production command is executed.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "client/runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from clientflow_runtime import update_maintenance as maintenance  # noqa: E402
from clientflow_runtime import system_broker  # noqa: E402
from clientflow_runtime import display_runtime  # noqa: E402
from clientflow_runtime import status_agent  # noqa: E402

COMMAND = "00000000-0000-4000-8000-000000000444"
OTHER_COMMAND = "00000000-0000-4000-8000-000000000445"
BOOT_BEFORE = "11111111-1111-4111-8111-111111111111"
BOOT_AFTER = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    directory = tmp_path / "maintenance"
    monkeypatch.setattr(maintenance, "STATE_DIR", directory)
    monkeypatch.setattr(maintenance, "STATE_PATH", directory / "state.json")
    broker_directory = tmp_path / "broker"
    monkeypatch.setattr(system_broker, "STATE_DIR", broker_directory)
    monkeypatch.setattr(system_broker, "JOURNAL_PATH", broker_directory / "command-journal.json")
    monkeypatch.setattr(system_broker, "JOURNAL_LOCK_PATH", broker_directory / "command-journal.lock")
    boot_file = tmp_path / "boot-id"
    boot_file.write_text(BOOT_BEFORE + "\n", encoding="ascii")
    monkeypatch.setattr(system_broker, "BOOT_ID_PATH", boot_file)
    return boot_file


def _begin():
    maintenance.begin(action="update_os", client_id=3, command_id=COMMAND, boot_id=BOOT_BEFORE)


def _request(action="update_os"):
    return {"schema_version": 1, "client_id": 3, "command_id": COMMAND,
            "action": action, "payload": {}}


def test_root_owned_marker_is_readable_but_blocks_chrome_until_verified_complete(isolated):
    assert maintenance.read_state() is None
    assert maintenance.is_active() is False
    _begin()
    assert maintenance.STATE_DIR.stat().st_mode & 0o777 == 0o755
    assert maintenance.STATE_PATH.stat().st_mode & 0o777 == 0o644
    assert maintenance.is_active() is True
    assert maintenance.public_snapshot()["phase"] == "browser_stopping"
    with pytest.raises(maintenance.MaintenanceStateError, match="already_active"):
        maintenance.begin(action="update_firmware", client_id=4, command_id=OTHER_COMMAND, boot_id=BOOT_BEFORE)
    with pytest.raises(maintenance.MaintenanceStateError, match="binding_mismatch"):
        maintenance.advance(action="update_os", client_id=4, command_id=COMMAND, phase="completed")
    maintenance.advance(action="update_os", client_id=3, command_id=COMMAND, phase="installing")
    maintenance.advance(action="update_os", client_id=3, command_id=COMMAND,
                        phase="completed", reboot_required=False)
    assert maintenance.is_active() is False
    assert maintenance.public_snapshot()["active"] is False


def test_symlink_or_corrupt_marker_never_opens_browser(isolated, tmp_path):
    maintenance.STATE_DIR.mkdir(mode=0o755)
    marker_target = tmp_path / "outside.json"
    marker_target.write_text("{}", encoding="utf-8")
    maintenance.STATE_PATH.symlink_to(marker_target)
    assert maintenance.is_active() is True
    assert maintenance.public_snapshot()["phase"] == "recovery_required"
    maintenance.STATE_PATH.unlink()
    maintenance.STATE_PATH.write_text("not-json", encoding="utf-8")
    assert maintenance.is_active() is True
    assert maintenance.public_snapshot()["phase"] == "recovery_required"


def test_display_runtime_never_starts_or_resets_chrome_with_active_marker(monkeypatch, isolated):
    _begin()
    runtime = display_runtime.DisplayRuntime.__new__(display_runtime.DisplayRuntime)
    runtime.browser_requested = False
    runtime.internet = SimpleNamespace(online=True)
    emitted = []
    runtime._status = lambda *args, **kwargs: emitted.append((args, kwargs))
    assert runtime.start_browser(source="backend")["blocked"] is True
    assert runtime.restart_browser()["blocked"] is True
    assert runtime.reset_browser()["blocked"] is True
    assert runtime.request_start_browser(source="gui")["blocked"] is True
    assert all(args[0] == "stopped" for args, _ in emitted)


def test_update_broker_stops_and_confirms_browser_before_apt_helper(monkeypatch, isolated):
    events = []

    def rpc(_socket, request, **_kwargs):
        events.append(request["action"])
        if request["action"] == "stop_browser":
            assert request["payload"]["source"] == "update_maintenance"
            assert maintenance.read_state()["phase"] == "browser_stopping"
            return {"stopped": True, "was_running": True}
        if request["action"] == "status":
            return {"pid": None, "state": "stopped"}
        raise AssertionError(request)

    def helper(_prepared):
        events.append("apt-helper")
        assert maintenance.read_state()["phase"] == "installing"
        return {"exit_code": 0, "output": "CLIENTFLOW_REBOOT_REQUIRED=0\nOS-opdatering gennemført"}

    monkeypatch.setattr(system_broker, "call", rpc)
    monkeypatch.setattr(system_broker, "_prepare", lambda *_args, **_kwargs: {"command": ["no-execute"]})
    monkeypatch.setattr(system_broker, "_execute", helper)
    response = system_broker.handle(_request())
    assert response["reboot_required"] is False
    assert events == ["stop_browser", "status", "apt-helper"]
    assert maintenance.read_state()["phase"] == "completed"
    # Retrying exact command never executes the helper again.
    assert system_broker.handle(_request()) == response
    assert events == ["stop_browser", "status", "apt-helper"]


def test_update_broker_fail_closed_when_chrome_stop_not_confirmed(monkeypatch, isolated):
    monkeypatch.setattr(system_broker, "call", lambda *_args, **_kwargs: {"stopped": False})
    monkeypatch.setattr(system_broker, "_prepare", lambda *_args, **_kwargs: {"command": ["no-execute"]})
    monkeypatch.setattr(system_broker, "_execute", lambda *_args: pytest.fail("apt/fwupd must NOT run"))
    monkeypatch.setattr(system_broker, "clear_system_intent", lambda: None)
    with pytest.raises(system_broker.SystemCommandInDoubt):
        system_broker.handle(_request())
    assert maintenance.read_state()["phase"] == "recovery_required"
    assert system_broker._load_journal()[f"3:{COMMAND}"]["state"] == "in_doubt"
    with pytest.raises(maintenance.MaintenanceStateError, match="already_active"):
        maintenance.begin(action="update_os", client_id=3, command_id=OTHER_COMMAND, boot_id=BOOT_BEFORE)


def test_reboot_recovery_needs_real_new_boot_and_healthy_services(monkeypatch, isolated):
    _begin()
    maintenance.advance(action="update_os", client_id=3, command_id=COMMAND,
                        phase="rebooting", reboot_required=True)
    recovered = {"previous_boot_id": BOOT_BEFORE, "observed_boot_id": BOOT_AFTER}
    monkeypatch.setattr(system_broker, "_fixed_binary", lambda _name: "/usr/bin/systemctl")
    monkeypatch.setattr(system_broker, "_run", lambda cmd, **kwargs: {
        "exit_code": 0, "output": "active\nactive\nactive\nactive\n"
    })
    with pytest.raises(system_broker.SystemCommandInDoubt, match="boot_boundary"):
        system_broker._complete_update_maintenance_after_boot(
            client_id=3, command_id=COMMAND, action="update_os", recovered=recovered)
    assert maintenance.is_active() is True
    isolated.write_text(BOOT_AFTER + "\n", encoding="ascii")
    system_broker._complete_update_maintenance_after_boot(
        client_id=3, command_id=COMMAND, action="update_os", recovered=recovered)
    assert maintenance.read_state()["observed_boot_id"] == BOOT_AFTER
    assert maintenance.read_state()["phase"] == "completed"
    # Replaying the same post-boot result must not produce an in-doubt error.
    system_broker._complete_update_maintenance_after_boot(
        client_id=3, command_id=COMMAND, action="update_os", recovered=recovered)
    assert maintenance.read_state()["phase"] == "completed"


def test_post_boot_unhealthy_units_keep_chrome_closed(monkeypatch, isolated):
    _begin()
    maintenance.advance(action="update_os", client_id=3, command_id=COMMAND,
                        phase="rebooting", reboot_required=True)
    isolated.write_text(BOOT_AFTER + "\n", encoding="ascii")
    monkeypatch.setattr(system_broker, "_fixed_binary", lambda _name: "/usr/bin/systemctl")
    monkeypatch.setattr(system_broker, "_run", lambda cmd, **kwargs: {"exit_code": 0, "output": "active\nfailed\nactive\nactive\n"})
    with pytest.raises(system_broker.SystemCommandInDoubt, match="unhealthy"):
        system_broker._complete_update_maintenance_after_boot(
            client_id=3, command_id=COMMAND, action="update_os",
            recovered={"previous_boot_id": BOOT_BEFORE, "observed_boot_id": BOOT_AFTER})
    assert maintenance.read_state()["phase"] == "recovery_required"
    assert maintenance.is_active()


def test_status_agent_piggybacks_the_same_local_marker_without_new_poll(monkeypatch, isolated):
    # No new periodic request or database write; the existing status payload is used.
    _begin()
    monkeypatch.setattr(status_agent, "_network_status", lambda: {})
    monkeypatch.setattr(status_agent, "_time_status", lambda: {})
    monkeypatch.setattr(status_agent, "_service_status", lambda: {})
    monkeypatch.setattr(status_agent, "_meminfo", lambda: {})
    monkeypatch.setattr(status_agent, "_uptime", lambda: 1.0)
    monkeypatch.setattr(status_agent, "_ubuntu_version", lambda: "Ubuntu 26.04")
    monkeypatch.setattr(status_agent, "collect_completed_local_power_event", lambda: None)
    payload = status_agent.collect_host_status()
    assert payload["update_maintenance"]["phase"] == "browser_stopping"
    assert payload["update_maintenance"]["active"] is True
    assert "command_id" not in payload["update_maintenance"]
