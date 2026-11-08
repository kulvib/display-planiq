"""Exact-byte, disabled-by-default authorization for the Viborg2 recovery pilot.

This guard is inert until a separately reviewed catalog promotion adds the
approved 1243 release, the exact immutable bundle exists in the Render store,
and the operator explicitly sets CLIENTFLOW_1243_PILOT_CLIENT_ID=2.
"""
from __future__ import annotations

import os
from typing import Any

PILOT_FLAG = "CLIENTFLOW_1243_PILOT_CLIENT_ID"
PILOT_CLIENT_ID = 2
PILOT_FROM_VERSION = "1.3.38"
PILOT_TO_VERSION = "1.3.42"
PILOT_RELEASE_ID = "clientflow-1.3.42-seq-1243"
PILOT_RELEASE_SEQUENCE = 1243
PILOT_APPROVED_BUNDLE_SHA256 = "ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914"
PILOT_APPROVED_BUNDLE_SIZE = 223610880
PILOT_CANDIDATE_SHA256 = "4e52cbfbaa844c2d835e5b57f625b5a64cb98346c428ee410aead02b7c67c88a"
PILOT_INSTALLER_SHA256 = "e23fefccb4c126fee82a807ce0ffe22ddc5051aa8b6b53ca1907161622e126f3"
PILOT_SOURCE_COMMIT = "b870cf8c3fa90286c6b4dccaae593eb8a0d57565"
PILOT_APPROVAL_REFERENCE = "CF-1.3.42-1243-VIBORG2-PILOT-20261107"
CONFLICTING_PILOT_FLAGS = (
    "CLIENTFLOW_1241_PILOT_CLIENT_ID", "CLIENTFLOW_1242_PILOT_CLIENT_ID",
)


class ClientFlowPilot1243Denied(ValueError):
    """Request does not match the explicitly authorized Viborg2 1243 update."""


def require_pilot_1243(
    *, client_id: int, current_version: str, release: dict[str, Any],
    reason: str | None, pre_first_activation_repair: bool,
    confirm_downgrade: bool, artifact: dict[str, Any] | None = None,
) -> None:
    # No wildcard, no alternative client IDs, no whitespace or leading zeroes.
    if os.environ.get(PILOT_FLAG) != str(PILOT_CLIENT_ID):
        raise ClientFlowPilot1243Denied("1243-piloten kræver eksakt CLIENTFLOW_1243_PILOT_CLIENT_ID=2")
    if any(os.environ.get(flag) for flag in CONFLICTING_PILOT_FLAGS):
        raise ClientFlowPilot1243Denied("1241/1242 pilotflag skal begge være deaktiverede")
    if type(client_id) is not int or client_id != PILOT_CLIENT_ID:
        raise ClientFlowPilot1243Denied("1243-piloten er kun autoriseret for Viborg2, backend klient-ID 2")
    if (
        current_version != PILOT_FROM_VERSION
        or release.get("version") != PILOT_TO_VERSION
        or release.get("release_id") != PILOT_RELEASE_ID
        or type(release.get("release_sequence")) is not int
        or release.get("release_sequence") != PILOT_RELEASE_SEQUENCE
        or release.get("install_modes") != ["in_place_update"]
        or release.get("status") != "supported"
        or release.get("installable") is not False
        or release.get("update_allowed") is not True
        or release.get("rollback_allowed") is not False
        or release.get("requires_explicit_downgrade") is not False
        or release.get("requires_reboot") is not True
        or release.get("min_current_version") != PILOT_FROM_VERSION
        or release.get("max_current_version") != PILOT_FROM_VERSION
    ):
        raise ClientFlowPilot1243Denied("1243-piloten kræver kun 1.3.38 → 1.3.42 in-place update")
    if pre_first_activation_repair or confirm_downgrade:
        raise ClientFlowPilot1243Denied("1243-piloten tillader ikke repair, downgrade eller manuel rollback")
    if not str(reason or "").strip():
        raise ClientFlowPilot1243Denied("1243-piloten kræver en konkret begrundelse")
    if artifact is not None:
        expected = {
            "target_release_id": PILOT_RELEASE_ID,
            "bundle_sha256": PILOT_APPROVED_BUNDLE_SHA256,
            "bundle_size": PILOT_APPROVED_BUNDLE_SIZE,
            "release_approval_reference": PILOT_APPROVAL_REFERENCE,
            "release_candidate_sha256": PILOT_CANDIDATE_SHA256,
            "source_commit": PILOT_SOURCE_COMMIT,
        }
        if any(artifact.get(key) != value for key, value in expected.items()):
            raise ClientFlowPilot1243Denied("1243-pilotens artifact matcher ikke godkendte SHA/size/source/approval")
