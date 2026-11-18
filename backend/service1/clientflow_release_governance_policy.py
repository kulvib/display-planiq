"""Pure 63D-3 governance decisions, deliberately incapable of deployment.

These validation functions do not import database, HTTP, release-authorization,
or updater modules. They are reusable by a future audited admin handler and
are *not* a deployment or physical-acceptance authority by themselves.
"""
from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Mapping, Sequence
from typing import Any
import re

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_VERSION = re.compile(r"\d+\.\d+\.\d+\Z")
_RELEASE = re.compile(r"clientflow-(\d+\.\d+\.\d+)-seq-([1-9][0-9]*)\Z")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{11,199}\Z")


class GovernanceDenied(ValueError):
    """No change may be committed after this outcome."""


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise GovernanceDenied("invalid_clock")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def require_revisions(*, control: Mapping[str, Any], wave: Mapping[str, Any],
                      control_revision: int, wave_revision: int,
                      release_id: str, bundle_sha256: str) -> None:
    if (type(control_revision) is not int or control_revision < 1
            or type(wave_revision) is not int or wave_revision < 1
            or type(control.get("revision")) is not int
            or type(wave.get("revision")) is not int
            or control["revision"] != control_revision
            or wave["revision"] != wave_revision):
        raise GovernanceDenied("optimistic_revision_mismatch")
    if (not isinstance(release_id, str) or not isinstance(bundle_sha256, str)
            or _SHA.fullmatch(bundle_sha256) is None
            or control.get("stable_release_id") != release_id
            or control.get("stable_bundle_sha256") != bundle_sha256
            or wave.get("release_id") != release_id
            or wave.get("bundle_sha256") != bundle_sha256):
        raise GovernanceDenied("release_binding_mismatch")


def require_approved_physical_evidence(*, acceptance: Mapping[str, Any] | None,
                                       release_id: str, bundle_sha256: str,
                                       now: datetime) -> None:
    if (not isinstance(acceptance, Mapping)
            or acceptance.get("decision") != "accepted"
            or acceptance.get("release_id") != release_id
            or acceptance.get("bundle_sha256") != bundle_sha256
            or type(acceptance.get("client_id")) is not int
            or acceptance["client_id"] <= 0
            or type(acceptance.get("actor_user_id")) is not int
            or acceptance["actor_user_id"] <= 0):
        raise GovernanceDenied("physical_acceptance_missing_or_mismatched")
    evidence = acceptance.get("evidence")
    if (not isinstance(evidence, Mapping)
            or evidence.get("physical_pilot_verified") is not True
            or evidence.get("recovery_verified") is not True
            or evidence.get("pilot_client_id") != acceptance["client_id"]
            or evidence.get("release_id") != release_id
            or evidence.get("bundle_sha256") != bundle_sha256
            or type(evidence.get("tested_by_user_id")) is not int
            or evidence["tested_by_user_id"] <= 0
            or evidence["tested_by_user_id"] == acceptance["actor_user_id"]
            or not isinstance(evidence.get("pilot_reference"), str)
            or _REF.fullmatch(evidence["pilot_reference"]) is None
            or not isinstance(evidence.get("recovery_reference"), str)
            or _REF.fullmatch(evidence["recovery_reference"]) is None):
        raise GovernanceDenied("physical_evidence_incomplete_or_not_independent")
    if utc(acceptance.get("created_at")) > utc(now):
        raise GovernanceDenied("physical_acceptance_in_future")


def physical_evidence_payload(*, client_id: int, release_id: str,
                              bundle_sha256: str, tested_by_user_id: int,
                              reviewer_user_id: int, observed_version: str,
                              pilot_reference: str, recovery_reference: str) -> dict[str, Any]:
    """Prepare bounded evidence; no logs, secrets or unrestricted operator text."""
    if (type(client_id) is not int or client_id <= 0
            or type(tested_by_user_id) is not int or tested_by_user_id <= 0
            or type(reviewer_user_id) is not int or reviewer_user_id <= 0
            or tested_by_user_id == reviewer_user_id
            or not isinstance(release_id, str) or not release_id
            or not isinstance(bundle_sha256, str) or _SHA.fullmatch(bundle_sha256) is None
            or not isinstance(observed_version, str) or _VERSION.fullmatch(observed_version) is None
            or _RELEASE.fullmatch(release_id) is None
            or _RELEASE.fullmatch(release_id).group(1) != observed_version):
        raise GovernanceDenied("physical_evidence_identity_invalid")
    if (not isinstance(pilot_reference, str) or _REF.fullmatch(pilot_reference) is None
            or not isinstance(recovery_reference, str) or _REF.fullmatch(recovery_reference) is None
            or pilot_reference == recovery_reference):
        raise GovernanceDenied("physical_evidence_reference_invalid")
    return {
        "physical_pilot_verified": True, "recovery_verified": True,
        "pilot_client_id": client_id, "release_id": release_id,
        "bundle_sha256": bundle_sha256, "tested_by_user_id": tested_by_user_id,
        "observed_version": observed_version,
        "pilot_reference": pilot_reference, "recovery_reference": recovery_reference,
    }


def require_wave_action(*, action: str, wave: Mapping[str, Any],
                        targets: Sequence[Mapping[str, Any]], now: datetime,
                        actor_id: int) -> None:
    """Check a wave under the caller's row locks; does not mutate it."""
    if (type(actor_id) is not int or actor_id <= 0
            or not isinstance(wave.get("id"), str)
            or not targets or len(targets) > 25
            or len({t.get("client_id") for t in targets}) != len(targets)
            or any(t.get("wave_id") != wave["id"] for t in targets)):
        raise GovernanceDenied("wave_targets_or_actor_invalid")
    if action == "approve":
        if (wave.get("kind") != "controlled" or len(targets) < 2
                or wave.get("state") != "draft"
                or type(wave.get("created_by_user_id")) is not int
                or wave["created_by_user_id"] == actor_id
                or wave.get("approved_at") is None
                or wave.get("approved_by_user_id") is None
                or any(t.get("state") != "draft" or t.get("consumed_deployment_id") is not None
                       for t in targets)):
            raise GovernanceDenied("reviewed_controlled_wave_required")
    elif action == "pause":
        if wave.get("state") not in ("approved", "running"):
            raise GovernanceDenied("wave_not_active")
    elif action == "resume":
        if (wave.get("state") != "paused" or wave.get("approved_at") is None
                or wave.get("approved_by_user_id") is None):
            raise GovernanceDenied("wave_not_resumable")
    elif action == "stop":
        if wave.get("state") not in ("draft", "approved", "running", "paused"):
            raise GovernanceDenied("wave_not_stoppable")
    elif action == "reconcile":
        if wave.get("state") not in ("running", "paused"):
            raise GovernanceDenied("wave_not_reconcilable")
    else:
        raise GovernanceDenied("unsupported_governance_action")
    if action not in ("stop", "reconcile"):
        if (not isinstance(wave.get("expires_at"), datetime)
                or utc(wave["expires_at"]) <= utc(now)
                or any(not isinstance(t.get("expires_at"), datetime)
                       or utc(t["expires_at"]) <= utc(now) for t in targets)):
            raise GovernanceDenied("wave_or_target_expired")
