"""Root-only, durable, cross-plane installation coordinator (61B-2D).

A short flock serializes CAS changes to a persistent operation binding.  The
persistent binding survives service restart and power loss; an expired process
lock NEVER implies that a maintenance operation is complete.  This is not
release authorization, a reboot controller or an operator unlock command.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid

DEFAULT_ROOT = Path('/var/lib/clientflow/install-coordinator')
OWNER_KINDS = frozenset({'update_os', 'update_firmware', 'update_clientflow', 'fresh_install', 'preclaim_host'})


class InstallCoordinationError(RuntimeError):
    pass


def _trusted_directory(root: Path) -> None:
    if root == DEFAULT_ROOT and os.geteuid() != 0:
        raise InstallCoordinationError('installation_coordination_requires_root')
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    meta = root.lstat()
    if (not stat.S_ISDIR(meta.st_mode) or meta.st_mode & 0o077
            or meta.st_uid != os.geteuid()):
        raise InstallCoordinationError('installation_coordination_directory_untrusted')


def _trusted_file(fd: int) -> None:
    meta = os.fstat(fd)
    if (not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o077
            or meta.st_uid != os.geteuid() or meta.st_size > 4096):
        raise InstallCoordinationError('installation_coordination_file_untrusted')


def _load(root: Path) -> dict | None:
    try:
        fd = os.open(root / 'state.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InstallCoordinationError('installation_coordination_state_unreadable') from exc
    try:
        _trusted_file(fd)
        raw = os.read(fd, 4097)
    finally:
        os.close(fd)
    try:
        state = json.loads(raw.decode('utf-8'))
        if (not isinstance(state, dict) or set(state) != {'schema_version', 'owner', 'operation_id'}
                or state['schema_version'] != 1 or state['owner'] not in OWNER_KINDS
                or str(uuid.UUID(state['operation_id'])) != state['operation_id']):
            raise ValueError('invalid binding')
    except (ValueError, UnicodeError, TypeError, KeyError, AttributeError) as exc:
        raise InstallCoordinationError('installation_coordination_state_corrupt') from exc
    return state


def _save(root: Path, value: dict | None) -> None:
    path = root / 'state.json'
    if value is None:
        # Leave no dangling symlink or an unknown journal behind.
        if path.is_symlink():
            raise InstallCoordinationError('installation_coordination_state_untrusted')
        path.unlink(missing_ok=True)
    else:
        fd, temporary = tempfile.mkstemp(prefix='.coord-', dir=root)
        try:
            os.fchmod(fd, 0o600)
            data = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


@contextmanager
def _locked(root: Path):
    _trusted_directory(root)
    fd = os.open(root / 'coordinate.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        _trusted_file(fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _binding(owner: str, operation_id: str) -> dict:
    if owner not in OWNER_KINDS or not isinstance(operation_id, str):
        raise InstallCoordinationError('installation_coordination_invalid_binding')
    try:
        if str(uuid.UUID(operation_id)) != operation_id:
            raise ValueError('noncanonical UUID')
    except (ValueError, AttributeError) as exc:
        raise InstallCoordinationError('installation_coordination_invalid_binding') from exc
    return {'schema_version': 1, 'owner': owner, 'operation_id': operation_id}


def claim(*, owner: str, operation_id: str, root: Path = DEFAULT_ROOT) -> None:
    target = _binding(owner, operation_id)
    with _locked(root):
        current = _load(root)
        if current is not None and current != target:
            raise InstallCoordinationError('another_installation_active_or_in_doubt')
        if current is None:
            _save(root, target)


def release(*, owner: str, operation_id: str, root: Path = DEFAULT_ROOT) -> None:
    target = _binding(owner, operation_id)
    with _locked(root):
        current = _load(root)
        if current is None:
            return  # repeat of an ALREADY committed release
        if current != target:
            raise InstallCoordinationError('installation_coordination_binding_mismatch')
        _save(root, None)


def snapshot(*, root: Path = DEFAULT_ROOT) -> dict | None:
    with _locked(root):
        return _load(root)


# 61B-2I: host package upgrades happen before consuming a CF enrollment code.
# The operation ID is stable for the *exact approved bundle* on this host; an
# interrupted upgrade remains blocked until retried with that SAME source.
# The root-owned coordinator remains the authority, not a timeout or PID.
_PRECLAIM_NAMESPACE = uuid.UUID('b5f06294-a356-4ec6-91b2-1e6a461bafd4')


def _preclaim_operation_id(expected_bundle_sha256: str) -> str:
    if (not isinstance(expected_bundle_sha256, str) or len(expected_bundle_sha256) != 64
            or any(c not in '0123456789abcdef' for c in expected_bundle_sha256)):
        raise InstallCoordinationError('preclaim_requires_exact_bundle_sha256')
    return str(uuid.uuid5(_PRECLAIM_NAMESPACE, 'ubuntu26.04-preclaim:' + expected_bundle_sha256))


@contextmanager
def preclaim_host_guard(
    *,
    expected_bundle_sha256: str,
    root: Path = DEFAULT_ROOT,
    existing_install_id: str | None = None,
):
    """Serialize the real preclaim apt transaction with ALL install planes.

    A separate nonblocking process guard also refuses two simultaneous
    invocations with the SAME stable ID. The durable coordinator binding is
    intentionally retained on *any* failure or crash, and recoverable only
    by rerunning with the exact approved bundle. For a pending installation,
    the original fresh_install ID owns the reservation through activation.
    """
    operation_id = _preclaim_operation_id(expected_bundle_sha256)
    if existing_install_id is not None:
        _binding('fresh_install', existing_install_id)  # validate before filesystem mutation
    _trusted_directory(root)
    guard = os.open(root / 'preclaim-run.lock',
                    os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    held = False
    try:
        _trusted_file(guard)
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InstallCoordinationError('preclaim_host_already_running') from exc
        held = True
        if existing_install_id is None:
            claim(owner='preclaim_host', operation_id=operation_id, root=root)
        else:
            # An interrupted first installation is already a different owner
            # and MUST NOT be replaced by a new preclaim reservation.
            claim(owner='fresh_install', operation_id=existing_install_id, root=root)
        try:
            yield
        except BaseException:
            # No automatic unlock on ambiguous package/host failure.
            raise
        else:
            if existing_install_id is None:
                release(owner='preclaim_host', operation_id=operation_id, root=root)
    finally:
        if held:
            fcntl.flock(guard, fcntl.LOCK_UN)
        os.close(guard)
