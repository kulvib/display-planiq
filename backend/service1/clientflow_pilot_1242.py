"""Exact-identity, reserve-device-only 1.3.41/1242 pilot authority.

The published GitHub/Render bundle is immutable. This backend policy does not
alter its signature, release identity, catalog or client trust. Disabled unless
the operator explicitly configures one *non-Heidi1* backend client ID. There is
no automatic rollout, no manual rollback, no repair or downgrade bypass.
"""
from __future__ import annotations

import os
from typing import Any

PILOT_FLAG = "CLIENTFLOW_1242_PILOT_CLIENT_ID"
OLD_PILOT_FLAG = "CLIENTFLOW_1241_PILOT_CLIENT_ID"
PILOT_FROM_VERSION = "1.3.38"
PILOT_TO_VERSION = "1.3.41"
PILOT_RELEASE_ID = "clientflow-1.3.41-seq-1242"
PILOT_RELEASE_SEQUENCE = 1242
PILOT_APPROVED_BUNDLE_SHA256 = "5b6603f9169870e867d340a567df1194c57dfb254b306328c07f1366023aabce"
PILOT_APPROVED_BUNDLE_SIZE = 223610880
PILOT_CANDIDATE_SHA256 = "d240a32595d4d33f33bfbff39b071f2bb6fba3e98a281b8718b30c3b43ca8633"
PILOT_SOURCE_COMMIT = "33fb7bafa9cd37b8ab3bebb437c1e4d81a50460d"
PILOT_APPROVAL_REFERENCE = "CF-1.3.41-1242-PILOT-20261030"
HEIDI1_CLIENT_ID = 1


class ClientFlowPilot1242Denied(ValueError):
    """The request is outside the explicit single-client 1242 pilot."""


def _configured_pilot_client_id() -> int:
    raw = os.environ.get(PILOT_FLAG, "")
    # No implicit parsing/trim, no 0, no multi-value lists or permissive flags.
    # Canonical positive integers only, and never the remote-only Heidi1.
    if not raw or not raw.isascii() or not raw.isdecimal() or raw.startswith("0"):
        raise ClientFlowPilot1242Denied("ClientFlow 1242-piloten er ikke aktiveret for en entydig reserveklient")
    if len(raw) > 10:
        raise ClientFlowPilot1242Denied("ClientFlow 1242-pilotens klient-ID er ugyldigt")
    result = int(raw)
    if result <= HEIDI1_CLIENT_ID or result > 2147483647:
        raise ClientFlowPilot1242Denied("ClientFlow 1242-piloten må ikke bruge Heidi1 eller et ugyldigt klient-ID")
    return result


def require_pilot_1242(
    *, client_id: int, current_version: str, release: dict[str, Any],
    reason: str | None, pre_first_activation_repair: bool,
    confirm_downgrade: bool, artifact: dict[str, Any] | None = None,
) -> None:
    """Re-check identical immutable authorization before AND after the DB lock."""
    allowed_id = _configured_pilot_client_id()
    if os.environ.get(OLD_PILOT_FLAG) == "1":
        raise ClientFlowPilot1242Denied("1241-piloten skal være deaktiveret før 1242-piloten")
    if type(client_id) is not int or client_id != allowed_id:
        raise ClientFlowPilot1242Denied("ClientFlow 1242 er kun autoriseret for den udpegede reserveklient")
    if (
        current_version != PILOT_FROM_VERSION
        or str(release.get("version")) != PILOT_TO_VERSION
        or str(release.get("release_id")) != PILOT_RELEASE_ID
        or type(release.get("release_sequence")) is not int
        or release.get("release_sequence") != PILOT_RELEASE_SEQUENCE
        or release.get("install_modes") != ["in_place_update"]
        or release.get("status") != "supported"
        or release.get("update_allowed") is not True
        or release.get("installable") is not False
        or release.get("rollback_allowed") is not False
        or release.get("requires_explicit_downgrade") is not False
        or release.get("requires_reboot") is not True
        or release.get("min_current_version") != PILOT_FROM_VERSION
        or release.get("max_current_version") != PILOT_FROM_VERSION
    ):
        raise ClientFlowPilot1242Denied("1242-piloten kræver præcis 1.3.38 → 1.3.41 og opdatering alene")
    if pre_first_activation_repair or confirm_downgrade:
        raise ClientFlowPilot1242Denied("1242-piloten tillader hverken repair eller downgrade")
    if not str(reason or "").strip():
        raise ClientFlowPilot1242Denied("1242-piloten kræver en eksplicit begrundelse")
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
            raise ClientFlowPilot1242Denied("1242-pilotens artifact matcher ikke den godkendte release")
