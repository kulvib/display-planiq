"""63D-11 event-driven, single-use, single-client 1247 database pilot guard.

This function does not grant permission by itself. Caller holds client/control
DB locks and independently verifies the published TAR and online identity.
"""
from __future__ import annotations
import os
from collections.abc import Mapping
from typing import Any
from .clientflow_pilot_1247 import (
    PILOT_CLIENT_ID, PILOT_RELEASE_ID, PILOT_FROM_VERSIONS,
    APPROVED_BUNDLE_SHA256, APPROVED_BUNDLE_SIZE,
    APPROVAL_REFERENCE, CANDIDATE_SHA256, SOURCE_COMMIT, approval_lock_1247,
)
from .clientflow_release_pilot_stage_1247 import validated_catalog_mode_1247

class DatabasePilot1247Denied(ValueError):
    pass

# Historic env flags cannot be used to authorize a 1247 order, but any
# active legacy/fleet flag must fail closed instead of creating mixed authority.
CONFLICTING_FLAGS = (
    'CLIENTFLOW_1241_PILOT_CLIENT_ID', 'CLIENTFLOW_1242_PILOT_CLIENT_ID',
    'CLIENTFLOW_1243_PILOT_CLIENT_ID', 'CLIENTFLOW_1245_PILOT_CLIENT_ID',
    'CLIENTFLOW_1245_PILOT_ARM_REFERENCE', 'CLIENTFLOW_1246_PILOT_CLIENT_ID',
    'CLIENTFLOW_1246_PILOT_ARM_REFERENCE', 'CLIENTFLOW_STABLE_ROLLOUT_ENABLED',
)

def require_database_pilot_1247(*, client_id: int, client_name: str,
    current_version: str, expected_current_version: str, ubuntu_version: str,
    release: Mapping[str, Any], artifact: Mapping[str, Any], catalog: dict[str, Any],
    reason: str, policy: Mapping[str, Any], expected_revision: int) -> None:
    approved = approval_lock_1247()
    if validated_catalog_mode_1247(active_catalog=catalog) != 'update_only_1247_pilot_catalog':
        raise DatabasePilot1247Denied('1247-kataloget er ikke godkendt og aktivt')
    if os.environ.get('CLIENTFLOW_FRESH_INSTALL_SUSPENDED') != '1':
        raise DatabasePilot1247Denied('Nyinstallationer skal fortsat være suspenderet')
    if any(os.environ.get(name) for name in CONFLICTING_FLAGS):
        raise DatabasePilot1247Denied('Konflikt med ældre pilot-/fleet-flags')
    if (type(client_id) is not int or client_id != PILOT_CLIENT_ID
            or client_name != 'Viborg1' or current_version not in PILOT_FROM_VERSIONS
            or expected_current_version != current_version or ubuntu_version != '26.04'
            or not isinstance(reason, str) or not 12 <= len(reason.strip()) <= 500
            or type(expected_revision) is not int or expected_revision < 1):
        raise DatabasePilot1247Denied('Kun frisk Viborg1/1246→1247-pilot kan autoriseres')
    if (type(policy.get('revision')) is not int
        or policy.get('revision') != expected_revision
        or policy.get('stable_release_id') != 'clientflow-1.3.44-seq-1245'
        or policy.get('stable_bundle_sha256') != '28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5'
        or any(policy.get(flag) is not False for flag in
               ('cutover_enabled', 'fleet_open', 'fresh_install_open'))):
        raise DatabasePilot1247Denied('Fælles release-/fleet-politik blev ændret')
    expected_release = {
        'release_id': PILOT_RELEASE_ID, 'revision': PILOT_RELEASE_ID,
        'version': '1.3.46', 'client_version': '1.3.46',
        'release_sequence': 1247, 'status': 'supported',
        'installable': False, 'update_allowed': True,
        'rollback_allowed': False, 'requires_explicit_downgrade': False,
        'requires_reboot': True, 'install_modes': ['in_place_update'],
        'min_current_version': '1.3.45', 'max_current_version': '1.3.45',
        'artifact_type': 'runtime_release',
    }
    if not isinstance(release, Mapping) or any(
        type(release.get(k)) is not type(v) or release.get(k) != v
        for k,v in expected_release.items()
    ):
        raise DatabasePilot1247Denied('1247-target er ikke præcis godkendt update-only release')
    expected_artifact = {
        'target_release_id': PILOT_RELEASE_ID,
        'bundle_sha256': APPROVED_BUNDLE_SHA256,
        'bundle_size': APPROVED_BUNDLE_SIZE,
        'release_approval_reference': APPROVAL_REFERENCE,
        'release_candidate_sha256': CANDIDATE_SHA256,
        'source_commit': SOURCE_COMMIT,
    }
    if not isinstance(artifact, Mapping) or any(
        type(artifact.get(k)) is not type(v) or artifact.get(k) != v
        for k,v in expected_artifact.items()
    ):
        raise DatabasePilot1247Denied('Publiceret TAR matcher ikke 1247 approval byte-for-byte')
    if (approved['release_id'] != artifact['target_release_id']
            or approved['approved_bundle_sha256'] != artifact['bundle_sha256']
            or approved['approved_bundle_size'] != artifact['bundle_size']):
        raise DatabasePilot1247Denied('Releasegodkendelsen afviger fra target')
