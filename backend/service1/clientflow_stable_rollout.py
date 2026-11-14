"""Default-off, per-client authorization for already promoted stable releases.

This never promotes or publishes a release. A manually requested deployment is
allowed only for an explicit wave of client IDs and an exact approved bundle
SHA256. The ordinary superadmin, row-lock and published-bundle checks remain.
"""
from __future__ import annotations

import os
import re
from typing import Any

from .clientflow_releases import ClientFlowCatalogError, compare_versions

ENABLED_FLAG = "CLIENTFLOW_STABLE_ROLLOUT_ENABLED"
RELEASE_FLAG = "CLIENTFLOW_STABLE_ROLLOUT_RELEASE_ID"
CLIENTS_FLAG = "CLIENTFLOW_STABLE_ROLLOUT_CLIENT_IDS"
BUNDLE_FLAG = "CLIENTFLOW_STABLE_ROLLOUT_BUNDLE_SHA256"
MAX_WAVE_CLIENTS = 25
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDS = re.compile(r"[1-9][0-9]*(?:,[1-9][0-9]*)*\Z")


class ClientFlowStableRolloutDenied(ValueError):
    """A stable release rollout was not explicitly authorized for this client."""


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
