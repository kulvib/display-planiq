"""Fail-closed, single-device authorization for the approved ClientFlow 1240 field pilot.

Only the backend can issue deployment authority. The signed ClientFlow bundle is
immutable; this policy cannot be bypassed by supplying version or digest fields
in a request. Remove this temporary policy only through a separately audited PR.
"""
from __future__ import annotations

import os
from typing import Any

PILOT_CLIENT_ID = 1
PILOT_FROM_VERSION = "1.3.38"
PILOT_TO_VERSION = "1.3.39"
PILOT_RELEASE_ID = "clientflow-1.3.39-seq-1240"
PILOT_RELEASE_SEQUENCE = 1240
PILOT_FLAG = "CLIENTFLOW_1240_PILOT_CLIENT_ID"
PILOT_APPROVED_BUNDLE_SHA256 = "40fb64e3e8e38686f4b03ee8f66afc81fe7a03247ed723d8a6ce636aebbcb798"
PILOT_APPROVED_BUNDLE_SIZE = 223498240
PILOT_SOURCE_COMMIT = "820e605d2e30f8dfea2914d81a1c6ee87053b334"
PILOT_CANDIDATE_SHA256 = "b083cb8e18e436e0b76cf66ac8cf1daee678dcdb9fb32b0760291d0944f9869a"
PILOT_APPROVAL_REFERENCE = (
    "clientflow-1.3.39-seq-1240/"
    "b083cb8e18e436e0b76cf66ac8cf1daee678dcdb9fb32b0760291d0944f9869a"
)


class ClientFlowPilotDenied(ValueError):
    """A deployment does not satisfy the explicitly approved single-client pilot."""


def require_pilot_1240(
    *,
    client_id: int,
    current_version: str,
    release: dict[str, Any],
    reason: str | None,
    pre_first_activation_repair: bool,
    confirm_downgrade: bool,
    artifact: dict[str, Any] | None = None,
) -> None:
    """Deny by default, and constrain client, predecessor, destination and bytes.

    The switch is deliberately not a generic allowlist: a typo, another ID, or
    an accidentally configured fleet value must not authorize any client.
    """
    if os.environ.get(PILOT_FLAG) != "1":
        raise ClientFlowPilotDenied("ClientFlow 1240-piloten er ikke aktiveret i backend")
    if type(client_id) is not int or client_id != PILOT_CLIENT_ID:
        raise ClientFlowPilotDenied("ClientFlow 1240 er kun autoriseret for pilotklient 1")
    if (
        current_version != PILOT_FROM_VERSION
        or str(release.get("version")) != PILOT_TO_VERSION
        or str(release.get("release_id")) != PILOT_RELEASE_ID
        or release.get("release_sequence") != PILOT_RELEASE_SEQUENCE
        or release.get("install_modes") != ["in_place_update"]
        or release.get("status") != "supported"
        or release.get("update_allowed") is not True
        or release.get("installable") is not False
        or release.get("rollback_allowed") is not False
        or release.get("min_current_version") != PILOT_FROM_VERSION
        or release.get("max_current_version") != PILOT_FROM_VERSION
    ):
        raise ClientFlowPilotDenied("ClientFlow-piloten kræver præcis 1.3.38 → 1.3.39")
    if pre_first_activation_repair or confirm_downgrade:
        raise ClientFlowPilotDenied("Pilotopdatering tillader hverken repair eller downgrade")
    if not str(reason or "").strip():
        raise ClientFlowPilotDenied("Pilotopdatering kræver en eksplicit begrundelse")
    if artifact is not None:
        expected = {
            "target_release_id": PILOT_RELEASE_ID,
            "bundle_sha256": PILOT_APPROVED_BUNDLE_SHA256,
            "bundle_size": PILOT_APPROVED_BUNDLE_SIZE,
            "release_approval_reference": PILOT_APPROVAL_REFERENCE,
            "release_candidate_sha256": PILOT_CANDIDATE_SHA256,
            "source_commit": PILOT_SOURCE_COMMIT,
        }
        if any(artifact.get(name) != value for name, value in expected.items()):
            raise ClientFlowPilotDenied("Pilotopdateringens publicerede artifact matcher ikke approval")
