"""Release cutover readiness, with no authority to deploy a client.

This is an explicit operator-facing diagnostic.  A READY source candidate,
reviewed plan, catalog entry or a successful CI run is NEVER a deployment
permission.  Only the existing separately reviewed deployment guards may
issue an authorized deployment; this module does no I/O or DB writes.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RELEASE_ID = re.compile(r"clientflow-(\d+\.\d+\.\d+)-seq-([1-9][0-9]*)\Z")


def _closed(label: str, reason: str) -> dict[str, Any]:
    return {"id": label, "ready": False, "reason": reason}


def _passed(label: str) -> dict[str, Any]:
    return {"id": label, "ready": True, "reason": None}


def planning_readiness(
    *,
    release_id: str,
    bundle_sha256: str,
    catalog: Mapping[str, Any],
    approval_bundle_sha256: str,
    control_revision: int,
    cutover_enabled: bool,
    fleet_open: bool,
    fresh_install_open: bool,
    physical_acceptance: bool,
) -> dict[str, Any]:
    """Safe status for the *current* pinned stable release.

    Only explicitly supplied facts are reported; no artifact/signature validity,
    live CI, local installer state, or physical acceptance is inferred.
    """
    releases = catalog.get("releases")
    match = _RELEASE_ID.fullmatch(release_id) if isinstance(release_id, str) else None
    catalog_match = bool(
        match
        and isinstance(releases, list)
        and len(releases) == 1
        and isinstance(releases[0], dict)
        and releases[0].get("release_id") == release_id
        and releases[0].get("status") == "stable"
        and releases[0].get("version") == match.group(1)
        and releases[0].get("release_sequence") == int(match.group(2))
        and catalog.get("latest_stable") == match.group(1)
        and catalog.get("default_install_version") == match.group(1)
        and _SHA.fullmatch(bundle_sha256 or "") is not None
        and bundle_sha256 == approval_bundle_sha256
        and type(control_revision) is int
        and control_revision >= 1
    )
    checks = [
        _passed("stable_catalog_binding") if catalog_match else
        _closed("stable_catalog_binding", "Katalog, releaseidentitet og godkendt bundling matcher ikke"),
        _passed("physical_pilot") if physical_acceptance is True else
        _closed("physical_pilot", "Fysisk pilotaccept er ikke dokumenteret"),
        _passed("database_cutover") if cutover_enabled is True else
        _closed("database_cutover", "Databasebaseret releaseautorisation er ikke aktiveret"),
        _passed("fleet") if fleet_open is True else
        _closed("fleet", "Udrulningsbølger er fortsat lukket"),
        _passed("fresh_install") if fresh_install_open is True else
        _closed("fresh_install", "Nyinstallation er fortsat lukket"),
        # Deliberately unknown rather than incorrectly implying that an API
        # status page can prove a fresh local signed candidate / recovery drill.
        _closed("reproducible_candidate", "Kræver separat, reproducerbar build og signeret godkendelse"),
        _closed("physical_recovery", "Kræver verificeret fysisk recovery og rollback på klient"),
    ]
    return {
        "schema_version": 1,
        "release_id": release_id,
        "policy_revision": control_revision,
        "deployment_authorized": False,
        "automatic_rollout_authorized": False,
        "checks": checks,
        "ready_for_fleet": False,
        "ready_for_fresh_install": False,
    }


def assess_future_db_wave(
    *,
    control: Mapping[str, Any],
    wave: Mapping[str, Any],
    target: Mapping[str, Any],
    release: Mapping[str, Any],
    artifact: Mapping[str, Any],
    client_id: int,
    current_version: str,
    active_status_credential: bool,
    physical_acceptance: Mapping[str, Any] | None,
    now: datetime,
) -> tuple[bool, str]:
    """Pure, fail-closed precondition evaluator for a future DB cutover.

    Do not call this as a deployment grant.  A future cutover must additionally
    wire the authoritative *locked* consumption transaction, fresh presence,
    artifact validation, and immutable deployment snapshot in one transaction.
    """
    if (control.get("cutover_enabled") is not True or control.get("fleet_open") is not True):
        return False, "cutover_or_fleet_hold"
    # An acceptance of a DIFFERENT release (or an unbound truthy boolean)
    # must never authorize this immutable bundle. This is only preflight;
    # production cutover additionally needs locked DB record verification.
    if not isinstance(physical_acceptance, Mapping) or (
        physical_acceptance.get("decision") != "accepted"
        or physical_acceptance.get("release_id") != control.get("stable_release_id")
        or physical_acceptance.get("bundle_sha256") != control.get("stable_bundle_sha256")
        or type(physical_acceptance.get("client_id")) is not int
        or physical_acceptance["client_id"] <= 0
        or type(physical_acceptance.get("actor_user_id")) is not int
        or physical_acceptance["actor_user_id"] <= 0
        or not isinstance(physical_acceptance.get("evidence"), dict)
        or physical_acceptance["evidence"].get("physical_pilot_verified") is not True
        or physical_acceptance["evidence"].get("recovery_verified") is not True
    ):
        return False, "missing_or_mismatched_physical_pilot"
    if (wave.get("kind") != "controlled" or wave.get("state") not in ("approved", "running")
            or not isinstance(wave.get("approved_at"), datetime)
            or type(wave.get("approved_by_user_id")) is not int
            or wave.get("approved_by_user_id", 0) <= 0):
        return False, "wave_not_approved"
    if target.get("state") != "approved" or target.get("consumed_deployment_id") is not None:
        return False, "target_not_approved_or_already_consumed"
    if type(client_id) is not int or client_id <= 0 or target.get("client_id") != client_id:
        return False, "client_binding_mismatch"
    if target.get("wave_id") != wave.get("id"):
        return False, "wave_binding_mismatch"
    if active_status_credential is not True or not isinstance(current_version, str):
        return False, "status_credential_not_current"
    if (not _RELEASE_ID.fullmatch(str(wave.get("release_id") or ""))
            or _SHA.fullmatch(str(wave.get("bundle_sha256") or "")) is None):
        return False, "invalid_wave_identity"
    if (
        wave.get("release_id") != control.get("stable_release_id")
        or wave.get("bundle_sha256") != control.get("stable_bundle_sha256")
        or release.get("release_id") != wave.get("release_id")
        or release.get("status") != "stable"
        or release.get("installable") is not True
        or release.get("update_allowed") is not True
        or release.get("rollback_allowed") is not False
        or artifact.get("target_release_id") != wave.get("release_id")
        or artifact.get("bundle_sha256") != wave.get("bundle_sha256")
        or type(artifact.get("bundle_size")) is not int
        or artifact["bundle_size"] <= 0
        or not artifact.get("release_approval_reference")
        or _SHA.fullmatch(str(artifact.get("release_candidate_sha256") or "")) is None
        or re.fullmatch(r"[0-9a-f]{40}", str(artifact.get("source_commit") or "")) is None
    ):
        return False, "artifact_or_release_binding_mismatch"
    if current_version != wave.get("source_version"):
        return False, "status_version_mismatch"
    try:
        from .clientflow_releases import compare_versions
        if compare_versions(current_version, str(release.get("version") or "")) >= 0:
            return False, "not_a_forward_update"
    except (ValueError, TypeError, RuntimeError):
        return False, "invalid_version"
    if not isinstance(now, datetime):
        return False, "invalid_clock"
    now_utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    for value in (wave.get("expires_at"), target.get("expires_at")):
        if not isinstance(value, datetime):
            return False, "invalid_expiry"
        expiry = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if expiry <= now_utc:
            return False, "expired"
    return True, "preconditions_only_not_deployment_authority"
