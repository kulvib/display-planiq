"""Fail-closed, exact-byte 1244 -> 1245 single-device pilot guard.

Source staging alone NEVER authorizes this pilot. The approval lock is checked
from a versioned repository file and ships approved only after dedicated source promotion.
The source-approved pilot still needs two absent-by-default operator flags,
a verified published artifact and an explicit superadmin order.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

PILOT_FLAG = "CLIENTFLOW_1245_PILOT_CLIENT_ID"
PILOT_ARM_FLAG = "CLIENTFLOW_1245_PILOT_ARM_REFERENCE"
PILOT_ARM_REFERENCE = "CF-1.3.44-1245-20261114-0685710-ffe58332-R2"
PILOT_CLIENT_ID = 3
PILOT_FROM_VERSION = "1.3.43"
PILOT_TO_VERSION = "1.3.44"
PILOT_RELEASE_ID = "clientflow-1.3.44-seq-1245"
PILOT_RELEASE_SEQUENCE = 1245
SOURCE_COMMIT = "06857104952ebb40bf1394c423c01332d28f8d5e"
CANDIDATE_SHA256 = "ffe58332c8e3b263e00f299e363dc95ecb9ac7e0176fd51888be98fecad9bd97"
INSTALLER_SHA256 = "fc843b6b37772996ecbfa67ff08a0e6f372443bf7d6104ca28d616855bc5737a"
APPROVAL_LOCK_PATH = Path(__file__).with_name("clientflow_pilot_1245_approval.json")
CONFLICTING_PILOT_FLAGS = (
    "CLIENTFLOW_1241_PILOT_CLIENT_ID",
    "CLIENTFLOW_1242_PILOT_CLIENT_ID",
    "CLIENTFLOW_1243_PILOT_CLIENT_ID",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_APPROVAL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:/@+-]{0,199}\Z")
_APPROVAL_KEYS = frozenset({
    "schema_version", "approved", "release_id", "source_commit",
    "candidate_sha256", "installer_sha256", "approved_bundle_sha256",
    "approved_bundle_size", "approval_reference",
})


class ClientFlowPilot1245Denied(ValueError):
    """1245 pilot authorization is absent, stale or mismatched."""


def _approved_lock() -> dict[str, Any]:
    """Read reviewed, immutable-byte binding; never trust env-provided SHA data."""
    try:
        approval = json.loads(APPROVAL_LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ClientFlowPilot1245Denied("1245-pilotens godkendelseslås mangler eller er ugyldig") from exc
    if not isinstance(approval, dict) or set(approval) != _APPROVAL_KEYS:
        raise ClientFlowPilot1245Denied("1245-pilotens godkendelseslås har forkert schema")
    if approval.get("approved") is not True or type(approval.get("schema_version")) is not int or approval["schema_version"] != 1:
        raise ClientFlowPilot1245Denied("1245 er endnu ikke særskilt godkendt til pilot")
    if (
        approval.get("approval_reference") != PILOT_ARM_REFERENCE
        or approval.get("release_id") != PILOT_RELEASE_ID
        or approval.get("source_commit") != SOURCE_COMMIT
        or approval.get("candidate_sha256") != CANDIDATE_SHA256
        or approval.get("installer_sha256") != INSTALLER_SHA256
        or not isinstance(approval.get("approved_bundle_sha256"), str)
        or _SHA256_RE.fullmatch(approval["approved_bundle_sha256"]) is None
        or type(approval.get("approved_bundle_size")) is not int
        or not 1 <= approval["approved_bundle_size"] <= 1024 * 1024 * 1024
        or not isinstance(approval.get("approval_reference"), str)
        or _APPROVAL_RE.fullmatch(approval["approval_reference"]) is None
    ):
        raise ClientFlowPilot1245Denied("1245-pilotens godkendelsesbytes er ikke entydigt låst")
    return approval


def require_pilot_1245(
    *, client_id: int, current_version: str, release: dict[str, Any],
    reason: str | None, pre_first_activation_repair: bool,
    confirm_downgrade: bool, artifact: dict[str, Any] | None = None,
) -> None:
    """Check before the DB lock and recheck immutable store bytes after it."""
    if os.environ.get(PILOT_FLAG) != str(PILOT_CLIENT_ID):
        raise ClientFlowPilot1245Denied("1245-piloten er ikke aktiveret for Viborg1")
    if os.environ.get(PILOT_ARM_FLAG) != PILOT_ARM_REFERENCE:
        raise ClientFlowPilot1245Denied("1245-pilotens særskilte operatøraktivering mangler")
    if any(os.environ.get(flag) for flag in CONFLICTING_PILOT_FLAGS):
        raise ClientFlowPilot1245Denied("Historiske 1241–1243-pilotflag skal være deaktiverede")
    if type(client_id) is not int or client_id != PILOT_CLIENT_ID:
        raise ClientFlowPilot1245Denied("1245-piloten er kun tilladt for backend klient-ID 3")
    if (
        current_version != PILOT_FROM_VERSION
        or release.get("version") != PILOT_TO_VERSION
        or release.get("release_id") != PILOT_RELEASE_ID
        or type(release.get("release_sequence")) is not int
        or release["release_sequence"] != PILOT_RELEASE_SEQUENCE
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
        raise ClientFlowPilot1245Denied("1245-piloten kræver eksakt 1244 → 1245 og kun in-place-opdatering")
    if pre_first_activation_repair or confirm_downgrade:
        raise ClientFlowPilot1245Denied("1245-piloten tillader ikke repair, downgrade eller manuel rollback")
    if not isinstance(reason, str) or len(reason.strip()) < 12:
        raise ClientFlowPilot1245Denied("1245-piloten kræver en administrativ begrundelse på mindst 12 tegn")
    approval = _approved_lock()
    if artifact is not None:
        expected = {
            "target_release_id": PILOT_RELEASE_ID,
            "bundle_sha256": approval["approved_bundle_sha256"],
            "bundle_size": approval["approved_bundle_size"],
            "release_approval_reference": approval["approval_reference"],
            "release_candidate_sha256": CANDIDATE_SHA256,
            "source_commit": SOURCE_COMMIT,
        }
        if any(artifact.get(key) != value for key, value in expected.items()):
            raise ClientFlowPilot1245Denied("1245-pilotens publicerede artifact matcher ikke godkendelseslåsen")
