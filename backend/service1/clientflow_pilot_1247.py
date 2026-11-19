"""Exact GitHub-approved 1247 bytes. Reviewable staging; never deployment approval."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

PILOT_CLIENT_ID = 3
PILOT_RELEASE_ID = 'clientflow-1.3.46-seq-1247'
PILOT_TO_VERSION = '1.3.46'
PILOT_FROM_VERSIONS = frozenset({'1.3.45'})
SOURCE_COMMIT = '22a8a873899fe736018e8238f4b2ec4bb896f6a2'
CANDIDATE_SHA256 = 'd60d63ba8daf182efd97c8a28183ddbde8f258ce3429e3c3bfe31bcb00f9d258'
INSTALLER_SHA256 = 'e1f153643d34db81200bbb106069a89353fb918b9dce9435d10c2ce6aea4e864'
APPROVED_BUNDLE_SHA256 = '3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150'
APPROVED_BUNDLE_SIZE = 223692800
APPROVAL_REFERENCE = 'CF-1.3.46-1247-20261119-22a8a873-d60d63ba'
APPROVAL_RUN_ID = 44609878344
GITHUB_RELEASE_TAG = 'clientflow-1.3.46-1247-approved-transport'
APPROVAL_LOCK_PATH = Path(__file__).with_name('clientflow_pilot_1247_approval.json')

class ClientFlowPilot1247Denied(ValueError):
    pass


def approval_lock_1247() -> dict[str, Any]:
    expected = {
        'schema_version': 1, 'approved': True,
        'release_id': PILOT_RELEASE_ID,
        'source_commit': SOURCE_COMMIT, 'candidate_sha256': CANDIDATE_SHA256,
        'installer_sha256': INSTALLER_SHA256,
        'approved_bundle_sha256': APPROVED_BUNDLE_SHA256,
        'approved_bundle_size': APPROVED_BUNDLE_SIZE,
        'approval_reference': APPROVAL_REFERENCE,
        'approval_run_id': APPROVAL_RUN_ID,
        'github_release_tag': GITHUB_RELEASE_TAG,
    }
    try:
        if APPROVAL_LOCK_PATH.is_symlink() or APPROVAL_LOCK_PATH.stat().st_size > 4096:
            raise ValueError('unsafe_approval_source')
        actual = json.loads(APPROVAL_LOCK_PATH.read_text(encoding='utf-8'))
        if actual != expected:
            raise ValueError('approval_changed')
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise ClientFlowPilot1247Denied('Godkendelsen af præcis 1247 TAR kan ikke verificeres') from exc
    return actual
