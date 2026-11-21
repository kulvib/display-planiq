"""Fail-closed single-client one-shot 1247->1248 DB pilot eligibility check.

No writes, flags to activate, client execution, or automatic permission.
The HTTP caller must hold its existing client/control row locks, verify
signed store bytes and obtain superadmin password reauthentication.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

from .clientflow_pilot_1248 import (
    PILOT_CLIENT_ID, PILOT_RELEASE_ID, PILOT_FROM_VERSIONS,
    APPROVED_BUNDLE_SHA256, APPROVED_BUNDLE_SIZE,
    APPROVAL_REFERENCE, CANDIDATE_SHA256, SOURCE_COMMIT,
    approval_lock_1248,
)
from .clientflow_release_pilot_stage_1248 import validated_catalog_mode_1248


class DatabasePilot1248Denied(ValueError):
    pass


CONFLICTING_FLAGS = (
    "CLIENTFLOW_1241_PILOT_CLIENT_ID", "CLIENTFLOW_1242_PILOT_CLIENT_ID",
    "CLIENTFLOW_1243_PILOT_CLIENT_ID", "CLIENTFLOW_1245_PILOT_CLIENT_ID",
    "CLIENTFLOW_1245_PILOT_ARM_REFERENCE", "CLIENTFLOW_1246_PILOT_CLIENT_ID",
    "CLIENTFLOW_1246_PILOT_ARM_REFERENCE", "CLIENTFLOW_1247_PILOT_CLIENT_ID",
    "CLIENTFLOW_1247_PILOT_ARM_REFERENCE", "CLIENTFLOW_STABLE_ROLLOUT_ENABLED",
)


def require_database_pilot_1248(
    *, client_id: int, client_name: str, current_version: str,
    expected_current_version: str, ubuntu_version: str,
    release: Mapping[str, Any], artifact: Mapping[str, Any],
    catalog: dict[str, Any], reason: str,
    policy: Mapping[str, Any], expected_revision: int,
) -> None:
    approved = approval_lock_1248()
    if validated_catalog_mode_1248(active_catalog=catalog) != "update_only_1248_pilot_catalog":
        raise DatabasePilot1248Denied("Exact 1248 pilot catalog is not active")
    if os.environ.get("CLIENTFLOW_FRESH_INSTALL_SUSPENDED") != "1":
        raise DatabasePilot1248Denied("Fresh installation must remain suspended")
    if any(os.environ.get(name) for name in CONFLICTING_FLAGS):
        raise DatabasePilot1248Denied("Conflicting legacy/fleet pilot authorization")
    if (
        type(client_id) is not int or client_id != PILOT_CLIENT_ID
        or client_name != "Viborg1" or current_version not in PILOT_FROM_VERSIONS
        or expected_current_version != current_version
        or ubuntu_version != "26.04"
        or not isinstance(reason, str) or not 12 <= len(reason.strip()) <= 500
        or type(expected_revision) is not int or expected_revision < 1
    ):
        raise DatabasePilot1248Denied("Only fresh Viborg1/1247->1248 evidence is accepted")
    if (
        type(policy.get("revision")) is not int or policy["revision"] != expected_revision
        or policy.get("stable_release_id") != "clientflow-1.3.44-seq-1245"
        or policy.get("stable_bundle_sha256") != "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
        or any(policy.get(flag) is not False for flag in
               ("cutover_enabled", "fleet_open", "fresh_install_open"))
    ):
        raise DatabasePilot1248Denied("Stable/fleet policy changed")
    expected_release = {
        "release_id": PILOT_RELEASE_ID, "revision": PILOT_RELEASE_ID,
        "version": "1.3.47", "client_version": "1.3.47",
        "release_sequence": 1248, "status": "supported",
        "installable": False, "update_allowed": True,
        "rollback_allowed": False, "requires_explicit_downgrade": False,
        "requires_reboot": True, "install_modes": ["in_place_update"],
        "min_current_version": "1.3.46", "max_current_version": "1.3.46",
        "artifact_type": "runtime_release",
    }
    if not isinstance(release, Mapping) or any(
        type(release.get(key)) is not type(value) or release.get(key) != value
        for key, value in expected_release.items()
    ):
        raise DatabasePilot1248Denied("1248 target is not exact update-only approval")
    expected_artifact = {
        "target_release_id": PILOT_RELEASE_ID,
        "bundle_sha256": APPROVED_BUNDLE_SHA256,
        "bundle_size": APPROVED_BUNDLE_SIZE,
        "release_approval_reference": APPROVAL_REFERENCE,
        "release_candidate_sha256": CANDIDATE_SHA256,
        "source_commit": SOURCE_COMMIT,
    }
    if not isinstance(artifact, Mapping) or any(
        type(artifact.get(key)) is not type(value) or artifact.get(key) != value
        for key, value in expected_artifact.items()
    ):
        raise DatabasePilot1248Denied("Published TAR identity differs from exact approved 1248")
    if (
        approved["release_id"] != artifact["target_release_id"]
        or approved["approved_bundle_sha256"] != artifact["bundle_sha256"]
        or approved["approved_bundle_size"] != artifact["bundle_size"]
    ):
        raise DatabasePilot1248Denied("Source approval and target mismatch")
