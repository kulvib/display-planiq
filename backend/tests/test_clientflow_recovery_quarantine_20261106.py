"""Viborg2 2026-11-06: a terminal DB failure must not authorize a second update.

The failed physical controller left an activation intent behind. Recovery is an
explicitly verified human gate, NOT the presence of a completed_at timestamp.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

sqlmodel = pytest.importorskip("sqlmodel")
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from service1.clientflow_deployments import (
    ClientFlowDeploymentConflict,
    acknowledge_recovery,
    create_authorized_deployment,
    unacknowledged_recovery_failure,
    utcnow,
)
from service1.models import Client

CLIENT_ID = 9281


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Client(id=CLIENT_ID, name="Viborg2 regression", status="approved"))
        session.commit()
    return engine


def _deploy(session: Session, target_version: str = "1.3.41"):
    seq = {"1.3.41": 1242, "1.3.42": 1243}[target_version]
    return create_authorized_deployment(
        session,
        client_id=CLIENT_ID,
        requested_by_user_id=None,
        target_release_id=f"clientflow-{target_version}-seq-{seq}",
        target_version=target_version,
        target_release_sequence=seq,
        bundle_sha256=hashlib.sha256(target_version.encode()).hexdigest(),
        bundle_size=1234,
        release_approval_reference="verified-regression-fixture",
        allow_downgrade=False,
        reason="Physical pilot",
    )


def _failed(session):
    row = _deploy(session)
    session.flush()
    row.state = "recovery_failed"
    row.completed_at = utcnow()
    row.state_updated_at = row.completed_at
    session.add(row)
    session.commit()
    return row.id


def test_recovery_failed_blocks_new_authorization_even_when_terminal():
    engine = _engine()
    with Session(engine) as session:
        failure_id = _failed(session)
        pending = unacknowledged_recovery_failure(session, client_id=CLIENT_ID)
        assert pending is not None and pending.id == failure_id
        with pytest.raises(ClientFlowDeploymentConflict, match="recovery_failed"):
            _deploy(session, "1.3.42")


def test_attestation_requires_non_target_version_and_no_active_deployment():
    engine = _engine()
    with Session(engine) as session:
        failure_id = _failed(session)
        with pytest.raises(ClientFlowDeploymentConflict, match="målversion"):
            acknowledge_recovery(
                session,
                deployment_id=failure_id,
                actor_user_id=5,
                restored_version="1.3.41",
                reason="Physical recovery checked",
            )
        # A second update may be queued before this server-side gate existed.
        # Existing authorized work must be explicitly cancelled before ACK.
        from service1.clientflow_update_models import ClientFlowDeployment
        from sqlmodel import select
        queued = ClientFlowDeployment(
            id="00000000-0000-4000-8000-000000000111",
            client_id=CLIENT_ID,
            target_release_id="clientflow-1.3.41-seq-1242",
            target_version="1.3.41",
            target_release_sequence=1242,
            bundle_sha256="a" * 64,
            bundle_size=1234,
            release_approval_reference="queued-regression",
            allow_downgrade=False,
            requested_at=utcnow(),
            state="authorized",
            state_updated_at=utcnow(),
        )
        session.add(queued)
        session.flush()
        with pytest.raises(ClientFlowDeploymentConflict, match="afsluttes først"):
            acknowledge_recovery(
                session, deployment_id=failure_id, actor_user_id=5,
                restored_version="1.3.38", reason="Physically verified recovery",
            )
        queued.state = "cancelled"
        queued.completed_at = utcnow()
        queued.state_updated_at = queued.completed_at
        session.add(queued)
        session.commit()

        failed = acknowledge_recovery(
            session, deployment_id=failure_id, actor_user_id=5,
            restored_version="1.3.38", reason="Physical checks passed on Viborg2",
        )
        assert failed.state == "recovery_failed"  # immutable terminal result
        session.commit()
        assert unacknowledged_recovery_failure(session, client_id=CLIENT_ID) is None
        with pytest.raises(ClientFlowDeploymentConflict, match="allerede kvitteret"):
            acknowledge_recovery(
                session, deployment_id=failure_id, actor_user_id=5,
                restored_version="1.3.38", reason="Repeat must be rejected",
            )
        from service1.clientflow_update_models import ClientFlowDeploymentEvent
        events = session.exec(select(ClientFlowDeploymentEvent).where(
            ClientFlowDeploymentEvent.deployment_id == failure_id,
            ClientFlowDeploymentEvent.event_type == "operator_recovery_acknowledged",
        )).all()
        assert len(events) == 1
        assert events[0].payload["restored_version"] == "1.3.38"
        assert events[0].payload["actor_user_id"] == 5
        assert _deploy(session, "1.3.42").state == "authorized"


def test_bridge_and_attestation_scripts_are_fail_closed_and_do_not_reset_release_state():
    root = Path(__file__).resolve().parents[2]
    bridge = (root / "scripts/clientflow_1338_controller_bridge.sh").read_text()
    attestation = (root / "scripts/clientflow_local_recovery_attestation.sh").read_text()
    for token in (
        "--confirm-backend-idle", "BRIDGE_DRY_RUN_ONLY=PASS", "BRIDGE_UPDATER_TIMER_MUST_BE_STOPPED",
        "CONTROLLER_DEFINITION_DRIFT", "NeedDaemonReload", "ProtectHome=tmpfs",
        "BindPaths=/home/clientflow-kiosk", "BRIDGE_EFFECTIVE_SYSTEMD_CONFIGURATION_INVALID",
        'ln -- "$TMP" "$DROPIN"',
    ):
        assert token in bridge
    for token in (
        "activation_intent", "previous_release_id", "automatic_rollback_completed",
        "automatic_rollback_failed", "NeedDaemonReload", "clientflow.target",
        "RECOVERY_ATTESTATION=PASS",
    ):
        assert token in attestation
    assert "state.json" in bridge
    assert "save_state" not in bridge + attestation
    assert "systemctl daemon-reload" not in attestation
    assert "systemctl restart" not in attestation
