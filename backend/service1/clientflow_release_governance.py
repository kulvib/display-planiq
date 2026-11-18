"""Staged 63D-3 human governance transaction, intentionally without HTTP routes.

No production route imports this module. Every mutator locks the singleton
policy then the wave then the targets, flushes without commit, and appends an
AuditLog in the *same transaction*. No permission flags or deployment are
written, and an operator must never treat these staged functions as live
fleet authorization. This is future cutover preparation only.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from sqlmodel import Session, select

from .audit import add_audit_log
from .client_domain_models import ClientDomainCredential, ClientDomainStatus
from .clientflow_deployments import unacknowledged_recovery_failure
from .clientflow_release_admin_models import (
    ClientFlowPhysicalAcceptance, ClientFlowReleaseControl,
    ClientFlowRolloutTarget, ClientFlowRolloutWave,
)
from .clientflow_release_governance_policy import (
    GovernanceDenied, physical_evidence_payload, require_approved_physical_evidence,
    require_revisions, require_wave_action, utc,
)
from .clientflow_releases import (
    ClientFlowArtifactUnavailable, ClientFlowCatalogError,
    deployment_release_snapshot, resolve_release,
)
from .clientflow_update_models import ClientFlowDeployment
from .models import Client, User


def _naive_now(now: datetime) -> datetime:
    return utc(now).replace(tzinfo=None)


def _actor(session: Session, actor_id: int) -> User:
    if type(actor_id) is not int or actor_id <= 0:
        raise GovernanceDenied("actor_not_active_superadmin")
    actor = session.get(User, actor_id)
    if actor is None or actor.is_superadmin is not True or actor.is_active is not True:
        raise GovernanceDenied("actor_not_active_superadmin")
    return actor


def _policy(session: Session, revision: int, release_id: str, sha: str) -> ClientFlowReleaseControl:
    policy = session.exec(select(ClientFlowReleaseControl).where(
        ClientFlowReleaseControl.id == 1).with_for_update()).first()
    if (policy is None or type(revision) is not int or policy.revision != revision
            or policy.stable_release_id != release_id or policy.stable_bundle_sha256 != sha):
        raise GovernanceDenied("policy_revision_or_release_binding_changed")
    return policy


def _published_release(policy: ClientFlowReleaseControl) -> None:
    """Prove immutable signed publication, not merely a catalog candidate."""
    try:
        rid = policy.stable_release_id
        version, sequence = rid.removeprefix("clientflow-").rsplit("-seq-", 1)
        if not sequence.isdecimal() or not version:
            raise GovernanceDenied("release_id_invalid")
        release = resolve_release(version)
        if (release.get("release_id") != rid or release.get("release_sequence") != int(sequence)
                or release.get("status") != "stable" or release.get("installable") is not True
                or release.get("update_allowed") is not True
                or release.get("rollback_allowed") is not False):
            raise GovernanceDenied("signed_stable_release_required")
        verified = deployment_release_snapshot(release)
        if (verified.get("target_release_id") != rid
                or verified.get("bundle_sha256") != policy.stable_bundle_sha256
                or not verified.get("release_approval_reference")):
            raise GovernanceDenied("signed_artifact_binding_changed")
    except GovernanceDenied:
        raise
    except (ValueError, TypeError, KeyError, RuntimeError, ClientFlowCatalogError,
            ClientFlowArtifactUnavailable) as exc:
        raise GovernanceDenied("signed_artifact_not_verified") from exc


def _wave_and_targets(session: Session, wave_id: str) -> tuple[ClientFlowRolloutWave, list[ClientFlowRolloutTarget]]:
    wave = session.exec(select(ClientFlowRolloutWave).where(
        ClientFlowRolloutWave.id == wave_id).with_for_update()).first()
    if wave is None:
        raise GovernanceDenied("wave_missing")
    targets = list(session.exec(select(ClientFlowRolloutTarget).where(
        ClientFlowRolloutTarget.wave_id == wave.id)
        .order_by(ClientFlowRolloutTarget.client_id, ClientFlowRolloutTarget.id)
        .with_for_update()).all())
    return wave, targets


def _snapshot(obj):
    return obj.model_dump()


def _audit(session: Session, *, actor: User, action: str, wave: ClientFlowRolloutWave | None,
           policy: ClientFlowReleaseControl, details: dict) -> None:
    add_audit_log(
        session, action=action, actor=actor,
        entity_type="clientflow_rollout_wave" if wave else "clientflow_physical_acceptance",
        entity_label=wave.id if wave else policy.stable_release_id,
        severity="critical", is_critical=True,
        details={"release_id": policy.stable_release_id,
                 "bundle_sha256": policy.stable_bundle_sha256,
                 "policy_revision": policy.revision,
                 "db_cutover_changed": False,
                 "deployment_authorized": False,
                 **details},
    )


def _physical(session: Session, policy: ClientFlowReleaseControl, now: datetime):
    # The future grant engine refuses ambiguous evidence. Honor that same
    # property here; a rejected attempt is not silently overwritten.
    matches = list(session.exec(select(ClientFlowPhysicalAcceptance).where(
        ClientFlowPhysicalAcceptance.release_id == policy.stable_release_id,
        ClientFlowPhysicalAcceptance.bundle_sha256 == policy.stable_bundle_sha256,
    ).order_by(ClientFlowPhysicalAcceptance.created_at, ClientFlowPhysicalAcceptance.id)
         .with_for_update().limit(2)).all())
    if len(matches) != 1:
        raise GovernanceDenied("physical_acceptance_missing_or_ambiguous")
    acceptance = matches[0]
    require_approved_physical_evidence(
        acceptance=_snapshot(acceptance), release_id=policy.stable_release_id,
        bundle_sha256=policy.stable_bundle_sha256, now=now,
    )
    return acceptance


def stage_physical_acceptance(
    session: Session, *, release_id: str, bundle_sha256: str,
    expected_policy_revision: int, pilot_client_id: int,
    tested_by_user_id: int, reviewer_user_id: int, observed_version: str,
    pilot_reference: str, recovery_reference: str, now: datetime,
) -> ClientFlowPhysicalAcceptance:
    """A future two-person, signed-artifact-bound manual attestation.

    Physical testing itself MUST happen outside this API. Human claims do not
    substitute for a physical test, and this function has no production route.
    """
    tested_by = _actor(session, tested_by_user_id)
    reviewer = _actor(session, reviewer_user_id)
    now = _naive_now(now)
    evidence = physical_evidence_payload(
        client_id=pilot_client_id, release_id=release_id,
        bundle_sha256=bundle_sha256, tested_by_user_id=int(tested_by.id),
        reviewer_user_id=int(reviewer.id), observed_version=observed_version,
        pilot_reference=pilot_reference, recovery_reference=recovery_reference,
    )
    policy = _policy(session, expected_policy_revision, release_id, bundle_sha256)
    _published_release(policy)
    prior = list(session.exec(select(ClientFlowPhysicalAcceptance.id).where(
        ClientFlowPhysicalAcceptance.release_id == release_id,
        ClientFlowPhysicalAcceptance.bundle_sha256 == bundle_sha256,
    ).limit(1)).all())
    if prior:
        raise GovernanceDenied("physical_acceptance_already_recorded")
    client = session.get(Client, pilot_client_id)
    if client is None or client.status != "approved" or client.deleted_at is not None:
        raise GovernanceDenied("pilot_client_not_approved")
    # Current, credential-bound canonical Status is an additional attestation;
    # never infer installed version from legacy Client.client_version.
    rows = session.exec(select(ClientDomainStatus, ClientDomainCredential)
        .join(ClientDomainCredential, ClientDomainStatus.credential_id == ClientDomainCredential.id)
        .where(ClientDomainStatus.client_id == pilot_client_id,
               ClientDomainStatus.domain == "status",
               ClientDomainCredential.client_id == pilot_client_id,
               ClientDomainCredential.domain == "status",
               ClientDomainCredential.revoked_at.is_(None))).all()
    if len(rows) != 1:
        raise GovernanceDenied("pilot_status_credential_missing")
    status, credential = rows[0]
    if (status.credential_id != credential.id or status.observed_state != "online"
            or status.agent_version != observed_version or utc(status.reported_at) > utc(now)
            or utc(now) - utc(status.reported_at) > timedelta(seconds=90)):
        raise GovernanceDenied("pilot_status_not_fresh_or_mismatched")
    # For the 1246 in-place pilot, a healthy Status alone is NOT proof of
    # installed artifact bytes. Require a terminal successful deployment of
    # exactly this release/SHA and no unresolved recovery failure. Future
    # fresh-install acceptance needs an independently designed claim proof.
    if unacknowledged_recovery_failure(session, client_id=pilot_client_id) is not None:
        raise GovernanceDenied("pilot_recovery_not_acknowledged")
    succeeded = session.exec(select(ClientFlowDeployment.id).where(
        ClientFlowDeployment.client_id == pilot_client_id,
        ClientFlowDeployment.target_release_id == release_id,
        ClientFlowDeployment.bundle_sha256 == bundle_sha256,
        ClientFlowDeployment.state == "succeeded",
    ).limit(1)).first()
    if succeeded is None:
        raise GovernanceDenied("pilot_signed_deployment_success_missing")
    row = ClientFlowPhysicalAcceptance(
        id=str(uuid4()), release_id=release_id, bundle_sha256=bundle_sha256,
        client_id=pilot_client_id, actor_user_id=int(reviewer.id),
        decision="accepted", evidence=evidence, created_at=now,
    )
    session.add(row)
    _audit(session, actor=reviewer, action="clientflow_physical_pilot_staged_for_review",
           wave=None, policy=policy, details={
               "client_id": pilot_client_id, "tested_by_user_id": tested_by.id,
               "acceptance_id": row.id,
               "pilot_reference": pilot_reference, "recovery_reference": recovery_reference,
           })
    session.flush()
    return row


def stage_approve_controlled_wave(
    session: Session, *, wave_id: str, expected_policy_revision: int,
    expected_wave_revision: int, release_id: str, bundle_sha256: str,
    actor_user_id: int, now: datetime,
) -> ClientFlowRolloutWave:
    """Future two-person approval; does not turn on fleet, cutover or install."""
    actor = _actor(session, actor_user_id)
    now = _naive_now(now)
    policy = _policy(session, expected_policy_revision, release_id, bundle_sha256)
    wave, targets = _wave_and_targets(session, wave_id)
    require_revisions(control=_snapshot(policy), wave=_snapshot(wave),
                      control_revision=expected_policy_revision,
                      wave_revision=expected_wave_revision,
                      release_id=release_id, bundle_sha256=bundle_sha256)
    require_wave_action(action="approve", wave=_snapshot(wave),
                        targets=[_snapshot(t) for t in targets], now=now,
                        actor_id=actor_user_id)
    _published_release(policy)
    _physical(session, policy, now)
    clients = list(session.exec(select(Client.id, Client.status, Client.deleted_at)
        .where(Client.id.in_([t.client_id for t in targets]))).all())
    if len(clients) != len(targets) or any(state != "approved" or deleted_at is not None
                                         for _, state, deleted_at in clients):
        raise GovernanceDenied("target_client_not_approved")
    # The reviewer must not approve a wave against an already changed source
    # identity. This bounded 25-client query runs ONLY in staged human admin,
    # never on any display/status hotpath. The real grant still rechecks under
    # the client lock at consumption time.
    statuses = session.exec(select(ClientDomainStatus, ClientDomainCredential)
        .join(ClientDomainCredential, ClientDomainStatus.credential_id == ClientDomainCredential.id)
        .where(ClientDomainStatus.client_id.in_([t.client_id for t in targets]),
               ClientDomainStatus.domain == "status",
               ClientDomainCredential.domain == "status",
               ClientDomainCredential.revoked_at.is_(None))).all()
    if len(statuses) != len(targets):
        raise GovernanceDenied("target_status_credential_missing")
    target_ids = {t.client_id for t in targets}
    observed_ids = set()
    for status, credential in statuses:
        if (status.client_id not in target_ids or status.client_id in observed_ids
                or credential.client_id != status.client_id
                or status.credential_id != credential.id
                or status.observed_state != "online"
                or status.agent_version != wave.source_version
                or utc(status.reported_at) > utc(now)
                or utc(now) - utc(status.reported_at) > timedelta(seconds=90)):
            raise GovernanceDenied("target_canonical_status_changed")
        observed_ids.add(status.client_id)
    # The DB unique partial index is the final protection against a target
    # concurrently being approved in a second wave.
    for target in targets:
        target.state = "approved"
        session.add(target)
    wave.state = "approved"
    wave.approved_at = now
    wave.approved_by_user_id = int(actor.id)
    wave.revision += 1
    session.add(wave)
    _audit(session, actor=actor, action="clientflow_wave_staged_approved", wave=wave,
           policy=policy, details={"wave_revision": wave.revision,
               "target_client_ids": sorted(t.client_id for t in targets),
               "physical_acceptance_required": True,
               "planning_review_distinct_from_release_approval": True})
    session.flush()
    return wave


def stage_control_wave(
    session: Session, *, action: str, wave_id: str,
    expected_policy_revision: int, expected_wave_revision: int,
    release_id: str, bundle_sha256: str, actor_user_id: int,
    reason: str, now: datetime,
) -> ClientFlowRolloutWave:
    """Pause, resume or irrevocably stop future grants, never in-flight updates."""
    if action not in ("pause", "resume", "stop"):
        raise GovernanceDenied("invalid_control_action")
    if not isinstance(reason, str) or len(" ".join(reason.split())) < 12 or len(reason) > 500:
        raise GovernanceDenied("operator_reason_required")
    actor = _actor(session, actor_user_id)
    now = _naive_now(now)
    policy = _policy(session, expected_policy_revision, release_id, bundle_sha256)
    wave, targets = _wave_and_targets(session, wave_id)
    require_revisions(control=_snapshot(policy), wave=_snapshot(wave),
                      control_revision=expected_policy_revision,
                      wave_revision=expected_wave_revision,
                      release_id=release_id, bundle_sha256=bundle_sha256)
    require_wave_action(action=action, wave=_snapshot(wave),
                        targets=[_snapshot(t) for t in targets], now=now,
                        actor_id=actor_user_id)
    if action == "resume":
        _published_release(policy)
        _physical(session, policy, now)
        wave.state = "running" if any(t.state == "consumed" for t in targets) else "approved"
    elif action == "pause":
        wave.state = "paused"
    else:
        # Already-authorized deployments remain immutable. Stop prevents new
        # approvals for this wave, and leaves an explicit audit of in-flight work.
        wave.state = "cancelled"
        for t in targets:
            if t.state in ("draft", "approved"):
                t.state = "revoked"
                session.add(t)
    wave.revision += 1
    session.add(wave)
    _audit(session, actor=actor, action=f"clientflow_wave_staged_{action}",
           wave=wave, policy=policy, details={
               "reason": " ".join(reason.split()), "wave_revision": wave.revision,
               "consumed_target_count": sum(t.state == "consumed" for t in targets),
               "unconsumed_target_count": sum(t.state != "consumed" for t in targets),
               "inflight_deployments_not_cancelled": True,
           })
    session.flush()
    return wave


def stage_reconcile_wave(
    session: Session, *, wave_id: str, expected_policy_revision: int,
    expected_wave_revision: int, release_id: str, bundle_sha256: str,
    actor_user_id: int, now: datetime,
) -> ClientFlowRolloutWave:
    """Close a fully-consumed wave after signed snapshot and terminal outcomes."""
    actor = _actor(session, actor_user_id)
    now = _naive_now(now)
    policy = _policy(session, expected_policy_revision, release_id, bundle_sha256)
    wave, targets = _wave_and_targets(session, wave_id)
    require_revisions(control=_snapshot(policy), wave=_snapshot(wave),
                      control_revision=expected_policy_revision,
                      wave_revision=expected_wave_revision,
                      release_id=release_id, bundle_sha256=bundle_sha256)
    require_wave_action(action="reconcile", wave=_snapshot(wave),
                        targets=[_snapshot(t) for t in targets], now=now,
                        actor_id=actor_user_id)
    consumed = [t for t in targets if t.state == "consumed"]
    if not consumed or any(not t.consumed_deployment_id for t in consumed):
        raise GovernanceDenied("no_consumed_deployments")
    deployments = list(session.exec(select(ClientFlowDeployment).where(
        ClientFlowDeployment.id.in_([t.consumed_deployment_id for t in consumed]))).all())
    if len(deployments) != len(consumed):
        raise GovernanceDenied("deployment_history_missing")
    by_id = {d.id: d for d in deployments}
    if any(by_id[t.consumed_deployment_id].client_id != t.client_id
           or by_id[t.consumed_deployment_id].bundle_sha256 != bundle_sha256
           or by_id[t.consumed_deployment_id].target_release_id != release_id
           for t in consumed):
        raise GovernanceDenied("deployment_provenance_mismatch")
    bad = [d for d in deployments if d.state in (
        "failed", "cancelled", "rolled_back", "recovery_failed")]
    if bad:
        wave.state = "failed"
        for t in targets:
            if t.state == "approved":
                t.state = "revoked"
                session.add(t)
    elif len(consumed) == len(targets) and all(d.state == "succeeded" for d in deployments):
        wave.state = "completed"
    else:
        raise GovernanceDenied("wave_still_in_progress")
    wave.revision += 1
    session.add(wave)
    _audit(session, actor=actor, action="clientflow_wave_staged_reconciled",
           wave=wave, policy=policy, details={"outcome": wave.state,
               "success_count": sum(d.state == "succeeded" for d in deployments),
               "failure_count": len(bad), "wave_revision": wave.revision})
    session.flush()
    return wave
