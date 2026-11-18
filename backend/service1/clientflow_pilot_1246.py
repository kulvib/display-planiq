"""Exact-byte 1246 / Viborg1 pilot guard. No source/catalog/env auto-enables it.

The verified GitHub approval below is ARTIFACT approval, not physical pilot
acceptance, Render publication, or fleet authorization. This guard is invoked
both before and after the per-client lock; the after-lock call checks immutable
store bytes. Production's 1245 catalog remains unchanged in this phase.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PILOT_CLIENT_ID = 3
PILOT_FLAG = 'CLIENTFLOW_1246_PILOT_CLIENT_ID'
PILOT_ARM_FLAG = 'CLIENTFLOW_1246_PILOT_ARM_REFERENCE'
PILOT_RELEASE_ID = 'clientflow-1.3.45-seq-1246'
PILOT_FROM_VERSIONS = frozenset({'1.3.43', '1.3.44'})
PILOT_TO_VERSION = '1.3.45'
SOURCE_COMMIT = 'bc7adef9fec4f4f4bc8382a5a9d212b71b9a9085'
CANDIDATE_SHA256 = 'f36bcd0b9080b765838b2c2a3ae582a161346f23b3d0c0404683158cf55865e7'
INSTALLER_SHA256 = '7613a8d0fa2bf73a06ee3afb45d564d6831d4172c82f1dad336bc6e66049e488'
APPROVED_BUNDLE_SHA256 = 'e37de3250d58d313d57ad7bcbf59682cee342f2727c6ad5b188c8782342d4c78'
APPROVED_BUNDLE_SIZE = 223682560
APPROVAL_REFERENCE = 'CF-1.3.45-1246-20261118-bc7adef-f36bcd0b'
APPROVAL_LOCK_PATH = Path(__file__).with_name('clientflow_pilot_1246_approval.json')
CONFLICTING_FLAGS = (
    'CLIENTFLOW_1241_PILOT_CLIENT_ID', 'CLIENTFLOW_1242_PILOT_CLIENT_ID',
    'CLIENTFLOW_1243_PILOT_CLIENT_ID', 'CLIENTFLOW_1245_PILOT_CLIENT_ID',
    'CLIENTFLOW_1245_PILOT_ARM_REFERENCE', 'CLIENTFLOW_STABLE_ROLLOUT_ENABLED',
)


class ClientFlowPilot1246Denied(ValueError):
    """A staged 1246 pilot was not precisely authorized."""


def approval_lock() -> dict[str, Any]:
    """Read only a fully pinned, git-reviewed artifact approval lock."""
    expected = {
        'schema_version': 1, 'approved': True,
        'release_id': PILOT_RELEASE_ID, 'source_commit': SOURCE_COMMIT,
        'candidate_sha256': CANDIDATE_SHA256,
        'installer_sha256': INSTALLER_SHA256,
        'approved_bundle_sha256': APPROVED_BUNDLE_SHA256,
        'approved_bundle_size': APPROVED_BUNDLE_SIZE,
        'approval_reference': APPROVAL_REFERENCE,
    }
    try:
        if APPROVAL_LOCK_PATH.is_symlink() or APPROVAL_LOCK_PATH.stat().st_size > 4096:
            raise ValueError('unsafe_approval_file')
        actual = json.loads(APPROVAL_LOCK_PATH.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ClientFlowPilot1246Denied('1246 artifact-godkendelseslåsen mangler eller er ugyldig') from exc
    if not isinstance(actual, dict) or type(actual.get('schema_version')) is not int or actual != expected:
        raise ClientFlowPilot1246Denied('1246 artifactets eksakte source, reference og bytes er ikke låst')
    return actual


def require_pilot_1246(
    *, client_id: int, current_version: str, release: dict[str, Any],
    reason: str | None, pre_first_activation_repair: bool,
    confirm_downgrade: bool, artifact: dict[str, Any] | None = None,
) -> None:
    """Never grants fleet, automatic rollout, fresh-install or rollback rights."""
    approval = approval_lock()
    if (os.environ.get(PILOT_FLAG) != str(PILOT_CLIENT_ID)
            or os.environ.get(PILOT_ARM_FLAG) != APPROVAL_REFERENCE):
        raise ClientFlowPilot1246Denied('1246 kræver særskilt klientbundet pilotaktivering')
    if any(os.environ.get(name) for name in CONFLICTING_FLAGS):
        raise ClientFlowPilot1246Denied('Anden pilot eller stabil fleet-udrulning er stadig aktiveret')
    if type(client_id) is not int or client_id != PILOT_CLIENT_ID:
        raise ClientFlowPilot1246Denied('1246-piloten må kun benyttes på Viborg1 (klient 3)')
    if (
        not isinstance(current_version, str) or current_version not in PILOT_FROM_VERSIONS
        or not isinstance(release, dict)
        or release.get('version') != PILOT_TO_VERSION
        or release.get('client_version') != PILOT_TO_VERSION
        or release.get('release_id') != PILOT_RELEASE_ID
        or release.get('revision') != PILOT_RELEASE_ID
        or type(release.get('release_sequence')) is not int
        or release['release_sequence'] != 1246
        or release.get('status') != 'supported'
        or release.get('installable') is not False
        or release.get('update_allowed') is not True
        or release.get('rollback_allowed') is not False
        or release.get('requires_explicit_downgrade') is not False
        or release.get('requires_reboot') is not True
        or release.get('install_modes') != ['in_place_update']
        or release.get('min_current_version') != '1.3.43'
        or release.get('max_current_version') != '1.3.44'
        or release.get('artifact_type') != 'runtime_release'
    ):
        raise ClientFlowPilot1246Denied('1246-piloten kræver præcis signeret 1.3.45/1246 fra 1244 eller 1245')
    if (pre_first_activation_repair is not False or confirm_downgrade is not False
            or not isinstance(reason, str) or len(reason.strip()) < 12):
        raise ClientFlowPilot1246Denied('1246-piloten afviser repair/downgrade og kræver begrundelse')
    if artifact is not None:
        if not isinstance(artifact, dict) or any(artifact.get(key) != value for key, value in {
            'target_release_id': PILOT_RELEASE_ID,
            'bundle_sha256': approval['approved_bundle_sha256'],
            'bundle_size': approval['approved_bundle_size'],
            'release_approval_reference': approval['approval_reference'],
            'release_candidate_sha256': CANDIDATE_SHA256,
            'source_commit': SOURCE_COMMIT,
        }.items()):
            raise ClientFlowPilot1246Denied('1246-pilotens publicerede bytes matcher ikke GitHub-godkendelsen')
