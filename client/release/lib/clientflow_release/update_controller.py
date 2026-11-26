"""Privileged controller for the canonical ClientFlow in-place update transaction.

The stable updater remains unprivileged and owns only authenticated download and
verification.  This controller consumes only an already verified, deployment-
bound artifact and performs the privileged verified -> staged -> activating
handoff through the existing root-owned release transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Any, Callable
import uuid

from .constants import INSTALL_MODE_UPDATE
from .filesystem import atomic_write_json, ensure_real_directory, fsync_directory, load_secure_json
from .transaction import Layout, TransactionError, activate_release, recover_failed_update, stage_bundle, status, _health_check, _assert_no_temporary_media_override, prepare_post_boot_recovery
from .updater_config import UpdaterConfig
from .updater_state import DeploymentSnapshot
from .updater_transport import UpdaterTransport, UpdaterTransportError
from . import release_public_status, install_coordinator
import sys

MAX_SOURCE_STATE_BYTES = 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024


class UpdateControllerError(RuntimeError):
    pass


class PostBootHealthError(TransactionError):
    """Health verification failed after observing a different kernel boot."""


@dataclass(frozen=True, slots=True)
class LocalActivationOutcome:
    state: str
    previous_release_id: str | None = None


class ControllerStateStore:
    SCHEMA_VERSION = 1

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        ensure_real_directory(self.root, mode=0o700)
        _assert_root_private_directory(self.root, label="Controller state-katalog")
        self.path = self.root / "state.json"
        self._state = self._load()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "schema_version": ControllerStateStore.SCHEMA_VERSION,
            "deployment": None,
            "phase": "idle",
            "history_anchor": None,
            "previous_release_id": None,
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            value = load_secure_json(self.path, max_bytes=1024 * 1024, forbidden_mode_bits=0o077)
        except Exception as exc:
            raise UpdateControllerError("Controller state kunne ikke indlæses sikkert") from exc
        if value.get("schema_version") != self.SCHEMA_VERSION:
            raise UpdateControllerError("Controller state schema er ugyldig")
        if value.get("phase") not in {
            "idle", "observed", "staged", "activation_authorized",
            "activation_succeeded", "rolled_back", "recovery_failed",
        }:
            raise UpdateControllerError("Controller state phase er ugyldig")
        deployment = value.get("deployment")
        if deployment is not None:
            try:
                DeploymentSnapshot.from_state(deployment)
            except Exception as exc:
                raise UpdateControllerError("Controller deployment state er ugyldig") from exc
        anchor = value.get("history_anchor")
        if anchor is not None and (not isinstance(anchor, str) or len(anchor) != 64):
            raise UpdateControllerError("Controller history anchor er ugyldigt")
        return value

    def _save(self) -> None:
        atomic_write_json(self.path, self._state, mode=0o600)

    def reload(self) -> None:
        self._state = self._load()

    def cleanup_handoffs(self) -> None:
        handoff_root = self.root / "handoff"
        if not handoff_root.exists() and not handoff_root.is_symlink():
            return
        _assert_root_private_directory(handoff_root, label="Controller handoff-katalog")
        for path in handoff_root.iterdir():
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise UpdateControllerError("Controller handoff-katalog indeholder en usikker fil")
            if os.geteuid() == 0 and metadata.st_uid != 0:
                raise UpdateControllerError("Controller handoff-fil er ikke root-owned")
            path.unlink()
        fsync_directory(handoff_root)

    @property
    def phase(self) -> str:
        return str(self._state["phase"])

    @property
    def history_anchor(self) -> str | None:
        value = self._state.get("history_anchor")
        return str(value) if value else None

    @property
    def previous_release_id(self) -> str | None:
        value = str(self._state.get("previous_release_id") or "").strip()
        return value or None

    def bind(self, snapshot: DeploymentSnapshot) -> None:
        current = self._state.get("deployment")
        expected = snapshot.to_dict()
        if current == expected:
            return
        if current is not None and self.phase not in {
            "idle", "activation_succeeded", "rolled_back", "recovery_failed"
        }:
            raise UpdateControllerError("En anden privileged deployment er stadig uafsluttet lokalt")
        boundary = self._state.get("reboot_boundary")
        if boundary is not None and (not isinstance(boundary, dict)
                or (not boundary.get("observed_boot_id") and self.phase != "rolled_back")):
            raise UpdateControllerError("Tidligere deployment afventer boot-verifikation eller recovery")
        self.cleanup_handoffs()
        self._state = self._empty()
        self._state["deployment"] = expected
        self._state["phase"] = "observed"
        self._save()

    def clear(self) -> None:
        self.cleanup_handoffs()
        self._state = self._empty()
        self._save()

    @staticmethod
    def history_anchor_for(local_state: dict[str, Any]) -> str | None:
        history = list(local_state.get("history") or [])
        if not history:
            return None
        tail = history[-1]
        if not isinstance(tail, dict):
            raise UpdateControllerError("Lokal release-history er ugyldig")
        raw = json.dumps(tail, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def mark_staged(self) -> None:
        self._state["phase"] = "staged"
        self._state["history_anchor"] = None
        self._state["previous_release_id"] = None
        self._save()

    def mark_activation_authorized(self, local_state: dict[str, Any]) -> None:
        self._state["phase"] = "activation_authorized"
        self._state["history_anchor"] = self.history_anchor_for(local_state)
        self._state["previous_release_id"] = None
        self._save()

    def mark_outcome(self, outcome: LocalActivationOutcome) -> None:
        if outcome.state not in {"succeeded", "rolled_back", "recovery_failed"}:
            raise UpdateControllerError("Controller forsøgte at gemme et ugyldigt activation outcome")
        self._state["phase"] = {
            "succeeded": "activation_succeeded",
            "rolled_back": "rolled_back",
            "recovery_failed": "recovery_failed",
        }[outcome.state]
        self._state["previous_release_id"] = outcome.previous_release_id
        self._save()


class UpdateControllerTransport(UpdaterTransport):
    """Updater transport plus the one privileged orchestration gate.

    The gate itself remains backend-owned.  This client merely invokes the
    existing DPoP-authenticated staged -> activating endpoint before any local
    activation mutation is attempted.
    """

    def start_activation(
        self,
        access_token: str,
        *,
        deployment_id: str,
        event_id: str,
        occurred_at: str,
    ) -> dict[str, Any]:
        response = self._json_request(
            method="POST",
            path=f"/api/clientflow-update/deployments/{deployment_id}/activation-start",
            access_token=access_token,
            payload={"event_id": event_id, "occurred_at": occurred_at},
        )
        if not isinstance(response, dict):
            raise UpdaterTransportError("Activation-start respons mangler deployment")
        return response


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_root(layout: Layout) -> None:
    if layout.root == Path("/") and os.geteuid() != 0:
        raise UpdateControllerError("ClientFlow update-controller kræver root")


def _assert_root_private_directory(path: Path, *, label: str) -> None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o077:
        raise UpdateControllerError(f"{label} har usikker type eller rettigheder")
    if os.geteuid() == 0 and metadata.st_uid != 0:
        raise UpdateControllerError(f"{label} er ikke root-owned")


class ControllerLock:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.fd: int | None = None

    def __enter__(self):
        ensure_real_directory(self.root, mode=0o700)
        _assert_root_private_directory(self.root, label="Controller state-katalog")
        self.fd = os.open(
            self.root / "controller.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        metadata = os.fstat(self.fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            os.close(self.fd)
            self.fd = None
            raise UpdateControllerError("Controller lockfil har usikker type eller rettigheder")
        if os.geteuid() == 0 and metadata.st_uid != 0:
            os.close(self.fd)
            self.fd = None
            raise UpdateControllerError("Controller lockfil er ikke root-owned")
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_args):
        assert self.fd is not None
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
        self.fd = None


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_json_fd(descriptor: int, *, label: str) -> dict[str, Any]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
        raise UpdateControllerError(f"{label} har usikker type eller rettigheder")
    if metadata.st_size <= 0 or metadata.st_size > MAX_SOURCE_STATE_BYTES:
        raise UpdateControllerError(f"{label} har ugyldig størrelse")
    raw = os.read(descriptor, MAX_SOURCE_STATE_BYTES + 1)
    if len(raw) > MAX_SOURCE_STATE_BYTES:
        raise UpdateControllerError(f"{label} er for stor")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateControllerError(f"{label} er ugyldig JSON") from exc
    if not isinstance(value, dict):
        raise UpdateControllerError(f"{label} skal være et objekt")
    return value


def _open_source_artifact(source_state_root: Path, snapshot: DeploymentSnapshot) -> int:
    try:
        root_fd = os.open(source_state_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise UpdateControllerError("Updaterens state-katalog kunne ikke åbnes sikkert") from exc
    try:
        root_meta = os.fstat(root_fd)
        if not stat.S_ISDIR(root_meta.st_mode) or root_meta.st_mode & 0o077:
            raise UpdateControllerError("Updaterens state-katalog har usikre rettigheder")

        state_fd = os.open("state.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            state = _read_json_fd(state_fd, label="Updater state")
        finally:
            os.close(state_fd)

        if state.get("schema_version") != 1:
            raise UpdateControllerError("Updater state schema er ugyldig")
        if state.get("deployment") != snapshot.to_dict():
            raise UpdateControllerError("Updater state matcher ikke backendens immutable deployment snapshot")

        expected_filename = f"{snapshot.deployment_id}-{snapshot.bundle_sha256}.tar"
        expected_artifact = {
            "deployment_id": snapshot.deployment_id,
            "bundle_sha256": snapshot.bundle_sha256,
            "bundle_size": snapshot.bundle_size,
            "filename": expected_filename,
        }
        if state.get("artifact") != expected_artifact:
            raise UpdateControllerError("Updater artifact-state matcher ikke deployment snapshot")

        artifacts_fd = os.open("artifacts", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            artifacts_meta = os.fstat(artifacts_fd)
            if not stat.S_ISDIR(artifacts_meta.st_mode) or artifacts_meta.st_mode & 0o077:
                raise UpdateControllerError("Updaterens artifact-katalog har usikre rettigheder")
            artifact_fd = os.open(expected_filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=artifacts_fd)
        finally:
            os.close(artifacts_fd)
    except Exception:
        os.close(root_fd)
        raise
    os.close(root_fd)
    return artifact_fd


def _hash_regular_file(path: Path, *, expected_size: int) -> tuple[int, str]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            raise UpdateControllerError("Controller handoff har usikker type eller rettigheder")
        if os.geteuid() == 0 and metadata.st_uid != 0:
            raise UpdateControllerError("Controller handoff er ikke root-owned")
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, COPY_CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > expected_size:
                raise UpdateControllerError("Controller handoff overskrider deployment bundle_size")
            digest.update(chunk)
        return size, digest.hexdigest()
    finally:
        os.close(descriptor)


def _private_handoff_path(controller_state_root: Path, snapshot: DeploymentSnapshot) -> Path:
    return controller_state_root / "handoff" / f"{snapshot.deployment_id}-{snapshot.bundle_sha256}.tar"


def secure_ingest_verified_artifact(
    *,
    source_state_root: Path,
    controller_state_root: Path,
    snapshot: DeploymentSnapshot,
) -> Path:
    """Copy one verified updater artifact into a pinned root-owned private handoff.

    The source file is opened no-follow from the updater StateDirectory.  The
    file identity is checked before and after the copy, while size and SHA-256
    are calculated from that same open descriptor.  Privileged staging never
    reopens the mutable unprivileged pathname.
    """
    ensure_real_directory(controller_state_root, mode=0o700)
    _assert_root_private_directory(controller_state_root, label="Controller state-katalog")
    handoff_root = controller_state_root / "handoff"
    ensure_real_directory(handoff_root, mode=0o700)
    _assert_root_private_directory(handoff_root, label="Controller handoff-katalog")
    destination = _private_handoff_path(controller_state_root, snapshot)

    if destination.exists() or destination.is_symlink():
        try:
            size, digest = _hash_regular_file(destination, expected_size=snapshot.bundle_size)
        except (OSError, UpdateControllerError):
            destination.unlink(missing_ok=True)
        else:
            if size == snapshot.bundle_size and digest == snapshot.bundle_sha256:
                return destination
            destination.unlink(missing_ok=True)

    source_fd = _open_source_artifact(source_state_root, snapshot)
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=f".{snapshot.deployment_id}.",
        suffix=".handoff",
        dir=handoff_root,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(temporary_fd, 0o600)
        before = os.fstat(source_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_mode & 0o077
            or before.st_size != snapshot.bundle_size
        ):
            raise UpdateControllerError("Updater artifact har usikker type, rettigheder eller størrelse")
        digest = hashlib.sha256()
        copied = 0
        with os.fdopen(temporary_fd, "wb", closefd=True) as destination_handle:
            temporary_fd = -1
            while True:
                chunk = os.read(source_fd, COPY_CHUNK_BYTES)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > snapshot.bundle_size:
                    raise UpdateControllerError("Updater artifact overskrider deployment bundle_size")
                digest.update(chunk)
                destination_handle.write(chunk)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
        after = os.fstat(source_fd)
        if _identity(before) != _identity(after):
            raise UpdateControllerError("Updater artifact ændrede identitet under privileged ingest")
        if copied != snapshot.bundle_size or digest.hexdigest() != snapshot.bundle_sha256:
            raise UpdateControllerError("Updater artifact matcher ikke deployment SHA-256/size under ingest")
        os.replace(temporary, destination)
        fsync_directory(handoff_root)
        final_size, final_digest = _hash_regular_file(destination, expected_size=snapshot.bundle_size)
        if final_size != snapshot.bundle_size or final_digest != snapshot.bundle_sha256:
            destination.unlink(missing_ok=True)
            fsync_directory(handoff_root)
            raise UpdateControllerError("Root-owned handoff kunne ikke genverificeres efter atomic publication")
        return destination
    finally:
        if temporary_fd >= 0:
            os.close(temporary_fd)
        os.close(source_fd)
        temporary.unlink(missing_ok=True)


def _discard_handoff(path: Path) -> None:
    path.unlink(missing_ok=True)
    if path.parent.exists():
        fsync_directory(path.parent)


def _record_matches_snapshot(record: object, snapshot: DeploymentSnapshot) -> bool:
    if not isinstance(record, dict):
        return False
    try:
        release_sequence = int(record.get("release_sequence"))
        bundle_size = int(record.get("bundle_size"))
    except (TypeError, ValueError):
        return False
    return (
        str(record.get("version") or "") == snapshot.target_version
        and release_sequence == snapshot.target_release_sequence
        and str(record.get("bundle_sha256") or "") == snapshot.bundle_sha256
        and bundle_size == snapshot.bundle_size
        and str(record.get("release_approval_reference") or "") == snapshot.release_approval_reference
        and (str(record.get("release_candidate_sha256") or "") or None) == snapshot.release_candidate_sha256
        and (str(record.get("source_commit") or "") or None) == snapshot.source_commit
    )


def _manifest_matches_snapshot(layout: Layout, snapshot: DeploymentSnapshot, record: dict[str, Any]) -> bool:
    release_root = layout.releases / snapshot.target_release_id
    try:
        manifest = load_secure_json(
            release_root / "release-manifest.json",
            max_bytes=8 * 1024 * 1024,
            forbidden_mode_bits=0o022,
        )
    except Exception:
        return False
    approval = manifest.get("release_approval") or {}
    source = manifest.get("source") or {}
    try:
        release_sequence = int(manifest.get("release_sequence") or 0)
    except (TypeError, ValueError):
        return False
    digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return (
        str(manifest.get("release_id") or "") == snapshot.target_release_id
        and str(manifest.get("version") or "") == snapshot.target_version
        and release_sequence == snapshot.target_release_sequence
        and str(approval.get("reference") or "") == snapshot.release_approval_reference
        and (str(approval.get("candidate_sha256") or "") or None) == snapshot.release_candidate_sha256
        and (str(source.get("commit") or "") or None) == snapshot.source_commit
        and str(record.get("manifest_sha256") or "") == digest
    )


def _assert_target_controller_support(layout: Layout, snapshot: DeploymentSnapshot) -> None:
    release_root = layout.releases / snapshot.target_release_id
    required = (
        "client-runtime/systemd/clientflow-update-controller.service",
        "client-runtime/libexec/update-controller",
        "release/lib/clientflow_release/update_controller.py",
        "release/lib/clientflow_release/update_controller_entrypoint.py",
    )
    for relative in required:
        path = release_root / relative
        try:
            metadata = path.lstat()
        except FileNotFoundError as exc:
            raise UpdateControllerError(
                f"Target release mangler canonical update-controller support: {relative}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise UpdateControllerError(
                f"Target release har ugyldig update-controller support: {relative}"
            )

    # The target's unit will become the managed definition after activation.
    # A previous physical update failed because ProtectHome=yes concealed the
    # kiosk home from the privileged setfacl step in both activation/rollback.
    # Reject that incompatible target *before* backend activation authorization.
    controller_unit = release_root / required[0]
    try:
        text = controller_unit.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UpdateControllerError("Target controller unit kan ikke indlæses") from exc
    directives: dict[str, list[str]] = {}
    section = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        if section != "[Service]" or "=" not in line:
            continue
        name, value = line.split("=", 1)
        directives.setdefault(name, []).append(value.strip())
    if (
        directives.get("User") != ["root"]
        or directives.get("ProtectHome") != ["tmpfs"]
        or directives.get("BindPaths") != ["/home/clientflow-kiosk"]
        or "BindReadOnlyPaths" in directives
        or "InaccessiblePaths" in directives
        or "ReadOnlyPaths" in directives
    ):
        raise UpdateControllerError(
            "Target controller unit mangler den verificerede, afgrænsede kiosk-home sandkasse"
        )


def _assert_local_staged(layout: Layout, snapshot: DeploymentSnapshot, local_state: dict[str, Any]) -> None:
    installed = local_state.get("installed") or {}
    record = installed.get(snapshot.target_release_id)
    if not _record_matches_snapshot(record, snapshot):
        raise UpdateControllerError("Lokal staged release matcher ikke deployment snapshot")
    if not _manifest_matches_snapshot(layout, snapshot, record):
        raise UpdateControllerError("Lokal staged manifest/provenance matcher ikke deployment snapshot")
    _assert_target_controller_support(layout, snapshot)
    if local_state.get("staged_release_id") != snapshot.target_release_id:
        raise UpdateControllerError("Lokal release-state markerer ikke deployment target som staged")
    active = local_state.get("active_release_id")
    active_link = local_state.get("active_symlink_release_id")
    if active != active_link:
        intent = local_state.get("activation_intent")
        resumable = (
            isinstance(intent, dict)
            and intent.get("release_id") == snapshot.target_release_id
            and intent.get("release_approval_reference") == snapshot.release_approval_reference
            and intent.get("previous_release_id") == active
            and active_link == snapshot.target_release_id
        )
        if not resumable:
            raise UpdateControllerError("Lokal active release-state matcher ikke active-symlink")
    if active == snapshot.target_release_id:
        raise UpdateControllerError("Backend markerer staged, men target release er allerede aktiv lokalt")


def _event_digest(event: dict[str, Any]) -> str:
    raw = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _history_after_anchor(local_state: dict[str, Any], anchor: str | None) -> list[dict[str, Any]]:
    history = list(local_state.get("history") or [])
    if any(not isinstance(event, dict) for event in history):
        raise UpdateControllerError("Lokal release-history er ugyldig")
    if anchor is None:
        return history
    for index in range(len(history) - 1, -1, -1):
        if _event_digest(history[index]) == anchor:
            return history[index + 1 :]
    raise UpdateControllerError("Controllerens activation history-anchor findes ikke længere lokalt")


def _local_activation_outcome(
    layout: Layout,
    snapshot: DeploymentSnapshot,
    local_state: dict[str, Any],
    *,
    history_anchor: str | None,
) -> LocalActivationOutcome | None:
    installed = local_state.get("installed") or {}
    record = installed.get(snapshot.target_release_id)
    if _record_matches_snapshot(record, snapshot) and _manifest_matches_snapshot(layout, snapshot, record):
        active = local_state.get("active_release_id")
        active_link = local_state.get("active_symlink_release_id")
        if active == snapshot.target_release_id and active_link == snapshot.target_release_id:
            previous = str(local_state.get("previous_release_id") or "").strip() or None
            return LocalActivationOutcome("succeeded", previous)

    for event in reversed(_history_after_anchor(local_state, history_anchor)):
        if (
            event.get("event") == "automatic_rollback_completed"
            and event.get("failed_release_id") == snapshot.target_release_id
        ):
            restored = str(event.get("restored_release_id") or "").strip() or None
            return LocalActivationOutcome("rolled_back", restored)
        if (
            event.get("event") == "automatic_rollback_failed"
            and event.get("release_id") == snapshot.target_release_id
        ):
            return LocalActivationOutcome("recovery_failed", None)
    return None


class UpdateController:
    def __init__(
        self,
        config: UpdaterConfig,
        *,
        transport: UpdateControllerTransport | None = None,
        source_state_root: Path = Path("/var/lib/clientflow/updater"),
        controller_state_root: Path = Path("/var/lib/clientflow/update-controller"),
        layout: Layout = Layout(),
        stage_func: Callable[..., dict[str, Any]] = stage_bundle,
        activate_func: Callable[..., dict[str, Any]] = activate_release,
        status_func: Callable[..., dict[str, Any]] = status,
        recovery_func: Callable[..., dict[str, Any]] = recover_failed_update,
    ) -> None:
        self.config = config
        self.transport = transport or UpdateControllerTransport(config)
        self.source_state_root = Path(source_state_root)
        self.controller_state_root = Path(controller_state_root)
        self.controller_state = ControllerStateStore(self.controller_state_root)
        self.layout = layout
        self.stage_func = stage_func
        self.activate_func = activate_func
        self.status_func = status_func
        self.recovery_func = recovery_func

    @staticmethod
    def _deployment_state(deployment: dict[str, Any]) -> str:
        value = str(deployment.get("state") or "").strip()
        allowed = {
            "authorized", "downloading", "verified", "staged", "activating",
            "health_check", "succeeded", "failed", "cancelled", "rolling_back",
            "rolled_back", "recovery_failed",
        }
        if value not in allowed:
            raise UpdateControllerError(f"Backend returnerede ukendt deployment state {value!r}")
        return value

    def _bind_deployment(
        self,
        deployment: dict[str, Any],
        *,
        expected_snapshot: DeploymentSnapshot | None = None,
        expected_deployment_id: str | None = None,
    ) -> DeploymentSnapshot:
        try:
            client_id = int(deployment.get("client_id"))
        except (TypeError, ValueError) as exc:
            raise UpdateControllerError("Deployment client_id er ugyldig") from exc
        if client_id != self.config.client_id:
            raise UpdateControllerError("Deployment client_id matcher ikke update identity")
        snapshot = DeploymentSnapshot.from_backend(deployment)
        if expected_deployment_id is not None and snapshot.deployment_id != expected_deployment_id:
            raise UpdateControllerError("Backend skiftede aktiv deployment under privileged transaction")
        if expected_snapshot is not None and snapshot != expected_snapshot:
            raise UpdateControllerError("Backend ændrede et immutable deployment snapshot")
        return snapshot

    def _fresh_active(
        self,
        snapshot: DeploymentSnapshot,
    ) -> tuple[str, dict[str, Any] | None]:
        access_token = self.transport.issue_access_token()
        deployment = self.transport.get_active_deployment(access_token)
        if deployment is not None:
            self._bind_deployment(
                deployment,
                expected_snapshot=snapshot,
                expected_deployment_id=snapshot.deployment_id,
            )
        return access_token, deployment

    def _report_event(
        self,
        access_token: str,
        deployment: dict[str, Any],
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "deployment_id": str(deployment["id"]),
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "occurred_at": _now(),
            "payload": dict(payload or {}),
        }
        response = self.transport.report_event(access_token, event)
        updated = response.get("deployment")
        if not isinstance(updated, dict):
            raise UpdateControllerError("Deployment event-respons mangler deployment")
        return updated

    def _stage_verified(self, snapshot: DeploymentSnapshot) -> None:
        handoff = secure_ingest_verified_artifact(
            source_state_root=self.source_state_root,
            controller_state_root=self.controller_state_root,
            snapshot=snapshot,
        )
        try:
            self.stage_func(
                handoff,
                release_id=snapshot.target_release_id,
                expected_bundle_sha256=snapshot.bundle_sha256,
                install_mode=INSTALL_MODE_UPDATE,
                layout=self.layout,
            )
            local_state = self.status_func(self.layout)
            _assert_local_staged(self.layout, snapshot, local_state)
            self.controller_state.mark_staged()
        except Exception:
            raise
        else:
            _discard_handoff(handoff)

    def _report_staged(self, snapshot: DeploymentSnapshot) -> dict[str, Any] | None:
        access_token, deployment = self._fresh_active(snapshot)
        if deployment is None:
            return None
        state = self._deployment_state(deployment)
        if state == "verified":
            deployment = self._report_event(
                access_token,
                deployment,
                event_type="staged",
                payload={
                    "release_id": snapshot.target_release_id,
                    "bundle_sha256": snapshot.bundle_sha256,
                    "bundle_size": snapshot.bundle_size,
                },
            )
            self._bind_deployment(deployment, expected_snapshot=snapshot)
            return deployment
        if state in {"staged", "activating", "health_check", "rolling_back"}:
            return deployment
        return None

    def _authorize_activation(self, snapshot: DeploymentSnapshot) -> dict[str, Any] | None:
        local_state = self.status_func(self.layout)
        _assert_local_staged(self.layout, snapshot, local_state)
        if self.controller_state.phase == "observed":
            self.controller_state.mark_staged()
        access_token, deployment = self._fresh_active(snapshot)
        if deployment is None:
            return None
        state = self._deployment_state(deployment)
        if state == "staged":
            deployment = self.transport.start_activation(
                access_token,
                deployment_id=snapshot.deployment_id,
                event_id=str(uuid.uuid4()),
                occurred_at=_now(),
            )
            self._bind_deployment(deployment, expected_snapshot=snapshot)
            if self._deployment_state(deployment) != "activating":
                raise UpdateControllerError("Activation-start flyttede ikke deployment til activating")
            self.controller_state.mark_activation_authorized(local_state)
            return deployment
        if state == "activating":
            if self.controller_state.phase == "staged":
                # The backend gate may have committed immediately before a lost
                # response.  No local mutation happens before this durable mark.
                self.controller_state.mark_activation_authorized(local_state)
            elif self.controller_state.phase not in {
                "activation_authorized", "activation_succeeded", "rolled_back", "recovery_failed"
            }:
                raise UpdateControllerError(
                    "Backend er activating uden en lokal deployment-bound activation authorization"
                )
            return deployment
        if state in {"health_check", "rolling_back"}:
            if self.controller_state.phase not in {
                "activation_authorized", "activation_succeeded", "rolled_back", "recovery_failed"
            }:
                raise UpdateControllerError(
                    f"Backend er {state!r} uden en lokal deployment-bound activation transaction"
                )
            return deployment
        return None

    def _boot_id(self) -> str:
        value = self.layout.path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        try:
            if str(uuid.UUID(value)) != value:
                raise ValueError("noncanonical boot id")
        except ValueError as exc:
            raise UpdateControllerError("Kernel boot-ID er ugyldigt") from exc
        return value

    def _request_reboot(self) -> None:
        if self.layout.root != Path("/"):
            raise UpdateControllerError("Test-root kan ikke genstarte værten")
        subprocess.run(["/usr/bin/systemctl", "--no-block", "reboot"],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=True)

    def _await_post_activation_boot(self, snapshot: DeploymentSnapshot) -> bool:
        # Legacy controllers executing the first 1248 -> 1250 transition
        # cannot run this code before their own completion. That transition
        # separately requires a physical reboot and health acceptance.
        version = tuple(int(part) for part in snapshot.target_version.split("."))
        if version < (1, 4, 0) or snapshot.target_release_sequence < 1250:
            return True
        boot = self._boot_id()
        state = self.controller_state._state
        record = state.get("reboot_boundary")
        path = self.controller_state_root.parent / "release-status" / "state.json"

        def publish(phase):
            # For this particular boot boundary the marker also inhibits the
            # kiosk. A failure to establish it must not request a reboot.
            release_public_status.publish(path=path, deployment_id=snapshot.deployment_id,
                release_id=snapshot.target_release_id, phase=phase)

        if record is None:
            publish("rebooting")
            record = {"deployment_id": snapshot.deployment_id, "release_id": snapshot.target_release_id,
                      "requested_boot_id": boot, "observed_boot_id": None}
            state["reboot_boundary"] = record
            self.controller_state._save()  # durable at-most-once request before systemctl
            try:
                self._request_reboot()
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                publish("recovery_required")
                raise UpdateControllerError("Genstart kunne ikke bekræftes; kontrollér klienten manuelt") from exc
            return False
        if not isinstance(record, dict) or set(record) != {
            "deployment_id", "release_id", "requested_boot_id", "observed_boot_id"
        } or record["deployment_id"] != snapshot.deployment_id or record["release_id"] != snapshot.target_release_id:
            raise UpdateControllerError("Genstartsjournal matcher ikke deployment")
        try:
            previous = record["requested_boot_id"]
            observed = record["observed_boot_id"]
            if str(uuid.UUID(previous)) != previous or (observed is not None and
                    (str(uuid.UUID(observed)) != observed or observed == previous)):
                raise ValueError("invalid boot boundary")
        except (ValueError, TypeError, AttributeError) as exc:
            raise UpdateControllerError("Genstartsjournalens boot-ID er ugyldigt") from exc
        if boot == previous:
            # Never repeat a reboot request after a crash or lost response.
            return False
        publish("post_boot_check")
        try:
            _assert_no_temporary_media_override(self.layout)
            try:
                _health_check(self.layout, snapshot.target_release_id, timeout=120)
            except TransactionError as exc:
                if self._boot_id() != boot:
                    raise UpdateControllerError("Boot-ID ændret under helbredskontrol") from exc
                raise PostBootHealthError("ClientFlow helbredskontrol fejlede efter genstart") from exc
            if self._boot_id() != boot:
                raise UpdateControllerError("Boot-ID ændret under helbredskontrol")
        except Exception:
            publish("recovery_required")
            raise
        record["observed_boot_id"] = boot
        self.controller_state._save()
        return True

    def _report_success(self, snapshot: DeploymentSnapshot, outcome: LocalActivationOutcome) -> dict[str, Any]:
        access_token, deployment = self._fresh_active(snapshot)
        if deployment is None:
            return {"status": "backend_terminal", "deployment_id": snapshot.deployment_id}
        state = self._deployment_state(deployment)
        if state == "activating":
            deployment = self._report_event(
                access_token,
                deployment,
                event_type="health_check_started",
                payload={"release_id": snapshot.target_release_id},
            )
            self._bind_deployment(deployment, expected_snapshot=snapshot)
            state = self._deployment_state(deployment)
        if state == "health_check":
            try:
                boot_ok = self._await_post_activation_boot(snapshot)
            except PostBootHealthError:
                previous = outcome.previous_release_id
                if not previous or int(previous.rsplit("-seq-", 1)[1]) < 1250:
                    raise  # legacy baseline transition remains manual
                record = self.controller_state._state["reboot_boundary"]
                self.controller_state._state["post_boot_recovery"] = {
                    "deployment_id": snapshot.deployment_id, "release_id": snapshot.target_release_id,
                    "previous_release_id": previous, "failed_boot_id": self._boot_id(),
                    "requested_boot_id": record["requested_boot_id"], "phase": "pending",
                }
                self.controller_state._save()
                return self._recover_post_boot(snapshot)
            if not boot_ok:
                return {"status": "awaiting_reboot", "deployment_id": snapshot.deployment_id,
                        "release_id": snapshot.target_release_id}
            # Only the new boot gate introduces a potentially long health check.
            if self.controller_state._state.get("reboot_boundary") is not None:
                access_token, deployment = self._fresh_active(snapshot)
                if deployment is None or self._deployment_state(deployment) != "health_check":
                    raise UpdateControllerError("Backend health-check state er ændret før success")
            deployment = self._report_event(
                access_token,
                deployment,
                event_type="succeeded",
                payload={
                    "observed_release_id": snapshot.target_release_id,
                    "observed_release_sequence": snapshot.target_release_sequence,
                    "observed_previous_release_id": outcome.previous_release_id,
                },
            )
            self._bind_deployment(deployment, expected_snapshot=snapshot)
            return {
                "status": self._deployment_state(deployment),
                "deployment_id": snapshot.deployment_id,
                "release_id": snapshot.target_release_id,
            }
        raise UpdateControllerError(f"Lokal activation er grøn, men backend state er {state!r}")

    def _report_rollback(self, snapshot: DeploymentSnapshot, outcome: LocalActivationOutcome) -> dict[str, Any]:
        access_token, deployment = self._fresh_active(snapshot)
        if deployment is None:
            return {"status": "backend_terminal", "deployment_id": snapshot.deployment_id}
        state = self._deployment_state(deployment)
        if state in {"activating", "health_check"}:
            deployment = self._report_event(
                access_token,
                deployment,
                event_type="rollback_started",
                payload={
                    "failed_release_id": snapshot.target_release_id,
                    "restored_release_id": outcome.previous_release_id,
                },
            )
            self._bind_deployment(deployment, expected_snapshot=snapshot)
            state = self._deployment_state(deployment)
        if state == "rolling_back":
            deployment = self._report_event(
                access_token,
                deployment,
                event_type="rolled_back",
                payload={
                    "failed_release_id": snapshot.target_release_id,
                    "restored_release_id": outcome.previous_release_id,
                },
            )
            self._bind_deployment(deployment, expected_snapshot=snapshot)
            return {
                "status": self._deployment_state(deployment),
                "deployment_id": snapshot.deployment_id,
                "release_id": snapshot.target_release_id,
                "restored_release_id": outcome.previous_release_id,
            }
        raise UpdateControllerError(f"Lokal rollback er færdig, men backend state er {state!r}")

    def _report_recovery_failed(self, snapshot: DeploymentSnapshot) -> dict[str, Any]:
        access_token, deployment = self._fresh_active(snapshot)
        if deployment is None:
            return {"status": "backend_terminal", "deployment_id": snapshot.deployment_id}
        state = self._deployment_state(deployment)
        if state not in {"activating", "health_check", "rolling_back"}:
            raise UpdateControllerError(f"Recovery failure kan ikke rapporteres fra backend state {state!r}")
        deployment = self._report_event(
            access_token,
            deployment,
            event_type="recovery_failed",
            payload={
                "failure_code": "local_activation_recovery_failed",
                "failure_message": "Privileged ClientFlow activation kunne ikke gendannes lokalt",
            },
        )
        self._bind_deployment(deployment, expected_snapshot=snapshot)
        return {
            "status": self._deployment_state(deployment),
            "deployment_id": snapshot.deployment_id,
            "release_id": snapshot.target_release_id,
        }

    def _resume_failed_local_rollback(
        self, snapshot: DeploymentSnapshot, local_state: dict[str, Any],
    ) -> LocalActivationOutcome | None:
        """One bounded recovery attempt before reporting an active backend failure.

        Never recover a different release/deployment or re-activate the failed
        target. The transaction API takes the canonical release lock and checks
        the durable approval and failure event again before any mutation.
        """
        intent = local_state.get("activation_intent")
        if not isinstance(intent, dict) or (
            intent.get("release_id") != snapshot.target_release_id
            or intent.get("release_approval_reference") != snapshot.release_approval_reference
        ):
            return None
        previous = intent.get("previous_release_id")
        if not isinstance(previous, str) or not previous:
            return None  # first activation follows its separate pending recovery
        try:
            self.recovery_func(
                expected_failed_release_id=snapshot.target_release_id,
                expected_release_approval_reference=snapshot.release_approval_reference,
                expected_previous_release_id=previous,
                layout=self.layout,
            )
        except TransactionError:
            return None  # preserve fail-closed terminal outcome and local evidence
        repaired = self.status_func(self.layout)
        outcome = _local_activation_outcome(
            self.layout, snapshot, repaired,
            history_anchor=self.controller_state.history_anchor,
        )
        if outcome is None or outcome.state != "rolled_back" or outcome.previous_release_id != previous:
            raise UpdateControllerError("Recovery returnerede uden eksakt rollback-outcome")
        return outcome

    def _post_boot_restored(self, snapshot: DeploymentSnapshot, previous: str) -> bool:
        local = self.status_func(self.layout)
        outcome = _local_activation_outcome(
            self.layout, snapshot, local, history_anchor=self.controller_state.history_anchor)
        return bool(outcome is not None and outcome.state == "rolled_back"
                    and outcome.previous_release_id == previous
                    and local.get("active_release_id") == previous
                    and local.get("active_symlink_release_id") == previous
                    and local.get("activation_intent") is None)

    def _recover_post_boot(self, snapshot: DeploymentSnapshot) -> dict[str, Any]:
        marker = self.controller_state._state.get("post_boot_recovery")
        boundary = self.controller_state._state.get("reboot_boundary")
        if (not isinstance(marker, dict) or not isinstance(boundary, dict)
                or set(marker) != {"deployment_id", "release_id", "previous_release_id",
                                   "failed_boot_id", "requested_boot_id", "phase"}
                or marker["deployment_id"] != snapshot.deployment_id
                or marker["release_id"] != snapshot.target_release_id
                or boundary.get("deployment_id") != snapshot.deployment_id
                or boundary.get("release_id") != snapshot.target_release_id
                or marker["requested_boot_id"] != boundary.get("requested_boot_id")
                or marker["failed_boot_id"] == marker["requested_boot_id"]
                or marker["phase"] not in {"pending", "failed"}):
            raise UpdateControllerError("Post-boot recoveryjournal matcher ikke deployment")
        previous = marker["previous_release_id"]
        # Re-prove the existing backend deployment before local mutation.
        _, deployment = self._fresh_active(snapshot)
        if deployment is None or self._deployment_state(deployment) not in {"health_check", "rolling_back"}:
            raise UpdateControllerError("Post-boot recovery mangler aktiv backendautorisation")
        if marker["phase"] == "pending" and not self._post_boot_restored(snapshot, previous):
            self._publish_advisory_release_status(snapshot, "rolling_back")
            try:
                prepare_post_boot_recovery(
                    expected_failed_release_id=snapshot.target_release_id,
                    expected_previous_release_id=previous,
                    expected_release_approval_reference=snapshot.release_approval_reference,
                    expected_bundle_sha256=snapshot.bundle_sha256,
                    deployment_id=snapshot.deployment_id,
                    requested_boot_id=marker["requested_boot_id"], failed_boot_id=marker["failed_boot_id"],
                    layout=self.layout,
                )
                self.recovery_func(
                    expected_failed_release_id=snapshot.target_release_id,
                    expected_previous_release_id=previous,
                    expected_release_approval_reference=snapshot.release_approval_reference,
                    layout=self.layout,
                )
            except Exception:
                # A lost response after a durable rollback must not become a
                # second attempt. Only the local commit proves restoration.
                if not self._post_boot_restored(snapshot, previous):
                    marker["phase"] = "failed"
                    self.controller_state._save()
        if self._post_boot_restored(snapshot, previous):
            outcome = LocalActivationOutcome("rolled_back", previous)
            self.controller_state.mark_outcome(outcome)
            return self._report_rollback(snapshot, outcome)
        marker["phase"] = "failed"
        self.controller_state._save()
        self.controller_state.mark_outcome(LocalActivationOutcome("recovery_failed"))
        self._publish_advisory_release_status(snapshot, "recovery_required")
        return self._report_recovery_failed(snapshot)

    def _activate_or_reconcile(self, snapshot: DeploymentSnapshot, backend_state: str) -> dict[str, Any]:
        if self.controller_state._state.get("post_boot_recovery") is not None:
            return self._recover_post_boot(snapshot)
        local_state = self.status_func(self.layout)
        phase = self.controller_state.phase

        if phase == "staged" and backend_state == "activating":
            # Recovery from a committed activation-start whose HTTP response was
            # lost before the local durable authorization marker was written.
            _assert_local_staged(self.layout, snapshot, local_state)
            self.controller_state.mark_activation_authorized(local_state)
            phase = self.controller_state.phase

        if phase == "activation_succeeded":
            outcome = LocalActivationOutcome("succeeded", self.controller_state.previous_release_id)
            observed = _local_activation_outcome(
                self.layout, snapshot, local_state, history_anchor=self.controller_state.history_anchor
            )
            if observed is None or observed.state != "succeeded":
                raise UpdateControllerError("Controller state siger success, men lokal release-state gør ikke")
            return self._report_success(snapshot, outcome)
        if phase == "rolled_back":
            return self._report_rollback(
                snapshot,
                LocalActivationOutcome("rolled_back", self.controller_state.previous_release_id),
            )
        if phase == "recovery_failed":
            outcome = self._resume_failed_local_rollback(snapshot, local_state)
            if outcome is not None:
                self.controller_state.mark_outcome(outcome)
                return self._report_rollback(snapshot, outcome)
            return self._report_recovery_failed(snapshot)
        if phase != "activation_authorized":
            raise UpdateControllerError(
                f"Backend er {backend_state!r}, men lokal controller phase er {phase!r}"
            )

        outcome = _local_activation_outcome(
            self.layout,
            snapshot,
            local_state,
            history_anchor=self.controller_state.history_anchor,
        )
        if outcome is not None:
            self.controller_state.mark_outcome(outcome)
            if outcome.state == "succeeded":
                return self._report_success(snapshot, outcome)
            if outcome.state == "rolled_back":
                return self._report_rollback(snapshot, outcome)
            if outcome.state == "recovery_failed":
                recovered = self._resume_failed_local_rollback(snapshot, local_state)
                if recovered is not None:
                    self.controller_state.mark_outcome(recovered)
                    return self._report_rollback(snapshot, recovered)
                return self._report_recovery_failed(snapshot)
            raise UpdateControllerError("Ukendt lokal activation outcome")

        if backend_state != "activating":
            raise UpdateControllerError(
                f"Backend er {backend_state!r}, men lokal privileged activation har intet auditerbart outcome"
            )
        _assert_local_staged(self.layout, snapshot, local_state)
        # Read-only public status is written ONLY after backend activation-start
        # and the durable local authorization mark; no change to txn authority.
        self._publish_advisory_release_status(snapshot, "activating")
        try:
            self.activate_func(
                snapshot.target_release_id,
                expected_release_approval_reference=snapshot.release_approval_reference,
                layout=self.layout,
                expected_update_deployment_id=snapshot.deployment_id,
            )
        except TransactionError as exc:
            recovered_state = self.status_func(self.layout)
            outcome = _local_activation_outcome(
                self.layout,
                snapshot,
                recovered_state,
                history_anchor=self.controller_state.history_anchor,
            )
            if outcome is None:
                raise UpdateControllerError(
                    "Lokal activation fejlede uden et entydigt deployment-bound recovery-resultat"
                ) from exc
            self.controller_state.mark_outcome(outcome)
            if outcome.state == "rolled_back":
                return self._report_rollback(snapshot, outcome)
            if outcome.state == "recovery_failed":
                recovered = self._resume_failed_local_rollback(snapshot, recovered_state)
                if recovered is not None:
                    self.controller_state.mark_outcome(recovered)
                    return self._report_rollback(snapshot, recovered)
                return self._report_recovery_failed(snapshot)
            if outcome.state == "succeeded":
                return self._report_success(snapshot, outcome)
            raise UpdateControllerError("Ukendt recovery outcome") from exc

        activated_state = self.status_func(self.layout)
        outcome = _local_activation_outcome(
            self.layout,
            snapshot,
            activated_state,
            history_anchor=self.controller_state.history_anchor,
        )
        if outcome is None or outcome.state != "succeeded":
            raise UpdateControllerError("Activation returnerede success uden et matchende lokalt release outcome")
        self.controller_state.mark_outcome(outcome)
        return self._report_success(snapshot, outcome)

    def _publish_advisory_release_status(self, snapshot: DeploymentSnapshot, phase: str) -> None:
        """Best-effort display ONLY; never grant permission or affect rollback.

        The root controller's real transaction journal and backend deployment
        remain the only authorities.  A display or filesystem problem cannot
        make the privileged activation/recovery transaction succeed or fail.
        """
        try:
            release_public_status.publish(
                path=self.controller_state_root.parent / "release-status" / "state.json",
                deployment_id=snapshot.deployment_id,
                release_id=snapshot.target_release_id,
                phase=phase,
            )
        except Exception as exc:  # a display failure must NEVER alter transaction outcome
            print(f"clientflow-update-controller: advisory release status unavailable ({type(exc).__name__})", file=sys.stderr)

    def _complete_advisory_release_status(self, result: dict[str, Any]) -> None:
        state = str(result.get("status") or "")
        if state == "idle":
            if self.controller_state.phase == "recovery_failed":
                return  # do not erase an unresolved recovery warning
            try:
                release_public_status.clear(
                    path=self.controller_state_root.parent / "release-status" / "state.json",
                )
            except Exception as exc:
                print(f"clientflow-update-controller: advisory release status cleanup unavailable ({type(exc).__name__})", file=sys.stderr)
            return
        deployment = result.get("deployment_id")
        release_id = result.get("release_id")
        if not deployment or not release_id:
            return
        try:
            snapshot = DeploymentSnapshot.from_state(self.controller_state._state["deployment"])
        except (TypeError, ValueError, KeyError):
            return
        if snapshot.deployment_id != deployment or snapshot.target_release_id != release_id:
            return
        # Only a committed controller success/rollback may become terminal
        # visually.  A backend status alone must NOT masquerade as health.
        if state == "succeeded" and self.controller_state.phase == "activation_succeeded":
            phase = "completed"
        elif state == "rolled_back" and self.controller_state.phase == "rolled_back":
            phase = "rolled_back"
        elif state == "recovery_failed" or self.controller_state.phase == "recovery_failed":
            phase = "recovery_required"
        elif state in {"rolling_back"}:
            phase = "rolling_back"
        elif state in {"health_check", "backend_terminal", "succeeded", "rolled_back"}:
            phase = "post_activation_check"
        elif state == "failed":
            phase = "recovery_required"
        elif state == "cancelled":
            phase = "recovery_required" if self.controller_state.phase == "activation_authorized" else "cancelled"
        elif state in {"waiting_for_verified_artifact", "local_staged_backend_inactive", "staged_backend_inactive"}:
            phase = "preparing" if state == "waiting_for_verified_artifact" else "staging"
        else:
            return
        self._publish_advisory_release_status(snapshot, phase)

    def _installation_lock_root(self) -> Path:
        # Test-root transactions must never touch the live host lock.
        return (install_coordinator.DEFAULT_ROOT if self.layout.root == Path('/')
                else self.layout.root / 'var/lib/clientflow/install-coordinator')

    def run_once(self) -> dict[str, Any]:
        _require_root(self.layout)
        with ControllerLock(self.controller_state_root):
            self.controller_state.reload()
            previous_phase = self.controller_state.phase
            previous_state = dict(getattr(self.controller_state, "_state", {}))
            result = self._run_locked()
            # A crash can occur after backend terminalization but before
            # releasing the shared lock. On the next idle poll, a previous
            # durable local outcome must STILL agree with release history.
            # Never infer success merely because the backend has no target.
            if result.get("status") == "idle" and previous_phase in {"activation_succeeded", "rolled_back"}:
                prior = previous_state.get("deployment")
                if isinstance(prior, dict):
                    snapshot = DeploymentSnapshot.from_state(prior)
                    observed = _local_activation_outcome(
                        self.layout, snapshot, self.status_func(self.layout),
                        history_anchor=previous_state.get("history_anchor"),
                    )
                    if (observed is not None and
                            observed.state == ("succeeded" if previous_phase == "activation_succeeded" else "rolled_back")):
                        install_coordinator.release(
                            owner="update_clientflow", operation_id=snapshot.deployment_id,
                            root=self._installation_lock_root(),
                        )
            # Only a proven local terminal outcome OR a locally untouched
            # cancelled deployment can relinquish cross-plane ownership.
            current = getattr(self.controller_state, "_state", {}).get("deployment")
            if isinstance(current, dict):
                operation = current.get("deployment_id")
                phase = self.controller_state.phase
                terminal = (
                    (result.get("status") == "succeeded" and phase == "activation_succeeded")
                    or (result.get("status") == "rolled_back" and phase == "rolled_back")
                    or (result.get("status") == "cancelled" and phase in {"observed", "staged"})
                )
                if terminal and isinstance(operation, str):
                    install_coordinator.release(owner="update_clientflow", operation_id=operation, root=self._installation_lock_root())
            try:
                # A backend with no active deployment is not proof that a
                # previously failed local recovery has been physically healed.
                if not (result.get("status") == "idle" and previous_phase == "recovery_failed"):
                    self._complete_advisory_release_status(result)
            except Exception as exc:  # never turn a green controller into a failure
                print(f"clientflow-update-controller: advisory status check unavailable ({type(exc).__name__})", file=sys.stderr)
            return result

    def _access_token_and_active_deployment(self) -> tuple[str, dict[str, Any] | None]:
        bootstrap = getattr(self.transport, "issue_access_token_with_active_deployment", None)
        if callable(bootstrap):
            access_token, included, deployment = bootstrap()
            if included:
                return access_token, deployment
            return access_token, self.transport.get_active_deployment(access_token)
        access_token = self.transport.issue_access_token()
        return access_token, self.transport.get_active_deployment(access_token)

    def _run_locked(self) -> dict[str, Any]:
        access_token, deployment = self._access_token_and_active_deployment()
        if deployment is None:
            boundary = self.controller_state._state.get("reboot_boundary")
            if boundary is not None and (not isinstance(boundary, dict) or not boundary.get("observed_boot_id")):
                marker = self.controller_state._state.get("post_boot_recovery")
                prior = self.controller_state._state.get("deployment")
                if not (self.controller_state.phase == "rolled_back" and isinstance(marker, dict)
                        and isinstance(prior, dict) and self._post_boot_restored(
                            DeploymentSnapshot.from_state(prior), marker.get("previous_release_id"))):
                    raise UpdateControllerError("Backend mangler aktiv deployment før verificeret genstart; behold recoveryjournal")
            if self.controller_state.phase != "idle":
                self.controller_state.clear()
            return {"status": "idle", "deployment_id": None, "release_id": None}
        snapshot = self._bind_deployment(deployment)
        self.controller_state.bind(snapshot)
        state = self._deployment_state(deployment)

        if state in {"authorized", "downloading"}:
            return {
                "status": "waiting_for_verified_artifact",
                "deployment_id": snapshot.deployment_id,
                "release_id": snapshot.target_release_id,
            }

        if state in {"verified", "staged", "activating", "health_check", "rolling_back"}:
            # Reserve BEFORE staging/activation and keep the binding across
            # controller restarts, rollback and uncertain recovery.
            install_coordinator.claim(owner="update_clientflow", operation_id=snapshot.deployment_id, root=self._installation_lock_root())

        if state == "verified":
            self._stage_verified(snapshot)
            deployment = self._report_staged(snapshot)
            if deployment is None:
                return {
                    "status": "local_staged_backend_inactive",
                    "deployment_id": snapshot.deployment_id,
                    "release_id": snapshot.target_release_id,
                }
            state = self._deployment_state(deployment)

        if state == "staged":
            deployment = self._authorize_activation(snapshot)
            if deployment is None:
                return {
                    "status": "staged_backend_inactive",
                    "deployment_id": snapshot.deployment_id,
                    "release_id": snapshot.target_release_id,
                }
            state = self._deployment_state(deployment)

        if state in {"activating", "health_check", "rolling_back"}:
            return self._activate_or_reconcile(snapshot, state)

        if state in {"succeeded", "failed", "cancelled", "rolled_back", "recovery_failed"}:
            return {
                "status": state,
                "deployment_id": snapshot.deployment_id,
                "release_id": snapshot.target_release_id,
            }

        raise UpdateControllerError(f"Privileged controller kan ikke fortsætte fra state {state!r}")
