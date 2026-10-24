"""Minimal stable, non-secret rollback outbox; no release-journal access for updater.

Root exporter reads the atomic transaction checkpoint and publishes read-only
receipts. The unprivileged updater reports them with its existing DPoP identity.
A failed export cannot consume or delete a source receipt. This module ships in
stable updater PYZ and remains usable after rollback to an older active release.
"""
from __future__ import annotations

from datetime import datetime
import grp
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

from .filesystem import fsync_directory, load_secure_json

OUTBOX_ROOT = Path("/var/lib/planiq-rollback-outbox")
ROOT_STATE = Path("/var/lib/clientflow/release/state.json")
ACK_FILE = "rollback-acknowledged.json"
_MAX_EVENTS = 10000
_RELEASE_RE = re.compile(r"^clientflow-\d+\.\d+\.\d+-seq-[1-9]\d*$")


class RollbackOutboxError(RuntimeError):
    pass


def _uuid(value: object) -> str:
    try:
        result = str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise RollbackOutboxError("Rollback outbox har ugyldigt permit/event-ID") from exc
    if result != value:
        raise RollbackOutboxError("Rollback outbox kræver canonical UUID")
    return result


def _receipt(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {"permit_id", "event_id", "outcome", "occurred_at", "to_release_id"}:
        raise RollbackOutboxError("Rollback receipt har ugyldige felter")
    permit = _uuid(value["permit_id"])
    event = _uuid(value["event_id"])
    outcome = value["outcome"]
    if outcome not in {"succeeded", "failed"}:
        raise RollbackOutboxError("Rollback receipt har ugyldigt resultat")
    if event != str(uuid.uuid5(uuid.NAMESPACE_URL, f"planiq-clientflow-rollback-{outcome}:" + permit)):
        raise RollbackOutboxError("Rollback event-ID matcher ikke tilladelsen")
    if not _RELEASE_RE.fullmatch(str(value["to_release_id"])):
        raise RollbackOutboxError("Rollback receipt har ugyldigt target")
    timestamp = value["occurred_at"]
    if not isinstance(timestamp, str) or len(timestamp) > 64:
        raise RollbackOutboxError("Rollback timestamp er ugyldigt")
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RollbackOutboxError("Rollback timestamp er ugyldigt") from exc
    return dict(value)


def _read_root_state(path: Path) -> dict:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077
                or metadata.st_uid != 0 or metadata.st_size > 4 * 1024 * 1024):
            raise RollbackOutboxError("Root release-journal har usikre rettigheder")
    finally:
        os.close(descriptor)
    return load_secure_json(path, max_bytes=4 * 1024 * 1024)


def _root_outbox_directory(path: Path, *, gid: int) -> None:
    path.mkdir(mode=0o750, parents=False, exist_ok=True)
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o007:
        raise RollbackOutboxError("Rollback outbox har usikker mappe")
    os.chown(path, 0, gid)
    os.chmod(path, 0o750)


def _write_receipt(path: Path, value: dict, *, gid: int) -> bool:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if path.exists() or path.is_symlink():
        existing = load_secure_json(path, max_bytes=2048, forbidden_mode_bits=0o117)
        st = path.lstat()
        if st.st_uid != 0 or st.st_gid != gid or existing != value:
            raise RollbackOutboxError("Tidligere offentliggjort rollback receipt er ændret")
        return False
    fd, temp = tempfile.mkstemp(prefix=".rollback.", dir=path.parent)
    tmp = Path(temp)
    try:
        os.fchown(fd, 0, gid)
        os.fchmod(fd, 0o640)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        fsync_directory(path.parent)
    finally:
        tmp.unlink(missing_ok=True)
    return True


def export_completed_rollbacks(*, state_path: Path = ROOT_STATE, outbox_root: Path = OUTBOX_ROOT,
                               updater_gid: int | None = None) -> dict:
    if os.geteuid() != 0:
        raise RollbackOutboxError("Root-only rollback eksport kræver root")
    if updater_gid is None:
        updater_gid = grp.getgrnam("clientflow-updater").gr_gid
    state = _read_root_state(state_path)
    if state.get("schema_version") != 2:
        raise RollbackOutboxError("Ukendt release-journal schema")
    receipts = state.get("rollback_reports", {})
    if not isinstance(receipts, dict) or len(receipts) > _MAX_EVENTS:
        raise RollbackOutboxError("Rollback eksportjournal er ugyldig eller for stor")
    outbox_root.parent.mkdir(parents=True, exist_ok=True)
    _root_outbox_directory(outbox_root, gid=updater_gid)
    created = 0
    for permit, value in sorted(receipts.items()):
        _uuid(permit)
        receipt = _receipt(value)
        if receipt["permit_id"] != permit or state.get("used_rollback_permits", {}).get(permit) != receipt["to_release_id"]:
            raise RollbackOutboxError("Rollback receipt matcher ikke root-forbrugsjournal")
        if _write_receipt(outbox_root / (receipt["event_id"] + ".json"), receipt, gid=updater_gid):
            created += 1
    return {"published": created, "total": len(receipts)}


class RollbackReceiptQueue:
    """Read-only root receipts; per-updater-user durable acknowledgement."""

    def __init__(self, state_root: Path, *, outbox_root: Path = OUTBOX_ROOT):
        self.state_root = Path(state_root)
        self.outbox_root = Path(outbox_root)
        self.ack_path = self.state_root / ACK_FILE

    def _acknowledged(self) -> dict:
        if not self.ack_path.exists():
            return {}
        data = load_secure_json(self.ack_path, max_bytes=1024 * 1024)
        if data.get("schema_version") != 1 or not isinstance(data.get("events"), dict):
            raise RollbackOutboxError("Rollback acknowledgement har ugyldigt schema")
        return data["events"]

    def pending(self) -> list[dict]:
        if not self.outbox_root.exists():
            return []
        st = self.outbox_root.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o007:
            raise RollbackOutboxError("Rollback outbox er ikke root-beskyttet")
        acknowledged = self._acknowledged()
        pending = []
        for path in sorted(self.outbox_root.iterdir()):
            if path.name.startswith("."):
                continue  # Exporter temporary files are not committed events.
            if not path.name.endswith(".json"):
                raise RollbackOutboxError("Ukendt rollback outbox-fil")
            data = load_secure_json(path, max_bytes=2048, forbidden_mode_bits=0o117)
            st = path.lstat()
            if st.st_uid != 0 or st.st_mode & 0o117 or (os.geteuid() != 0 and st.st_gid != os.getegid()):
                raise RollbackOutboxError("Rollback receipt har usikkert ejerskab")
            receipt = _receipt(data)
            if path.name != receipt["event_id"] + ".json":
                raise RollbackOutboxError("Rollback receipt filename matcher ikke event-ID")
            if receipt["event_id"] not in acknowledged:
                pending.append(receipt)
        return pending

    def acknowledge(self, receipt: dict) -> None:
        receipt = _receipt(receipt)
        events = self._acknowledged()
        if receipt["event_id"] in events:
            return
        events[receipt["event_id"]] = receipt["permit_id"]
        if len(events) > _MAX_EVENTS:
            raise RollbackOutboxError("Rollback-acknowledgement er fuld")
        # Do not use filesystem.atomic_write_json here: its generic directory
        # helper would chmod the private updater state directory to 0755.
        if self.ack_path.is_symlink():
            raise RollbackOutboxError("Rollback acknowledgement må ikke være symlink")
        raw = (json.dumps({"schema_version": 1, "events": events}, sort_keys=True) + "\n").encode("utf-8")
        fd, temp = tempfile.mkstemp(prefix=".rollback-ack.", dir=self.state_root)
        tmp = Path(temp)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.ack_path)
            fsync_directory(self.state_root)
        finally:
            tmp.unlink(missing_ok=True)
