"""Root-owned, read-only-to-clients update maintenance contract (61B-2).

This is an OS/firmware maintenance gate, not release authorization.
Only the System broker may write the state. All other processes read a
sanitized status; a corrupt or unreadable marker fails closed for Chrome.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import time
import uuid
from typing import Any

from .atomic import atomic_write_json

STATE_DIR = Path("/var/lib/clientflow/update-maintenance")
STATE_PATH = STATE_DIR / "state.json"
ACTIONS = frozenset({"update_os", "update_firmware"})
PHASES = frozenset({
    "browser_stopping", "installing", "rebooting", "post_boot_check",
    "completed", "recovery_required",
})
PUBLIC_MESSAGES = {
    "browser_stopping": "Lukker kioskbrowser før systemopdatering",
    "installing": "Installerer systemopdatering",
    "rebooting": "Genstart kræves for at afslutte opdateringen",
    "post_boot_check": "Kontrollerer systemet efter genstart",
    "completed": "Systemopdatering gennemført; kiosk kontrolleres separat",
    "recovery_required": "Opdatering kræver kontrol og eventuel manuel recovery",
}


class MaintenanceStateError(RuntimeError):
    pass


def _validated_directory(*, create: bool = False) -> None:
    if create:
        STATE_DIR.mkdir(parents=True, mode=0o755, exist_ok=True)
    try:
        info = STATE_DIR.lstat()
    except FileNotFoundError:
        if create:
            raise MaintenanceStateError("maintenance_directory_missing")
        return
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
        raise MaintenanceStateError("maintenance_directory_untrusted")
    # The running client is root in production; tests may run unprivileged.
    if info.st_uid not in {0, os.geteuid()}:
        raise MaintenanceStateError("maintenance_directory_owner_untrusted")
    if create:
        # The broker runs with UMask=0077. Keep the root-owned directory
        # traversable to the kiosk/Status user while denying all mutations.
        os.chmod(STATE_DIR, 0o755)


def read_state() -> dict[str, Any] | None:
    _validated_directory()
    try:
        fd = os.open(STATE_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise MaintenanceStateError("maintenance_state_unreadable") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022
                or info.st_uid not in {0, os.geteuid()} or info.st_size > 8192):
            raise MaintenanceStateError("maintenance_state_untrusted")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(8193)
        if len(raw) > 8192:
            raise MaintenanceStateError("maintenance_state_oversize")
    finally:
        os.close(fd)
    try:
        value = json.loads(raw.decode("utf-8"))
        if (not isinstance(value, dict) or value.get("schema_version") != 1
                or value.get("action") not in ACTIONS or value.get("phase") not in PHASES
                or not isinstance(value.get("client_id"), int) or value["client_id"] <= 0):
            raise ValueError("invalid maintenance schema")
        uuid.UUID(str(value.get("command_id") or ""))
        return value
    except (UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise MaintenanceStateError("maintenance_state_corrupt") from exc


def is_active() -> bool:
    try:
        value = read_state()
    except MaintenanceStateError:
        return True
    return value is not None and value["phase"] != "completed"


def public_snapshot() -> dict[str, Any] | None:
    try:
        value = read_state()
    except MaintenanceStateError:
        return {"schema_version": 1, "phase": "recovery_required", "active": True,
                "message": PUBLIC_MESSAGES["recovery_required"]}
    if value is None:
        return None
    return {
        "schema_version": 1,
        "action": value["action"],
        "phase": value["phase"],
        "active": value["phase"] != "completed",
        "message": PUBLIC_MESSAGES[value["phase"]],
        "operation_id": value["command_id"],
        "updated_at": value.get("updated_at"),
        "reboot_required": value.get("reboot_required"),
        "requested_boot_id": value.get("requested_boot_id"),
        "observed_boot_id": value.get("observed_boot_id"),
    }


def begin(*, action: str, client_id: int, command_id: str, boot_id: str) -> None:
    if action not in ACTIONS or client_id <= 0:
        raise MaintenanceStateError("maintenance_action_invalid")
    uuid.UUID(command_id)
    _validated_directory(create=True)
    existing = read_state()
    if existing is not None and existing["phase"] != "completed":
        raise MaintenanceStateError("maintenance_already_active_or_in_doubt")
    now = time.time()
    atomic_write_json(STATE_PATH, {
        "schema_version": 1, "action": action, "client_id": client_id,
        "command_id": command_id, "phase": "browser_stopping",
        "started_at": now, "updated_at": now, "requested_boot_id": boot_id,
        "reboot_required": None,
    }, mode=0o644)


def advance(*, action: str, client_id: int, command_id: str, phase: str,
            reboot_required: bool | None = None,
            observed_boot_id: str | None = None) -> None:
    if phase not in PHASES:
        raise MaintenanceStateError("maintenance_phase_invalid")
    current = read_state()
    if (current is None or current["action"] != action
            or current["client_id"] != client_id or current["command_id"] != command_id):
        raise MaintenanceStateError("maintenance_binding_mismatch")
    if current["phase"] == "completed":
        raise MaintenanceStateError("maintenance_already_completed")
    current["phase"] = phase
    current["updated_at"] = time.time()
    if reboot_required is not None:
        current["reboot_required"] = reboot_required
    if observed_boot_id is not None:
        current["observed_boot_id"] = observed_boot_id
    if phase == "completed":
        current["completed_at"] = current["updated_at"]
    atomic_write_json(STATE_PATH, current, mode=0o644)
