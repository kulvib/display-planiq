"""68N-D2/D3: one exact forward order; closed standard 1251 remains selected."""
from datetime import datetime, timezone

from sqlmodel import select

from .clientflow_1252_transition import (
    CANDIDATE_ID, CANDIDATE_VERSION, CANDIDATE_SEQUENCE, PREDECESSOR_ID,
    require, is_candidate_order,
)
from .clientflow_pilot_1252 import candidate_snapshot, match_candidate_artifact
from .clientflow_pilot_1251 import BASELINE_ID, SUCCESSOR_VERSION
from .clientflow_closed_standard_1251 import require_closed_standard_control, require_completed_successor
from .clientflow_release_admin_models import (
    ClientFlowReleaseControl, ClientFlowRolloutTarget, ClientFlowRolloutWave, ClientFlowPhysicalAcceptance,
)
from .clientflow_release_security_policy import require_centrally_eligible_release
from .clientflow_releases import load_catalog
from .clientflow_update_models import ClientFlowDeployment, ClientFlowDeploymentEvent, ClientFlowUpdateCredential, ClientFlowUpdateProvisioningToken
from .clientflow_rollback_models import ClientFlowRollbackPermit
from .enrollment_models import ClientEnrollmentReceipt
from .models import Client, EnrollmentToken
from .client_presence import load_client_presence
from .system_control import active_system_command, lock_system_client

RECOVERY_EVENT = "operator_1252_restoration_verified"
RECOVERY_PAYLOAD = {"restored_release_id": PREDECESSOR_ID, "verified_local_state": True,
                    "operator_attestation": True}


def require_control(session, *, lock=False):
    query = select(ClientFlowReleaseControl).where(ClientFlowReleaseControl.id == 1)
    if lock:
        query = query.with_for_update()
    control = session.exec(query).one_or_none()
    require(control is not None, "1252_CONTROL_MISSING")
    if lock:
        session.refresh(control)
    require(require_closed_standard_control(load_catalog(), control.model_dump()) == "bound",
            "1252_CONTROL_NOT_BOUND")
    require_centrally_eligible_release(release_id=PREDECESSOR_ID, release_sequence=1251)
    require_centrally_eligible_release(release_id=CANDIDATE_ID, release_sequence=1252)
    return control


def require_exact_order(row):
    require(row is not None and type(row.client_id) is int and row.client_id == 3
            and row.allow_downgrade is False, "1252_WRONG_CLIENT_OR_DIRECTION")
    match_candidate_artifact({key: getattr(row, key, None) for key in candidate_snapshot()})


def candidate_orders(session):
    return session.exec(select(ClientFlowDeployment).where(
        (ClientFlowDeployment.target_release_id == CANDIDATE_ID)
        | (ClientFlowDeployment.target_release_sequence == CANDIDATE_SEQUENCE)
        | (ClientFlowDeployment.target_version == CANDIDATE_VERSION)
    ).limit(2)).all()


def require_candidate_access(session, row):
    """No disk/network work. Recheck pin and closed policy on token/activation."""
    if not is_candidate_order(row):
        return
    require_exact_order(row)
    require_control(session)
    orders = candidate_orders(session)
    require(len(orders) == 1 and orders[0].id == row.id, "1252_ORDER_NOT_UNIQUE")


def predecessor_history(session):
    old = session.exec(select(ClientFlowDeployment).where(
        ClientFlowDeployment.target_release_id == BASELINE_ID).limit(2)).all()
    prior = session.exec(select(ClientFlowDeployment).where(
        ClientFlowDeployment.target_release_id == PREDECESSOR_ID).limit(2)).all()
    require(len(old) == len(prior) == 1, "1252_PREDECESSOR_HISTORY_NOT_UNIQUE")
    require_completed_successor(prior[0], old[0], client_id=3)
    require(old[0].completed_at <= prior[0].requested_at, "1252_PREDECESSOR_CHRONOLOGY")
    return prior[0]


def latest_order(session):
    return session.exec(select(ClientFlowDeployment).where(ClientFlowDeployment.client_id == 3)
        .order_by(ClientFlowDeployment.requested_at.desc(), ClientFlowDeployment.id.desc()).limit(1)).first()


def require_client(session):
    require(session.exec(select(Client.id).order_by(Client.id).limit(2)).all() == [3],
            "1252_REQUIRES_SOLE_CLIENT")
    client = session.get(Client, 3)
    require(client is not None, "1252_CLIENT_MISSING")
    session.refresh(client)
    require(client.name == "Viborg1" and client.status == "approved" and client.deleted_at is None
            and client.ubuntu_version == "26.04", "1252_CLIENT_IDENTITY_CHANGED")
    presence = load_client_presence(session, client).status
    require(presence.is_online and presence.agent_version == SUCCESSOR_VERSION, "1252_FRESH_1251_REQUIRED")
    credentials = session.exec(select(ClientFlowUpdateCredential.id).where(
        ClientFlowUpdateCredential.client_id == 3, ClientFlowUpdateCredential.revoked_at.is_(None)
    ).limit(2)).all()
    require(len(credentials) == 1, "1252_UPDATE_IDENTITY_NOT_UNIQUE")
    require(active_system_command(session, 3) is None, "1252_ACTIVE_SYSTEM_COMMAND")
    return client


def require_no_other_authority(session):
    from .clientflow_deployments import unacknowledged_recovery_failure
    require(unacknowledged_recovery_failure(session, client_id=3) is None, "1252_UNACKNOWLEDGED_RECOVERY")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    queries = (
        select(ClientFlowDeployment.id).where(ClientFlowDeployment.completed_at.is_(None)),
        select(EnrollmentToken.id).where(EnrollmentToken.used_at.is_(None),
            EnrollmentToken.revoked_at.is_(None), EnrollmentToken.expires_at > now),
        select(ClientEnrollmentReceipt.install_id).where(ClientEnrollmentReceipt.completed_at.is_(None),
            ClientEnrollmentReceipt.expires_at > now),
        select(ClientFlowUpdateProvisioningToken.id).where(ClientFlowUpdateProvisioningToken.used_at.is_(None),
            ClientFlowUpdateProvisioningToken.revoked_at.is_(None), ClientFlowUpdateProvisioningToken.expires_at > now),
        select(ClientFlowRollbackPermit.id).where(ClientFlowRollbackPermit.state == "issued",
            ClientFlowRollbackPermit.expires_at > now),
        select(ClientFlowRolloutTarget.id).where(ClientFlowRolloutTarget.state.in_(["approved", "consumed"])),
        select(ClientFlowRolloutWave.id).where(ClientFlowRolloutWave.state.in_(["approved", "running", "completed", "failed"])),
        select(ClientFlowRolloutWave.id).where(ClientFlowRolloutWave.state.in_(["draft", "paused"]),
            ClientFlowRolloutWave.expires_at > now),
        select(ClientFlowPhysicalAcceptance.id),
    )
    require(all(session.exec(query.limit(1)).first() is None for query in queries),
            "1252_CONFLICTING_AUTHORITY")


def require_preorder(session, *, lock=False):
    if lock:
        lock_system_client(session, 3)
    control = require_control(session, lock=lock)
    client = require_client(session)
    require_no_other_authority(session)
    require(not candidate_orders(session), "1252_ALREADY_ORDERED")
    prior = predecessor_history(session)
    latest = latest_order(session)
    require(latest is not None and latest.id == prior.id, "1252_PREDECESSOR_NOT_LATEST")
    return client, control


def require_candidate_history(session, row):
    require_exact_order(row)
    orders = candidate_orders(session)
    require(len(orders) == 1 and orders[0].id == row.id, "1252_ORDER_NOT_UNIQUE")
    prior = predecessor_history(session)
    require(prior.completed_at <= row.requested_at, "1252_ORDER_CHRONOLOGY")
    require(row.completed_at is not None, "1252_ORDER_NOT_TERMINAL")
    return prior


def recovery_events(session, row):
    """Terminal recovery evidence is not permission until operator verification."""
    require(row.state in {"failed", "cancelled", "rolled_back"}, "1252_RECOVERY_STATE_NOT_ELIGIBLE")
    events = session.exec(select(ClientFlowDeploymentEvent).where(
        ClientFlowDeploymentEvent.deployment_id == row.id,
        ClientFlowDeploymentEvent.event_type.in_([
            "activation_started", "health_check_started", "succeeded", "rollback_started",
            "rolled_back", "recovery_failed", "failed", "cancelled", RECOVERY_EVENT,
        ]),
    ).limit(16)).all()
    require(len(events) < 16, "1252_AMBIGUOUS_RECOVERY_EVENTS")
    grouped = {}
    for event in events:
        grouped.setdefault(event.event_type, []).append(event)
    require(all(len(items) == 1 for items in grouped.values()), "1252_DUPLICATE_RECOVERY_EVENTS")
    require(row.state in grouped and not ({"succeeded", "recovery_failed"} & grouped.keys()),
            "1252_TERMINAL_EVENT_MISSING_OR_CONFLICTING")
    if row.state in {"failed", "cancelled"}:
        require(not ({"activation_started", "health_check_started", "rollback_started", "rolled_back"}
                     & grouped.keys()), "1252_PREACTIVATION_FAILURE_NOT_PROVEN")
    else:
        require("activation_started" in grouped and "rollback_started" in grouped,
                "1252_ROLLBACK_CHAIN_MISSING")
        start, end = grouped["rollback_started"][0], grouped["rolled_back"][0]
        expected = {"failed_release_id": CANDIDATE_ID, "restored_release_id": PREDECESSOR_ID}
        require(start.credential_id is not None and start.credential_id == end.credential_id
                and start.payload == end.payload == expected and start.received_at <= end.received_at,
                "1252_ROLLBACK_CHAIN_MISMATCH")
        credential = session.get(ClientFlowUpdateCredential, end.credential_id)
        require(credential is not None and credential.client_id == 3 and credential.revoked_at is None,
                "1252_ROLLBACK_CREDENTIAL_UNAVAILABLE")
    return grouped.get(RECOVERY_EVENT, [])


def require_recovery_review(session, *, lock=False):
    if lock:
        lock_system_client(session, 3)
    control = require_control(session, lock=lock)
    client = require_client(session)
    require_no_other_authority(session)
    row = latest_order(session)
    require(row is not None, "1252_RECOVERY_ORDER_MISSING")
    require_candidate_history(session, row)
    require(not recovery_events(session, row), "1252_RECOVERY_ALREADY_ATTESTED")
    return client, control, row
