"""Default-off, per-client authorization for already promoted stable releases.

This never promotes or publishes a release. A manually requested deployment is
allowed only for an explicit wave of client IDs and an exact approved bundle
SHA256. The ordinary superadmin, row-lock and published-bundle checks remain.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

from .clientflow_releases import ClientFlowCatalogError, compare_versions

ENABLED_FLAG = "CLIENTFLOW_STABLE_ROLLOUT_ENABLED"
RELEASE_FLAG = "CLIENTFLOW_STABLE_ROLLOUT_RELEASE_ID"
CLIENTS_FLAG = "CLIENTFLOW_STABLE_ROLLOUT_CLIENT_IDS"
BUNDLE_FLAG = "CLIENTFLOW_STABLE_ROLLOUT_BUNDLE_SHA256"
MAX_WAVE_CLIENTS = 25
FLEET_ACCEPTANCE_PATH = Path(__file__).with_name("clientflow_1245_fleet_acceptance.json")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDS = re.compile(r"[1-9][0-9]*(?:,[1-9][0-9]*)*\Z")


class ClientFlowStableRolloutDenied(ValueError):
    """A stable release rollout was not explicitly authorized for this client."""


def require_1245_physical_acceptance() -> None:
    """Reviewed physical-pilot gate for 1245 fleet rollout and fresh install.

    Read-only and fail closed. A release label, an env flag or successful CI
    alone cannot grant fleet/fresh-install authority before physical acceptance.
    """
    try:
        acceptance = json.loads(FLEET_ACCEPTANCE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ClientFlowStableRolloutDenied("1245 mangler fysisk pilotaccept") from exc
    if not isinstance(acceptance, dict) or type(acceptance.get("physical_pilot_accepted")) is not bool or acceptance != {
        "schema_version": 1,
        "release_id": "clientflow-1.3.44-seq-1245",
        "physical_pilot_accepted": True,
        "approved_bundle_sha256": "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5",
        "approval_reference": "CF-1.3.44-1245-20261114-0685710-ffe58332-R2",
        "source_commit": "06857104952ebb40bf1394c423c01332d28f8d5e",
    }:
        raise ClientFlowStableRolloutDenied("1245 kræver særskilt godkendt fysisk Viborg1-pilot")


def require_stable_rollout(
    *, client_id: int, current_version: str, release: dict[str, Any],
    catalog: dict[str, Any], reason: str | None,
    pre_first_activation_repair: bool, confirm_downgrade: bool,
    artifact: dict[str, Any] | None = None,
) -> None:
    """Check both before and after acquiring the per-client deployment lock."""
    if os.environ.get(ENABLED_FLAG) != "1":
        raise ClientFlowStableRolloutDenied("Stabil udrulning er ikke aktiveret")
    release_id = str(release.get("release_id") or "")
    if not re.fullmatch(r"clientflow-\d+\.\d+\.\d+-seq-[1-9][0-9]*", release_id):
        raise ClientFlowStableRolloutDenied("Ugyldig stabil releaseidentitet")
    if os.environ.get(RELEASE_FLAG) != release_id:
        raise ClientFlowStableRolloutDenied("Stabil udrulning er ikke autoriseret for denne release")
    raw_ids = os.environ.get(CLIENTS_FLAG, "")
    if _IDS.fullmatch(raw_ids) is None:
        raise ClientFlowStableRolloutDenied("Klientlisten skal være eksplicit uden wildcard")
    ids = [int(value) for value in raw_ids.split(",")]
    if len(ids) > MAX_WAVE_CLIENTS or len(ids) != len(set(ids)):
        raise ClientFlowStableRolloutDenied("Stabil udrulning kræver en unik, afgrænset klientbølge")
    if type(client_id) is not int or client_id not in ids:
        raise ClientFlowStableRolloutDenied("Klienten er ikke omfattet af den godkendte bølge")
    approved_sha = os.environ.get(BUNDLE_FLAG, "")
    if _SHA256.fullmatch(approved_sha) is None:
        raise ClientFlowStableRolloutDenied("Stabil udrulning kræver eksakt approved bundle SHA256")
    rows = catalog.get("releases")
    if (
        not isinstance(rows, list)
        or not rows
        or catalog.get("latest_stable") != catalog.get("default_install_version")
        or catalog.get("latest_stable") != release.get("version")
        or rows[-1].get("release_id") != release_id
        or release.get("status") != "stable"
        or release.get("installable") is not True
        or release.get("update_allowed") is not True
        or release.get("rollback_allowed") is not False
        or release.get("requires_explicit_downgrade") is not False
        or release.get("requires_reboot") is not True
        or release.get("install_modes") != ["fresh_install", "in_place_update"]
        or not isinstance(release.get("min_current_version"), str)
    ):
        raise ClientFlowStableRolloutDenied("Udrulning kræver promoveret, stabil nyeste release")
    if (
        not isinstance(current_version, str)
        or not current_version
        or pre_first_activation_repair
        or confirm_downgrade
        or not isinstance(reason, str)
        or len(reason.strip()) < 12
    ):
        raise ClientFlowStableRolloutDenied("Udrulning kræver opgradering og en begrundelse på mindst 12 tegn")
    try:
        if compare_versions(current_version, str(release["version"])) >= 0:
            raise ClientFlowStableRolloutDenied("Stabil udrulning tillader kun en nyere målversion")
    except ClientFlowCatalogError as exc:
        raise ClientFlowStableRolloutDenied("Klientens rapporterede version er ugyldig") from exc
    # The first 1245 stable wave must use the *same* exact approved R2 bytes
    # as the preceding single-device pilot. A new/stale store artifact, SHA,
    # candidate or approval reference cannot be authorized just by changing
    # an environment variable. Future releases retain the generic rollout rule.
    if release_id == "clientflow-1.3.44-seq-1245":
        require_1245_physical_acceptance()
        from .clientflow_pilot_1245 import (
            _approved_lock, ClientFlowPilot1245Denied,
            SOURCE_COMMIT, CANDIDATE_SHA256, PILOT_ARM_REFERENCE,
        )
        try:
            lock = _approved_lock()
        except ClientFlowPilot1245Denied as exc:
            raise ClientFlowStableRolloutDenied("1245 R2-godkendelseslåsen er ikke gyldig") from exc
        if (
            approved_sha != "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
            or lock["approved_bundle_sha256"] != approved_sha
            or lock["approved_bundle_size"] != 223610880
            or lock["approval_reference"] != PILOT_ARM_REFERENCE
            or lock["candidate_sha256"] != CANDIDATE_SHA256
            or lock["source_commit"] != SOURCE_COMMIT
        ):
            raise ClientFlowStableRolloutDenied("Stabil 1245 kræver eksakt godkendt R2-bundle")
        if artifact is not None and (
            artifact.get("bundle_size") != lock["approved_bundle_size"]
            or artifact.get("release_approval_reference") != lock["approval_reference"]
            or artifact.get("release_candidate_sha256") != lock["candidate_sha256"]
            or artifact.get("source_commit") != lock["source_commit"]
        ):
            raise ClientFlowStableRolloutDenied("Stabil 1245 kræver samme R2-proveniens som Viborg1-pilot")
    if artifact is not None:
        if (
            artifact.get("target_release_id") != release_id
            or artifact.get("bundle_sha256") != approved_sha
            or type(artifact.get("bundle_size")) is not int
            or artifact["bundle_size"] <= 0
            or not isinstance(artifact.get("release_approval_reference"), str)
            or not artifact["release_approval_reference"].strip()
            or _SHA256.fullmatch(str(artifact.get("release_candidate_sha256") or "")) is None
            or re.fullmatch(r"[0-9a-f]{40}", str(artifact.get("source_commit") or "")) is None
        ):
            raise ClientFlowStableRolloutDenied("Publiceret artifact matcher ikke den godkendte udrulningsbølge")
