"""A failed historical Control Room reboot must not poison current Status."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from service1.system_control import power_projection_from_command
from service1.routers.clients import _apply_system_projection_for_read


REQUESTED_AT = datetime(2026, 10, 19, 17, 44, 10, tzinfo=timezone.utc)


def command(status: str, *, action: str = "reboot", requested_boot_id: str | None = "old-boot"):
    return SimpleNamespace(
        command_type=action,
        status=status,
        payload={"source": "control_room", "requested_boot_id": requested_boot_id},
        requested_at=REQUESTED_AT,
        claimed_at=None if status in {"queued", "expired", "cancelled"} else REQUESTED_AT + timedelta(seconds=2),
        completed_at=REQUESTED_AT + timedelta(minutes=5) if status in {"succeeded", "failed", "expired", "cancelled"} else None,
    )


@pytest.mark.parametrize("status", ["failed", "expired", "cancelled"])
def test_historical_failed_command_does_not_override_online_new_boot(status):
    # Heidi1: Control Room command expired without a claim; a local reboot
    # completed and Status is now online with a different boot ID.
    projected = power_projection_from_command(command(status), current_boot_id="new-boot", status_online=True)
    assert projected["state"] == "normal"
    assert projected["pending_reboot"] is False
    assert projected["last_power_event"] is None
    assert projected["last_power_event_source"] is None
    assert projected["last_power_event_at"] is None
    # Never fabricate a successful execution of the historical failed command.
    assert command(status).status == status


@pytest.mark.parametrize("online,boot_id", [
    (False, "new-boot"),
    (True, "old-boot"),
    (True, None),
])
def test_terminal_command_error_remains_visible_without_verified_recovery(online, boot_id):
    projected = power_projection_from_command(command("expired"), current_boot_id=boot_id, status_online=online)
    assert projected["state"] == "error"
    assert projected["last_power_event"] == "reboot_started"
    assert projected["last_power_event_source"] == "control_room"


def test_missing_requested_boot_id_does_not_count_as_verified_recovery():
    projected = power_projection_from_command(
        command("expired", requested_boot_id=None), current_boot_id="new-boot", status_online=True,
    )
    assert projected["state"] == "error"


@pytest.mark.parametrize("status,expected_state,expected_pending", [
    ("queued", "rebooting", True),
    ("claimed", "rebooting", True),
    ("succeeded", "normal", False),
])
def test_active_and_successful_reboot_contract_remains_unchanged(status, expected_state, expected_pending):
    projected = power_projection_from_command(command(status), current_boot_id="new-boot", status_online=True)
    assert projected["state"] == expected_state
    assert projected["pending_reboot"] is expected_pending


def test_shutdown_failures_are_not_reclassified_as_reboot_recovery():
    projected = power_projection_from_command(
        command("expired", action="shutdown"), current_boot_id="new-boot", status_online=True,
    )
    assert projected["state"] == "error"
    assert projected["pending_shutdown"] is False


def test_client_read_keeps_local_reboot_completed_event_after_expired_remote_command():
    client = SimpleNamespace(
        id=1,
        state="normal",
        last_power_event="reboot_completed",
        last_power_event_at=REQUESTED_AT + timedelta(minutes=2),
        last_power_event_source="local",
        last_reboot_started_at=REQUESTED_AT + timedelta(seconds=25),
        last_shutdown_started_at=None,
    )
    presence = SimpleNamespace(status=SimpleNamespace(boot_id="new-boot", is_online=True))
    row = command("expired")
    _apply_system_projection_for_read(
        None, client, presence,
        projection_commands={"power": row, "os_update": None, "firmware_update": None, "local_management": None},
    )
    assert client.state == "normal"
    assert client.pending_reboot is False
    assert client.last_power_event == "reboot_completed"
    assert client.last_power_event_source == "local"
    assert client.last_reboot_started_at == REQUESTED_AT + timedelta(seconds=25)
    # Projection is read-only: no command mutation or persistence write.
    assert row.status == "expired"
