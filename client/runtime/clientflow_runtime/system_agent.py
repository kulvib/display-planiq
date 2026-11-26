"""System command agent. It can call only the fixed-function local system broker."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import logging
import subprocess
import time
from typing import Any

from .atomic import atomic_write_json
from .command_agent import CommandContext, CommandRejected, QueueAgent
from .config import DomainCredential
from .constants import Domain
from .net import DomainTransport
from .unix_rpc import RpcError, call

SYSTEM_SOCKET = os.getenv("CLIENTFLOW_SYSTEM_SOCKET", "/run/clientflow/system.sock")
FWUPDMGR = Path("/usr/bin/fwupdmgr")
APT = Path("/usr/bin/apt")
APT_INDEX_STAMPS = (Path("/var/lib/apt/periodic/update-success-stamp"),
                    Path("/var/lib/clientflow/ubuntu-index-refresh"))
UPDATE_STATUS_PATH = Path("/var/lib/clientflow/update-status/summary.json")
APT_CHECK_TTL_SECONDS = 900
APT_ERROR_RETRY_SECONDS = 300
APT_INDEX_MAX_AGE_SECONDS = 48 * 3600
_UPGRADABLE = re.compile(r"^[^/\s]+/\S+\s+\S+\s+\S+\s+\[upgradable from: [^\]]+\]$")
FIRMWARE_STATUS_TTL_SECONDS = max(300, int(os.getenv("CLIENTFLOW_FIRMWARE_STATUS_TTL_SECONDS", "21600")))


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apt_fingerprint() -> tuple:
    values = []
    for path in (*APT_INDEX_STAMPS, Path("/var/lib/dpkg/status")):
        try:
            values.append(path.stat().st_mtime_ns)
        except OSError:
            values.append(None)
    return tuple(values)


def _parse_apt_upgradable(output: str) -> int:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines or lines[0] != "Listing..." or any(not _UPGRADABLE.fullmatch(line) for line in lines[1:]):
        raise ValueError("unexpected_apt_output")
    return len(lines) - 1


def _ubuntu_snapshot() -> dict[str, Any]:
    value = {"schema_version": 1, "provider": "apt-cache", "checked_at": _iso_now(),
             "index_checked_at": None, "update_count": None, "state": "unknown",
             "requires_reboot": Path("/run/reboot-required").exists()}
    before = _apt_fingerprint()
    stamps = [stamp for stamp in before[:2] if stamp is not None]
    if not stamps:
        return {**value, "error": "apt_index_timestamp_missing"}
    newest = max(stamps) / 1e9
    value["index_checked_at"] = datetime.fromtimestamp(newest, timezone.utc).isoformat()
    if not -60 <= time.time() - newest <= APT_INDEX_MAX_AGE_SECONDS:
        return {**value, "state": "stale", "error": "apt_index_stale"}
    try:
        # Cached local inspection only, never installation or index refresh.
        result = subprocess.run(
            [str(APT), "list", "--upgradable"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
            check=False, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        if result.returncode != 0:
            return {**value, "error": "apt_list_failed"}
        count = _parse_apt_upgradable(result.stdout.decode("utf-8", errors="strict"))
        if _apt_fingerprint() != before:
            return {**value, "error": "apt_index_changed"}
        return {**value, "state": "known", "update_count": count, "error": None}
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        return {**value, "error": "apt_list_unavailable"}


class UbuntuStatusCache:
    def invalidate(self) -> None:
        self._value = None

    def __init__(self) -> None:
        self._value = None
        self._fingerprint = None
        self._loaded_at = 0.0

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        fingerprint = _apt_fingerprint()
        ttl = APT_ERROR_RETRY_SECONDS if self._value is not None and self._value.get("state") == "unknown" else APT_CHECK_TTL_SECONDS
        # A cached positive count must not remain known past the APT index age
        # boundary, even if the package database did not change.
        stamps = [stamp for stamp in fingerprint[:2] if stamp is not None]
        index_fresh = bool(stamps) and -60 <= time.time() - max(stamps) / 1e9 <= APT_INDEX_MAX_AGE_SECONDS
        known_index_expired = self._value is not None and self._value.get("state") == "known" and not index_fresh
        if self._value is None or fingerprint != self._fingerprint or known_index_expired or now - self._loaded_at >= ttl:
            self._value = _ubuntu_snapshot()
            self._fingerprint = fingerprint
            self._loaded_at = now
        # A reboot marker can appear independently of the APT/dpkg fingerprint.
        # Refresh this cheap observation without forcing another apt invocation.
        return {**self._value, "requires_reboot": Path("/run/reboot-required").exists()}


def _run_fwupd_json(*args: str, timeout: int = 45) -> tuple[int, dict[str, Any] | None, str | None]:
    if not FWUPDMGR.is_file() or not os.access(FWUPDMGR, os.X_OK):
        return 127, None, "fwupdmgr_missing"
    completed = subprocess.run(
        [str(FWUPDMGR), *args, "--json"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    raw = completed.stdout.decode("utf-8", errors="replace").strip()
    error = completed.stderr.decode("utf-8", errors="replace").strip()[:500]
    if completed.returncode not in {0, 2}:
        return completed.returncode, None, error or f"fwupdmgr_exit_{completed.returncode}"
    if not raw:
        return completed.returncode, {}, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return completed.returncode, None, "fwupdmgr_invalid_json"
    if not isinstance(value, dict):
        return completed.returncode, None, "fwupdmgr_invalid_json"
    return completed.returncode, value, None


def _firmware_snapshot() -> dict[str, Any]:
    checked_at = _iso_now()
    if not FWUPDMGR.is_file() or not os.access(FWUPDMGR, os.X_OK):
        return {
            "supported": False,
            "provider": "fwupd",
            "update_available": False,
            "update_count": 0,
            "requires_reboot": False,
            "requires_shutdown": False,
            "checked_at": checked_at,
            "devices": [],
            "error": "fwupdmgr_missing",
        }

    devices_rc, devices_doc, devices_error = _run_fwupd_json("get-devices", timeout=15)
    updates_rc, updates_doc, updates_error = _run_fwupd_json("get-updates", timeout=20)
    if devices_doc is None:
        return {
            "supported": False,
            "provider": "fwupd",
            "update_available": False,
            "update_count": 0,
            "requires_reboot": False,
            "requires_shutdown": False,
            "checked_at": checked_at,
            "devices": [],
            "error": devices_error or f"fwupdmgr_get_devices_exit_{devices_rc}",
        }

    candidates = [] if updates_doc is None else updates_doc.get("Devices", [])
    if not isinstance(candidates, list) or len(candidates) > 32 or any(not isinstance(item, dict) for item in candidates):
        candidates = []
        updates_error = "fwupd_invalid_or_incomplete_devices"
    if updates_rc == 0 and not candidates and updates_error is None and (not isinstance(updates_doc, dict) or "Devices" not in updates_doc):
        updates_error = "fwupd_empty_success_response"
    sanitized: list[dict[str, Any]] = []
    requires_reboot = False
    requires_shutdown = False
    for raw in candidates[:32]:
        if not isinstance(raw, dict):
            continue
        flags_raw = raw.get("Flags")
        flags = [str(item)[:80] for item in flags_raw] if isinstance(flags_raw, list) else []
        requires_reboot = requires_reboot or "needs-reboot" in flags
        requires_shutdown = requires_shutdown or "needs-shutdown" in flags
        sanitized.append({
            "device_id": str(raw.get("DeviceId") or "")[:128] or None,
            "name": str(raw.get("Name") or "Ukendt firmwareenhed")[:160],
            "vendor": str(raw.get("Vendor") or "")[:120] or None,
            "version": str(raw.get("Version") or "")[:120] or None,
            "available_versions": [str(item.get("Version"))[:120] for item in (raw.get("Releases") if isinstance(raw.get("Releases"), list) else [])[:8] if isinstance(item, dict) and item.get("Version")],
            "flags": flags,
        })

    error = updates_error
    return {
        "supported": True,
        "provider": "fwupd",
        "update_available": bool(sanitized),
        "update_count": len(sanitized),
        "requires_reboot": requires_reboot,
        "requires_shutdown": requires_shutdown,
        "checked_at": checked_at,
        "devices": sanitized,
        "error": error,
        "get_updates_exit_code": updates_rc,
    }


class FirmwareStatusCache:
    def invalidate(self) -> None:
        self._value = None

    def __init__(self) -> None:
        self._value: dict[str, Any] | None = None
        self._loaded_at = 0.0

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        ttl = 300 if self._value is not None and self._value.get("error") else FIRMWARE_STATUS_TTL_SECONDS
        if self._value is None or now - self._loaded_at >= ttl:
            try:
                self._value = _firmware_snapshot()
            except Exception as exc:
                self._value = {
                    "supported": False,
                    "provider": "fwupd",
                    "update_available": False,
                    "update_count": 0,
                    "requires_reboot": False,
                    "requires_shutdown": False,
                    "checked_at": _iso_now(),
                    "devices": [],
                    "error": f"firmware_status_error:{type(exc).__name__}",
                }
            self._loaded_at = now
        return dict(self._value)


def build_handler(transport: DomainTransport, *, invalidate_inventory=None):
    def handle(context: CommandContext) -> dict[str, Any]:
        payload = dict(context.payload)
        try:
            return call(
                SYSTEM_SOCKET,
                {
                    "action": context.command_type,
                    "client_id": context.client_id,
                    "command_id": context.command_id,
                    "schema_version": context.schema_version,
                    "payload": payload,
                },
                timeout=7250 if context.command_type in {"update_os", "update_firmware"} else 1850,
            )
        except RpcError as exc:
            message = str(exc)
            in_doubt = "system_command_in_doubt" in message or "system_command_journal" in message
            retryable = not in_doubt and context.command_type in {"update_os", "update_firmware"}
            code = "system_command_in_doubt" if in_doubt else "system_broker_error"
            raise CommandRejected(code, message, retryable=retryable) from exc
        finally:
            if invalidate_inventory is not None and context.command_type in {"update_os", "update_firmware"}:
                invalidate_inventory()
    return handle


def main() -> int:
    credential = DomainCredential.load(Domain.SYSTEM)
    transport = DomainTransport(credential)
    firmware_cache = FirmwareStatusCache()
    ubuntu_cache = UbuntuStatusCache()

    def status_payload():
        ubuntu = ubuntu_cache.snapshot()
        firmware = firmware_cache.snapshot()
        # Display-only snapshot; never publish credentials or raw command output.
        public = {"schema_version": 1, "ubuntu": ubuntu, "firmware": {
            key: firmware.get(key) for key in ("supported", "checked_at", "update_count",
                "update_available", "requires_reboot", "requires_shutdown")
        }}
        public["firmware"]["error"] = bool(firmware.get("error"))
        try:
            if not UPDATE_STATUS_PATH.exists() or json.loads(UPDATE_STATUS_PATH.read_text()) != public:
                atomic_write_json(UPDATE_STATUS_PATH, public, mode=0o644)
        except (OSError, ValueError):
            logging.getLogger(__name__).warning("public_update_status_unavailable")
        return {
            "broker_socket": os.path.exists(SYSTEM_SOCKET),
            "safe_reboot_recovery": True,
            "firmware": firmware,
            "ubuntu_update_inventory": ubuntu,
        }

    def invalidate_inventory():
        ubuntu_cache.invalidate()
        firmware_cache.invalidate()

    QueueAgent(
        transport,
        build_handler(transport, invalidate_inventory=invalidate_inventory),
        lease_seconds=300,
        status_payload=status_payload,
        piggyback_status_on_claim=True,
    ).run_forever()
    return 0
