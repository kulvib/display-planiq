"""63D-7 single-client, database-controlled 1246 pilot permission.

This is an independent, event-driven authorization boundary. It neither opens
fleet/fresh-install rollout nor consults Render flags as a grant. Strict
catalog, signed artifact and client identity are required together.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .clientflow_pilot_1246 import (
    APPROVAL_REFERENCE, APPROVED_BUNDLE_SHA256, APPROVED_BUNDLE_SIZE,
    CANDIDATE_SHA256, SOURCE_COMMIT, PILOT_CLIENT_ID, PILOT_RELEASE_ID,
    PILOT_FROM_VERSIONS, PILOT_FLAG, PILOT_ARM_FLAG, CONFLICTING_FLAGS,
    approval_lock,
)
from .clientflow_release_pilot_stage_1246 import validated_catalog_mode


class DatabasePilot1246Denied(ValueError):
    """No release order may be created from this invalid pilot intent."""


def require_database_pilot_1246(
    *, client_id: int, client_name: str, current_version: str,
    expected_current_version: str, ubuntu_version: str,
    release: Mapping[str, Any], artifact: Mapping[str, Any],
    catalog: dict[str, Any], reason: str,
    policy: Mapping[str, Any], expected_revision: int,
) -> None:
    """Pure strict business/safety policy; called *under* DB client/policy locks.

    The exact staged source is pinned by validated_catalog_mode; the signed
    store bytes are independently verified by deployment_release_snapshot.
    No environment value grants any update or selects the pilot device.
    """
    if validated_catalog_mode(active_catalog=catalog) != 'update_only_1246_pilot_catalog':
        raise DatabasePilot1246Denied('Det eksakte 1246-pilotkatalog er ikke aktivt')
    approval = approval_lock()
    if any(os.environ.get(name) for name in (PILOT_FLAG, PILOT_ARM_FLAG, *CONFLICTING_FLAGS)):
        raise DatabasePilot1246Denied('Historisk pilot-/fleet-flag er aktivt: blandede autoriteter afvises')
    if os.environ.get('CLIENTFLOW_FRESH_INSTALL_SUSPENDED') != '1':
        raise DatabasePilot1246Denied('Fresh-install skal fortsat være suspenderet')
    if (
        type(client_id) is not int or client_id != PILOT_CLIENT_ID or client_name != 'Viborg1'
        or not isinstance(current_version, str) or current_version not in PILOT_FROM_VERSIONS
        or expected_current_version != current_version
        or ubuntu_version != '26.04'
        or not isinstance(reason, str) or not 12 <= len(reason.strip()) <= 500
        or type(expected_revision) is not int or expected_revision < 1
    ):
        raise DatabasePilot1246Denied('Kun en eksplicit begrundet, uændret Viborg1/1244-1245 pilot er tilladt')
    if (
        type(policy.get('revision')) is not int
        or policy.get('revision') != expected_revision
        or policy.get('stable_release_id') != 'clientflow-1.3.44-seq-1245'
        or policy.get('stable_bundle_sha256') != '28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5'
        or any(policy.get(flag) is not False for flag in (
            'cutover_enabled', 'fleet_open', 'fresh_install_open'))
    ):
        raise DatabasePilot1246Denied('Releasepolitik/revision eller fleet/fresh-install låse er ændret')
    expected_release = {
        'release_id': PILOT_RELEASE_ID, 'revision': PILOT_RELEASE_ID,
        'version': '1.3.45', 'client_version': '1.3.45',
        'release_sequence': 1246, 'status': 'supported',
        'installable': False, 'update_allowed': True,
        'rollback_allowed': False, 'requires_explicit_downgrade': False,
        'install_modes': ['in_place_update'], 'requires_reboot': True,
        'min_current_version': '1.3.43', 'max_current_version': '1.3.44',
        'artifact_type': 'runtime_release',
    }
    if not isinstance(release, Mapping) or any(
        type(release.get(key)) is not type(value) or release.get(key) != value
        for key, value in expected_release.items()
    ):
        raise DatabasePilot1246Denied('Målrelease er ikke eksakt godkendt update-only 1246')
    expected_artifact = {
        'target_release_id': PILOT_RELEASE_ID,
        'bundle_sha256': APPROVED_BUNDLE_SHA256,
        'bundle_size': APPROVED_BUNDLE_SIZE,
        'release_approval_reference': APPROVAL_REFERENCE,
        'release_candidate_sha256': CANDIDATE_SHA256,
        'source_commit': SOURCE_COMMIT,
    }
    if not isinstance(artifact, Mapping) or any(
        type(artifact.get(key)) is not type(value) or artifact.get(key) != value
        for key, value in expected_artifact.items()
    ):
        raise DatabasePilot1246Denied('Publiceret 1246-bundle matcher ikke den godkendte SHA256-identitet')
    if (
        approval['release_id'] != artifact['target_release_id']
        or approval['approved_bundle_sha256'] != artifact['bundle_sha256']
        or approval['approved_bundle_size'] != artifact['bundle_size']
    ):
        raise DatabasePilot1246Denied('Kryptografisk godkendelseslås ændret')
