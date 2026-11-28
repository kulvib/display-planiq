"""Reusable explicit managed update authority; no per-client pilot identity.

The bootstrap registration bridges the existing closed standard. Policy
remains disabled until recovery, admission and UI integration are accepted.
No new release may fall through to a generic legacy order.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from sqlmodel import select

from .clientflow_closed_standard_1251 import require_closed_standard_control
from .clientflow_pilot_1251 import successor_snapshot
from .clientflow_pilot_1252 import candidate_release, candidate_snapshot, require_rotated_store
from .clientflow_release_admin_models import ClientFlowReleaseControl
from .clientflow_release_security_policy import require_centrally_eligible_release
from .clientflow_releases import load_catalog
from .clientflow_update_models import ClientFlowDeployment, ClientFlowDeploymentEvent, ClientFlowUpdateCredential
from .client_presence import load_client_presence
from .models import Client, EnrollmentToken
from .enrollment_models import ClientEnrollmentReceipt
from .system_control import active_system_command, lock_system_client

MANAGED_AUTHORITY = "managed_forward_update_v1"
MAX_ORDER_CLIENTS = 25


class ManagedRolloutDenied(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise ManagedRolloutDenied(reason)


@dataclass(frozen=True)
class ReleasePolicy:
    source: Mapping
    target: Mapping
    release: Mapping
    revision: int
    enabled: bool


def current_policy() -> ReleasePolicy:
    # Single release registration, not a new endpoint or client-specific
    # implementation. The bootstrap control/catalog adapter is transitional.
    return ReleasePolicy(successor_snapshot(), candidate_snapshot(), candidate_release(), 3, False)


def matches_target(policy, release_id, version, sequence):
    target = policy.target
    return (release_id == target["target_release_id"] or version == target["target_version"]
            or sequence == target["target_release_sequence"])


def require_snapshot(policy, snapshot):
    require(all(type(snapshot.get(k)) is type(v) and snapshot.get(k) == v
                for k, v in policy.target.items()), "Målrelease matcher ikke godkendte bytes")


def require_control(session, policy, *, lock=False):
    require(policy.enabled is True, "Managed udrulning afventer samlet sikkerhedsaccept")
    query = select(ClientFlowReleaseControl).where(ClientFlowReleaseControl.id == 1)
    if lock:
        query = query.with_for_update()
    control = session.exec(query).one_or_none()
    require(control is not None, "Releasekontrol mangler")
    if lock:
        session.refresh(control)
    require(control.revision == policy.revision
            and control.stable_release_id == policy.source["target_release_id"]
            and control.stable_bundle_sha256 == policy.source["bundle_sha256"],
            "Releasekontrol er ændret")
    require(require_closed_standard_control(load_catalog(), control.model_dump()) == "bound",
            "Eksakt standardbinding mangler")
    for snapshot in (policy.source, policy.target):
        require_centrally_eligible_release(release_id=snapshot["target_release_id"],
                                          release_sequence=snapshot["target_release_sequence"])
    require(policy.target["target_release_sequence"] > policy.source["target_release_sequence"],
            "Kun fremadrettet opdatering")
    return control


def require_store(policy):
    snapshot = require_rotated_store()
    require_snapshot(policy, snapshot)
    return dict(snapshot)


def select_targets(policy, targets):
    ids = set()
    require(1 <= len(targets) <= MAX_ORDER_CLIENTS, "Vælg 1–25 klienter")
    for target in targets:
        require(type(target.client_id) is int and target.client_id > 0 and target.client_id not in ids,
                "Ugyldigt eller dubleret klient-ID")
        require(target.expected_source_version == policy.source["target_version"],
                "Klienten har ikke en kompatibel kildeversion")
        ids.add(target.client_id)
    return sorted(targets, key=lambda target: target.client_id)


def latest_order(session, client_id):
    return session.exec(select(ClientFlowDeployment).where(ClientFlowDeployment.client_id == client_id)
        .order_by(ClientFlowDeployment.requested_at.desc(), ClientFlowDeployment.id.desc()).limit(1)).first()


def require_source_evidence(session, client, policy):
    from .native_rdp_admission import matches_completed_update, matches_completed_enrollment
    latest = latest_order(session, client.id)
    if latest is not None:
        require(latest.allow_downgrade is False and matches_completed_update(
            latest, client_id=client.id, artifact=dict(policy.source)), "Kilderelease mangler verificeret deployment")
        return
    token = session.get(EnrollmentToken, client.enrollment_token_id) if client.enrollment_token_id is not None else None
    receipts = session.exec(select(ClientEnrollmentReceipt).where(
        ClientEnrollmentReceipt.client_id == client.id).limit(2)).all()
    require(len(receipts) == 1 and matches_completed_enrollment(
        token, receipts[0], client=client, artifact=dict(policy.source)), "Kilderelease mangler installationsbevis")


def require_client(session, client_id, policy):
    from .clientflow_deployments import active_deployment, unacknowledged_recovery_failure
    client = session.get(Client, client_id)
    require(client is not None, "Klient findes ikke")
    session.refresh(client)
    require(client.status == "approved" and client.deleted_at is None, "Klient er ikke godkendt")
    require(client.ubuntu_version in policy.release["ubuntu_compatibility"]["certified_versions"],
            "Klienten mangler certificeret Ubuntu-version")
    presence = load_client_presence(session, client).status
    require(presence.is_online and presence.agent_version == policy.source["target_version"],
            "Frisk kompatibel Status-version mangler")
    credentials = session.exec(select(ClientFlowUpdateCredential.id).where(
        ClientFlowUpdateCredential.client_id == client_id,
        ClientFlowUpdateCredential.revoked_at.is_(None)).limit(2)).all()
    require(len(credentials) == 1, "Entydig Update-identitet mangler")
    require(active_system_command(session, client_id) is None
            and active_deployment(session, client_id=client_id, for_update=True) is None
            and unacknowledged_recovery_failure(session, client_id=client_id) is None,
            "Aktiv System-handling, deployment eller uafklaret recovery")
    require_source_evidence(session, client, policy)
    return client


def authorization_payload(policy):
    return {"authority": MANAGED_AUTHORITY, "source": dict(policy.source),
            "target": dict(policy.target), "policy_revision": policy.revision}


def authorize_creation(session, *, snapshot, client_id, requested_by_user_id, allow_downgrade, authority):
    policy = current_policy()
    managed = matches_target(policy, snapshot["target_release_id"], snapshot["target_version"],
                             snapshot["target_release_sequence"])
    if not managed:
        require(authority is None, "Managed autorisation matcher ikke releaseidentitet")
        return None
    require(authority == MANAGED_AUTHORITY and type(requested_by_user_id) is int
            and requested_by_user_id > 0 and allow_downgrade is False, "Særskilt managed bestilling kræves")
    require_snapshot(policy, snapshot)
    lock_system_client(session, client_id)
    require_control(session, policy, lock=True)
    require_client(session, client_id, policy)
    return authorization_payload(policy)


def require_order_evidence(session, deployment, policy):
    require(deployment.allow_downgrade is False and deployment.requested_by_user_id is not None,
            "Ugyldig managed bestilling")
    require_snapshot(policy, {key: getattr(deployment, key, None) for key in policy.target})
    events = session.exec(select(ClientFlowDeploymentEvent).where(
        ClientFlowDeploymentEvent.deployment_id == deployment.id,
        ClientFlowDeploymentEvent.event_type == "managed_forward_authorized").limit(2)).all()
    require(len(events) == 1 and events[0].credential_id is None
            and events[0].payload == authorization_payload(policy), "Managed autorisationsbevis mangler")


def require_access(session, deployment):
    policy = current_policy()
    if not matches_target(policy, deployment.target_release_id, deployment.target_version,
                          deployment.target_release_sequence):
        return
    require_control(session, policy)
    require_order_evidence(session, deployment, policy)


def require_credential(session, deployment, credential_id):
    credential = session.get(ClientFlowUpdateCredential, credential_id) if credential_id is not None else None
    require(credential is not None and credential.client_id == deployment.client_id
            and credential.revoked_at is None, "Aktiv Update-identitet matcher ikke deployment")
