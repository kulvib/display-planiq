"""Advisory, sanitized release visibility from the root update controller.

The authoritative deployment, approval, rollback and health boundaries remain
in update_controller.py and transaction.py.  This file is NOT a lock, command,
approval, or source of success.  Its public marker has no credentials.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

from .filesystem import atomic_write_json, fsync_directory

DEFAULT_PATH = Path('/var/lib/clientflow/release-status/state.json')
PHASES = frozenset({
    'preparing', 'staging', 'activating', 'post_activation_check',
    'rolling_back', 'recovery_required', 'completed', 'rolled_back', 'cancelled',
})
_RELEASE = re.compile(r'clientflow-[0-9]+\.[0-9]+\.[0-9]+-seq-[0-9]+\Z')


class ReleasePublicStatusError(RuntimeError):
    pass


def _check_directory(path: Path) -> None:
    # Refuse to publish to a writable or symlinked parent.  In production the
    # controller is root; a custom temp directory is used only in isolated tests.
    if path == DEFAULT_PATH and os.geteuid() != 0:
        raise ReleasePublicStatusError('Release status-publicering kræver root')
    path.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
    info = path.parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022
            or (info.st_uid != 0 if os.geteuid() == 0 else info.st_uid != os.geteuid())):
        raise ReleasePublicStatusError('Ubetroet release-statuskatalog')
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022
                or (info.st_uid != 0 if os.geteuid() == 0 else info.st_uid != os.geteuid())):
            raise ReleasePublicStatusError('Ubetroet release-statusfil')


def _validated_binding(deployment_id: str, release_id: str) -> None:
    try:
        uuid.UUID(deployment_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ReleasePublicStatusError('Ugyldigt deployment-id') from exc
    if not isinstance(release_id, str) or not _RELEASE.fullmatch(release_id):
        raise ReleasePublicStatusError('Ugyldigt ClientFlow release-id')


def publish(*, path: Path = DEFAULT_PATH, deployment_id: str, release_id: str,
            phase: str) -> None:
    """Atomic root publication; no backend writes or privileged actions."""
    _validated_binding(deployment_id, release_id)
    if phase not in PHASES:
        raise ReleasePublicStatusError('Ugyldig visningsfase')
    _check_directory(path)
    old: dict = {}
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(old, dict):
                raise ValueError('not a mapping')
        except (OSError, ValueError, UnicodeError) as exc:
            raise ReleasePublicStatusError('Ugyldig eksisterende visningsjournal') from exc
    if (old.get('schema_version') == 1 and old.get('deployment_id') == deployment_id
            and old.get('target_release_id') == release_id and old.get('phase') == phase):
        return  # do not manufacture changes/Neon status writes on each poll
    revision = int(old.get('revision', 0)) if isinstance(old.get('revision', 0), int) else 0
    if revision < 0 or revision > 2**60:
        raise ReleasePublicStatusError('Ugyldig visningsrevision')
    now = time.time()
    atomic_write_json(path, {
        'schema_version': 1,
        'action': 'update_clientflow',
        'deployment_id': deployment_id,
        'target_release_id': release_id,
        'phase': phase,
        'revision': revision + 1,
        'updated_at': now,
    }, mode=0o644)


def clear(*, path: Path = DEFAULT_PATH) -> None:
    """Only after the backend has proved NO active deployment."""
    if not path.exists() and not path.is_symlink():
        return
    _check_directory(path)
    path.unlink()
    fsync_directory(path.parent)
