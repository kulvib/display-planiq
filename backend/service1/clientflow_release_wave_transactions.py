"""Staged DB-wave authorization transaction; NOT a live deployment entry point.

63D-2 prepares the *one-transaction* future cutover.  No route imports or calls
this module.  In particular no UI review, successful CI, candidate build or
physical-acceptance claim can invoke it on a production client.

The eventual caller MUST also enforce the existing independent release/pilot
approval before the client lock and again under it.  This module never writes
or commits a release-policy toggle, signs a bundle or creates a new permission.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Callable, Mapping

from sqlmodel import Session, select

from .client_domain_models import ClientDomainCredential, ClientDomainStatus
from .clientflow_deployments import create_authorized_deployment
from .clientflow_releases import deployment_release_snapshot, resolve_release
from .system_control import active_system_command
from .clientflow_release_admin_models import (
    ClientFlowPhysicalAcceptance, ClientFlowReleaseControl,
    ClientFlowRolloutTarget, ClientFlowRolloutWave,
)
from .clientflow_release_readiness import assess_future_db_wave
from .models import Client, User
from .system_control import lock_system_client

MAX_STATUS_AGE = timedelta(seconds=90)
MAX_CLOCK_SKEW = timedelta(seconds=5)


def _system_now() -> datetime:
    return datetime.now(timezone.utc)


class WaveTransactionDenied(ValueError):
    """No changes to wave or deployment may be committed on this outcome."""


@dataclass(frozen=True)
class LockedGrant:
    control_revision: int
    wave_id: str
    wave_revision: int
    target_id: str
    client_id: int
    release_id: str
    bundle_sha256: str
    physical_acceptance_id: str


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise WaveTransactionDenied("invalid_timestamp")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _record(row: Any) -> dict[str, Any]:
    return row.model_dump()


def _trusted_status_version(
    session: Session, *, client_id: int, now: datetime,
) -> tuple[str, bool]:
    rows = session.exec(
        select(ClientDomainStatus, ClientDomainCredential)
        .join(ClientDomainCredential, ClientDomainCredential.id == ClientDomainStatus.credential_id)
        .where(
            ClientDomainStatus.client_id == client_id,
            ClientDomainStatus.domain == "status",
            ClientDomainCredential.client_id == client_id,
            ClientDomainCredential.domain == "status",
            ClientDomainCredential.revoked_at.is_(None),
        )
        .with_for_update()
    ).all()
    if len(rows) != 1:
        raise WaveTransactionDenied("missing_active_status_credential")
    status, credential = rows[0]
    age = _utc(now) - _utc(status.reported_at)
    version = status.agent_version
    if (
        status.credential_id != credential.id
        or status.observed_state != "online"
        or age < timedelta(0) or age > MAX_STATUS_AGE
        or not isinstance(version, str)
        or not re.fullmatch(r"\d+\.\d+\.\d+", version)
    ):
        raise WaveTransactionDenied("stale_or_invalid_status_version")
    return version, True


def locked_wave_preconditions(
    session: Session, *, client_id: int, current_version: str,
    release: Mapping[str, Any], artifact: Mapping[str, Any],
    expected_policy_revision: int, expected_wave_revision: int,
    now: datetime,
) -> LockedGrant:
    """Read authoritative rows with a fixed client→policy→wave→target lock order.

    CALLER must remain in this same uncommitted transaction until after both
    create_authorized_deployment and consume_locked_wave.  This function does
    not acquire a grant from a draft, and never modifies permission state.
    """
    if type(client_id) is not int or client_id <= 0 or type(expected_policy_revision) is not int or expected_policy_revision < 1 or type(expected_wave_revision) is not int or expected_wave_revision < 1:
        raise WaveTransactionDenied("invalid_request")
    requested_clock = _utc(now)
    try:
        lock_system_client(session, client_id)
    except ValueError as exc:
        raise WaveTransactionDenied("client_not_found") from exc
    client = session.exec(select(Client).where(Client.id == client_id).with_for_update()).first()
    if client is None or client.status != "approved" or client.deleted_at is not None:
        raise WaveTransactionDenied("client_not_approved")
    if active_system_command(session, client_id) is not None:
        raise WaveTransactionDenied("system_command_active")
    control = session.exec(
        select(ClientFlowReleaseControl).where(ClientFlowReleaseControl.id == 1).with_for_update()
    ).first()
    if control is None or control.revision != expected_policy_revision:
        raise WaveTransactionDenied("policy_revision_mismatch")
    if control.cutover_enabled is not True or control.fleet_open is not True:
        raise WaveTransactionDenied("cutover_or_fleet_hold")
    # Select the future wave ID *without taking a target lock*. The existing
    # administration locks wave → target. Locking target first would permit a
    # deadlock between rollout pause/revoke and authorization.
    candidates = session.exec(
        select(ClientFlowRolloutTarget.id, ClientFlowRolloutTarget.wave_id)
        .where(ClientFlowRolloutTarget.client_id == client_id,
               ClientFlowRolloutTarget.state == "approved")
    ).all()
    if len(candidates) != 1:
        raise WaveTransactionDenied("no_unique_approved_target")
    target_id, wave_id = candidates[0]
    wave = session.exec(
        select(ClientFlowRolloutWave).where(ClientFlowRolloutWave.id == wave_id).with_for_update()
    ).first()
    if wave is None or wave.revision != expected_wave_revision:
        raise WaveTransactionDenied("wave_revision_mismatch")
    target = session.exec(
        select(ClientFlowRolloutTarget)
        .where(ClientFlowRolloutTarget.id == target_id).with_for_update()
    ).first()
    if (target is None or target.client_id != client_id or target.wave_id != wave_id
            or target.state != "approved" or target.consumed_deployment_id is not None):
        raise WaveTransactionDenied("target_changed_under_lock")
    # Request timestamps are only an input constraint. Re-read the wall clock
    # AFTER all authorization locks, so a blocked request cannot reuse a stale
    # not-yet-expired timestamp to bypass the wave TTL.
    clock = _utc(_system_now())
    if abs(clock - requested_clock) > MAX_CLOCK_SKEW:
        raise WaveTransactionDenied("stale_authorization_clock")
    physical = session.exec(
        select(ClientFlowPhysicalAcceptance)
        .where(ClientFlowPhysicalAcceptance.release_id == control.stable_release_id,
               ClientFlowPhysicalAcceptance.bundle_sha256 == control.stable_bundle_sha256)
        .order_by(ClientFlowPhysicalAcceptance.created_at.desc(), ClientFlowPhysicalAcceptance.id.desc())
        .with_for_update()
        .limit(2)
    ).all()
    # An ambiguous acceptance history cannot be inferred as authority.
    if len(physical) != 1:
        raise WaveTransactionDenied("missing_or_ambiguous_physical_acceptance")
    acceptance = physical[0]
    if acceptance.decision != "accepted" or _utc(acceptance.created_at) > clock:
        raise WaveTransactionDenied("physical_acceptance_not_current")
    version, active = _trusted_status_version(session, client_id=client_id, now=clock)
    if version != current_version:
        raise WaveTransactionDenied("reported_version_changed")
    allowed, reason = assess_future_db_wave(
        control=_record(control), wave=_record(wave), target=_record(target),
        release=release, artifact=artifact, client_id=client_id,
        current_version=version, active_status_credential=active,
        physical_acceptance=_record(acceptance), now=clock,
    )
    if not allowed:
        raise WaveTransactionDenied(reason)
    return LockedGrant(
        control_revision=control.revision, wave_id=wave.id,
        wave_revision=wave.revision, target_id=target.id, client_id=client_id,
        release_id=control.stable_release_id,
        bundle_sha256=control.stable_bundle_sha256,
        physical_acceptance_id=acceptance.id,
    )


def consume_locked_wave(
    session: Session, *, grant: LockedGrant, deployment: Any,
) -> None:
    """Consume approved target only after an immutable deployment was created.

    No commit; caller must commit both rows together.  Rollback leaves both
    unchanged.  All references were row-locked in locked_wave_preconditions.
    """
    target = session.get(ClientFlowRolloutTarget, grant.target_id)
    wave = session.get(ClientFlowRolloutWave, grant.wave_id)
    control = session.get(ClientFlowReleaseControl, 1)
    acceptance = session.get(ClientFlowPhysicalAcceptance, grant.physical_acceptance_id)
    if (
        target is None or wave is None or control is None or acceptance is None
        or acceptance.decision != "accepted"
        or acceptance.release_id != grant.release_id
        or acceptance.bundle_sha256 != grant.bundle_sha256
        or target.state != "approved" or target.consumed_deployment_id is not None
        or target.client_id != grant.client_id or target.wave_id != grant.wave_id
        or wave.state not in ("approved", "running")
        or wave.revision != grant.wave_revision
        or _utc(wave.expires_at) <= _utc(_system_now())
        or _utc(target.expires_at) <= _utc(_system_now())
        or control.revision != grant.control_revision
        or control.cutover_enabled is not True or control.fleet_open is not True
        or wave.release_id != grant.release_id or wave.bundle_sha256 != grant.bundle_sha256
        or getattr(deployment, "id", None) is None
        or getattr(deployment, "client_id", None) != grant.client_id
        or getattr(deployment, "target_release_id", None) != grant.release_id
        or getattr(deployment, "bundle_sha256", None) != grant.bundle_sha256
        or getattr(deployment, "state", None) != "authorized"
        or getattr(deployment, "allow_downgrade", None) is not False
    ):
        raise WaveTransactionDenied("deployment_consumption_binding_mismatch")
    target.consumed_deployment_id = deployment.id
    target.state = "consumed"
    wave.state = "running"
    wave.revision += 1
    session.add(target)
    session.add(wave)
    session.flush()


def create_staged_wave_deployment(
    session: Session, *, client_id: int, current_version: str,
    release: Mapping[str, Any], artifact: Mapping[str, Any],
    expected_policy_revision: int, expected_wave_revision: int,
    requested_by_user_id: int, reason: str, now: datetime,
    legacy_guard: Callable[[], None],
) -> Any:
    """Future integration helper, kept UNROUTED until after physical pilot.

    Legacy policy must independently pass *twice* (preliminary+inside lock in
    the eventual HTTP route).  This helper requires the locked recheck callback
    and uses the same session with no intermediate commit.
    """
    if not callable(legacy_guard) or type(requested_by_user_id) is not int or requested_by_user_id <= 0 or not isinstance(reason, str) or len(reason.strip()) < 12:
        raise WaveTransactionDenied("missing_existing_approval_or_actor")
    actor = session.get(User, requested_by_user_id)
    if actor is None or actor.is_active is not True or actor.is_superadmin is not True:
        raise WaveTransactionDenied("actor_is_not_active_superadmin")
    # The frontend is NOT artifact authority. Read and verify immutable published
    # bytes through the existing backend verifier, and match the canonical catalog.
    try:
        canonical = resolve_release(str(release.get("version") or ""))
        if any(canonical.get(k) != release.get(k) for k in (
            "release_id", "version", "release_sequence", "status",
            "installable", "update_allowed", "rollback_allowed",
        )):
            raise WaveTransactionDenied("noncanonical_release_metadata")
        verified = deployment_release_snapshot(canonical)
        required = ("target_release_id", "bundle_sha256", "bundle_size",
                    "release_approval_reference", "release_candidate_sha256", "source_commit")
        if any(verified.get(k) != artifact.get(k) for k in required):
            raise WaveTransactionDenied("published_artifact_changed")
    except WaveTransactionDenied:
        raise
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise WaveTransactionDenied("published_release_not_verified") from exc
    grant = locked_wave_preconditions(
        session, client_id=client_id, current_version=current_version,
        release=release, artifact=artifact,
        expected_policy_revision=expected_policy_revision,
        expected_wave_revision=expected_wave_revision, now=now,
    )
    legacy_guard()  # mandatory OLD gate under client lock, without side effects
    result = create_authorized_deployment(
        session, client_id=client_id, requested_by_user_id=requested_by_user_id,
        target_release_id=artifact["target_release_id"],
        target_version=release["version"],
        target_release_sequence=release["release_sequence"],
        bundle_sha256=artifact["bundle_sha256"],
        bundle_size=artifact["bundle_size"],
        release_approval_reference=artifact["release_approval_reference"],
        release_candidate_sha256=artifact["release_candidate_sha256"],
        source_commit=artifact["source_commit"],
        allow_downgrade=False, reason=reason.strip(),
    )
    consume_locked_wave(session, grant=grant, deployment=result)
    return result
