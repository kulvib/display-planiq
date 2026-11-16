"""Unprivileged, read-only ClientFlow release visibility.

Only root-owned marker paths are trusted. A marker is NEVER authority to run,
start, stop, reboot, recover, or authorize a release.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import time
import uuid
from typing import Any

STATUS_DIR = Path('/var/lib/clientflow/release-status')
STATUS_PATH = STATUS_DIR / 'state.json'
PHASE_MESSAGES = {
    'preparing': 'ClientFlow-opdatering forberedes',
    'staging': 'Verificeret ClientFlow-release klargøres',
    'activating': 'ClientFlow-release aktiveres; kiosk kan være midlertidigt lukket',
    'post_activation_check': 'Kontrollerer ClientFlow efter aktivering',
    'rolling_back': 'Gendanner tidligere ClientFlow-release',
    'recovery_required': 'ClientFlow-opdatering kræver teknisk kontrol',
    'completed': 'ClientFlow-opdateringen er bekræftet gennemført',
    'rolled_back': 'Tidligere ClientFlow-release blev gendannet',
    'cancelled': 'ClientFlow-opdatering blev annulleret',
}
_RELEASE = re.compile(r'clientflow-[0-9]+\.[0-9]+\.[0-9]+-seq-[0-9]+\Z')
MAX_BYTES = 4096
STALE_SECONDS = 1800


class UntrustedReleaseStatus(RuntimeError):
    pass


def _trusted_data() -> dict[str, Any] | None:
    try:
        directory = STATUS_DIR.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 0
            or directory.st_mode & 0o022):
        raise UntrustedReleaseStatus('untrusted_release_status_directory')
    try:
        descriptor = os.open(STATUS_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise UntrustedReleaseStatus('release_status_unreadable') from exc
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022 or info.st_size > MAX_BYTES):
            raise UntrustedReleaseStatus('untrusted_release_status_file')
        raw = os.read(descriptor, MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise UntrustedReleaseStatus('release_status_oversize')
    finally:
        os.close(descriptor)
    try:
        data = json.loads(raw.decode('utf-8'))
        if (not isinstance(data, dict) or data.get('schema_version') != 1
                or data.get('action') != 'update_clientflow'
                or data.get('phase') not in PHASE_MESSAGES
                or not isinstance(data.get('revision'), int) or data['revision'] < 1
                or not isinstance(data.get('updated_at'), (int, float))
                or not 0 < data['updated_at'] < time.time() + 300
                or not isinstance(data.get('target_release_id'), str)
                or not _RELEASE.fullmatch(data['target_release_id'])):
            raise ValueError('invalid release-status schema')
        uuid.UUID(str(data.get('deployment_id') or ''))
        return data
    except (UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise UntrustedReleaseStatus('release_status_corrupt') from exc


def public_snapshot() -> dict[str, Any] | None:
    try:
        data = _trusted_data()
    except (OSError, UntrustedReleaseStatus):
        return {
            'schema_version': 1, 'action': 'update_clientflow',
            'phase': 'recovery_required', 'active': True,
            'message': PHASE_MESSAGES['recovery_required'],
        }
    if data is None:
        return None
    phase = data['phase']
    if phase not in {'completed', 'rolled_back', 'cancelled'} and time.time() - data['updated_at'] > STALE_SECONDS:
        return {
            'schema_version': 1, 'action': 'update_clientflow',
            'phase': 'recovery_required', 'active': True,
            'message': 'ClientFlow-opdateringsstatus er forældet; status afventer teknisk kontrol',
            'operation_id': data['deployment_id'],
            'target_release_id': data['target_release_id'],
            'revision': data['revision'], 'updated_at': data['updated_at'],
        }
    return {
        'schema_version': 1, 'action': 'update_clientflow',
        'phase': phase,
        'active': phase not in {'completed', 'rolled_back', 'cancelled'},
        'message': PHASE_MESSAGES[phase],
        'operation_id': data['deployment_id'],
        'target_release_id': data['target_release_id'],
        'revision': data['revision'], 'updated_at': data['updated_at'],
    }
