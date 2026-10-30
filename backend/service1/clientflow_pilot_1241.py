"""Fail-closed, single-device authorization for the approved ClientFlow 1241 field pilot.

Only the backend can issue deployment authority. The signed ClientFlow bundle is
immutable; this policy cannot be bypassed by supplying version or digest fields
in a request. Remove this temporary policy only through a separately audited PR.
"""
from __future__ import annotations

import os

from typing import Any

PILOT_CLIENT_ID = 1
PILOT_FROM_VERSION = "1.3.38"
PILOT_TO_VERSION = "1.3.40"
PILOT_RELEASE_ID = "clientflow-1.3.40-seq-1241"
PILOT_RELEASE_SEQUENCE = 1241
PILOT_FLAG = "CLIENTFLOW_1241_PILOT_CLIENT_ID"
PILOT_APPROVED_BUNDLE_SHA256 = "b63211454c9cee0f24277c51f0d13d75099729e641d13f9ce4ed9ad696468783"
PILOT_APPROVED_BUNDLE_SIZE = 223518720
PILOT_SOURCE_COMMIT = "f4a25bcefba1c222bd3f908309ce2e94cbf5c4db"
PILOT_CANDIDATE_SHA256 = "c38442404905515dce0f06db2d69be68903f9ffeaf3522cfe968ff16e977419d"
PILOT_APPROVAL_REFERENCE = "CF-1.3.40-1241-20261021-f4a25bce"


class ClientFlowPilotDenied(ValueError):
    """A deployment does not satisfy the explicitly approved single-client pilot."""


def require_pilot_1241(
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
        raise ClientFlowPilotDenied("ClientFlow 1241-piloten er ikke aktiveret i backend")
    if os.environ.get("CLIENTFLOW_1242_PILOT_CLIENT_ID"):
        raise ClientFlowPilotDenied("1241-piloten må ikke være aktiv samtidig med 1242-piloten")
    if type(client_id) is not int or client_id != PILOT_CLIENT_ID:
        raise ClientFlowPilotDenied("ClientFlow 1241 er kun autoriseret for pilotklient 1")
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
        raise ClientFlowPilotDenied("ClientFlow-piloten kræver præcis 1.3.38 → 1.3.40")
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
