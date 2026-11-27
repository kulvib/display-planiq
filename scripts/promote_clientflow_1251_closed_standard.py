#!/usr/bin/env python3
"""68M-A: verified, closed 1251 standard rebind. Dry-run is default.

No release bytes, client state, deployment, enrollment or rollback permit
are modified. The active source catalog must be separately reviewed and
activated before an explicit operator apply. Never synthesize independent
physical or recovery acceptance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(ROOT / "client/release/lib")]

from sqlalchemy import text  # noqa: E402
from sqlmodel import Session, select  # noqa: E402
from service1.audit import add_audit_log  # noqa: E402
from service1.client_presence import load_client_presence  # noqa: E402
from service1.clientflow_deployments import unacknowledged_recovery_failure  # noqa: E402
from service1.clientflow_pilot_1251 import (  # noqa: E402
    BASELINE_ID, SUCCESSOR_ID, SUCCESSOR_VERSION, approval_lock_1251,
    closed_baseline_catalog, require_retained_store,
)
from service1.clientflow_closed_standard_1251 import (  # noqa: E402
    closed_standard_catalog, require_closed_standard_control, require_completed_successor,
)
from service1.clientflow_release_admin_models import (  # noqa: E402
    ClientFlowReleaseControl, ClientFlowRolloutWave, ClientFlowRolloutTarget,
    ClientFlowPhysicalAcceptance,
)
from service1.clientflow_release_security_policy import require_centrally_eligible_release  # noqa: E402
from service1.clientflow_releases import load_catalog  # noqa: E402
from service1.clientflow_rollback_models import ClientFlowRollbackPermit  # noqa: E402
from service1.clientflow_update_models import (  # noqa: E402
    ClientFlowDeployment, ClientFlowUpdateCredential, ClientFlowUpdateProvisioningToken,
)
from service1.enrollment_models import ClientEnrollmentReceipt  # noqa: E402
from service1.models import Client, EnrollmentToken  # noqa: E402
from service1.system_control import lock_system_client, active_system_command  # noqa: E402
from scripts.reconcile_clientflow_1251_store import (  # noqa: E402
    STORE, RotationDenied, require, _exists,
)


def transition_mode(catalog, control, *, apply):
    mode = require_closed_standard_control(closed_standard_catalog(), control, allow_predecessor=True)
    if catalog == closed_baseline_catalog():
        require(not apply and mode == "pending", "ACTIVE_1251_CATALOG_REQUIRED")
        return "staged"
    return require_closed_standard_control(catalog, control, allow_predecessor=True)


def _control_and_dependencies(session, *, apply):
    session.execute(text("SET LOCAL lock_timeout = '10s'"))
    session.execute(text("SET LOCAL statement_timeout = '30s'"))
    lock_system_client(session, 3)
    require(list(session.exec(select(Client.id).order_by(Client.id).limit(2)).all()) == [3],
            "CLIENT_INVENTORY_CHANGED")
    client = session.get(Client, 3)
    require(client is not None and client.name == "Viborg1" and client.status == "approved"
            and client.deleted_at is None and client.ubuntu_version == "26.04", "CLIENT_IDENTITY_CHANGED")
    presence = load_client_presence(session, client).status
    require(presence.is_online and presence.agent_version == SUCCESSOR_VERSION, "FRESH_1251_STATUS_REQUIRED")
    control = session.exec(select(ClientFlowReleaseControl).where(
        ClientFlowReleaseControl.id == 1).with_for_update()).one_or_none()
    require(control is not None, "RELEASE_CONTROL_MISSING")
    mode = transition_mode(load_catalog(), control.model_dump(), apply=apply)
    require_centrally_eligible_release(release_id=SUCCESSOR_ID, release_sequence=1251)
    require_centrally_eligible_release(release_id=BASELINE_ID, release_sequence=1250)
    require(not _exists(session, select(ClientFlowDeployment.id).where(
        ClientFlowDeployment.completed_at.is_(None))), "ACTIVE_DEPLOYMENT")
    require(unacknowledged_recovery_failure(session, client_id=3) is None, "UNACKNOWLEDGED_RECOVERY")
    require(active_system_command(session, 3) is None, "ACTIVE_SYSTEM_COMMAND")
    credentials = session.exec(select(ClientFlowUpdateCredential.id).where(
        ClientFlowUpdateCredential.client_id == 3,
        ClientFlowUpdateCredential.revoked_at.is_(None)).limit(2)).all()
    require(len(credentials) == 1, "UPDATE_IDENTITY_NOT_UNIQUE")
    latest = session.exec(select(ClientFlowDeployment).where(
        ClientFlowDeployment.client_id == 3).order_by(
        ClientFlowDeployment.requested_at.desc(), ClientFlowDeployment.id.desc()).limit(1)).first()
    predecessors = session.exec(select(ClientFlowDeployment).where(
        ClientFlowDeployment.target_release_id == BASELINE_ID).limit(2)).all()
    successors = session.exec(select(ClientFlowDeployment).where(
        ClientFlowDeployment.target_release_id == SUCCESSOR_ID).limit(2)).all()
    require(len(predecessors) == 1 and len(successors) == 1 and latest is not None
            and successors[0].id == latest.id, "NON_UNIQUE_DEPLOYMENT_HISTORY")
    require_completed_successor(latest, predecessors[0], client_id=3)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    require(not _exists(session, select(EnrollmentToken.id).where(
        EnrollmentToken.used_at.is_(None), EnrollmentToken.revoked_at.is_(None),
        EnrollmentToken.expires_at > now)), "LIVE_ENROLLMENT_TOKEN")
    require(not _exists(session, select(ClientEnrollmentReceipt.install_id).where(
        ClientEnrollmentReceipt.completed_at.is_(None), ClientEnrollmentReceipt.expires_at > now)),
        "UNFINISHED_ENROLLMENT")
    require(not _exists(session, select(ClientFlowUpdateProvisioningToken.id).where(
        ClientFlowUpdateProvisioningToken.used_at.is_(None), ClientFlowUpdateProvisioningToken.revoked_at.is_(None),
        ClientFlowUpdateProvisioningToken.expires_at > now)), "LIVE_UPDATE_PROVISIONING")
    require(not _exists(session, select(ClientFlowRollbackPermit.id).where(
        ClientFlowRollbackPermit.state == "issued", ClientFlowRollbackPermit.expires_at > now)), "LIVE_ROLLBACK_PERMIT")
    require(not _exists(session, select(ClientFlowRolloutTarget.id).where(
        ClientFlowRolloutTarget.state.in_(["approved", "consumed"]))), "ROLLOUT_TARGET_AUTHORITY")
    require(not _exists(session, select(ClientFlowRolloutWave.id).where(
        ClientFlowRolloutWave.state.in_(["approved", "running", "completed", "failed"]))), "ROLLOUT_WAVE_AUTHORITY")
    require(not _exists(session, select(ClientFlowRolloutWave.id).where(
        ClientFlowRolloutWave.state.in_(["draft", "paused"]), ClientFlowRolloutWave.expires_at > now)),
        "LIVE_DRAFT_OR_PAUSED_WAVE")
    require(not _exists(session, select(ClientFlowPhysicalAcceptance.id)), "UNEXPECTED_PHYSICAL_ACCEPTANCE")
    return control, mode, latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-physical-acceptance", action="store_true")
    args = parser.parse_args()
    require(args.apply == args.confirm_physical_acceptance, "EXPLICIT_OPERATOR_ATTESTATION_REQUIRED")
    require(ROOT == Path("/opt/display") and os.environ.get("CLIENTFLOW_RELEASE_ARTIFACT_DIR") == str(STORE),
            "WRONG_RENDER_SOURCE_OR_STORE")
    from service1.db import engine
    require(engine.dialect.name == "postgresql" and engine.url.database == "display"
            and engine.url.query.get("host") == "/run/display-postgres"
            and engine.url.host is None, "WRONG_LOCAL_DATABASE")
    # Verify all three immutable archives before taking database locks.
    artifact = require_retained_store()
    with Session(engine) as session, session.begin():
        control, mode, latest = _control_and_dependencies(session, apply=args.apply)
        print(json.dumps({"mode": mode, "control_revision": control.revision,
            "deployment_provenance": "verified", "retained_store": "verified",
            "deployment_authorized": False, "fleet_open": False, "fresh_install_open": False},
            sort_keys=True), flush=True)
        if args.apply and mode == "pending":
            control.stable_release_id = SUCCESSOR_ID
            control.stable_bundle_sha256 = approval_lock_1251()["approved_bundle_sha256"]
            control.revision = 3
            control.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            control.updated_by_user_id = None
            require_closed_standard_control(load_catalog(), control.model_dump())
            session.add(control)
            add_audit_log(session, action="clientflow_closed_standard_1251_rebound",
                entity_type="clientflow_release_control", entity_id=1,
                entity_label="1250 → closed 1251", severity="critical", is_critical=True,
                details={"authority": "render_operator_shell", "client_id": 3,
                         "deployment_id": latest.id, **artifact, "revision": 3,
                         "physical_acceptance_operator_reported": True,
                         "independent_review_verified": False, "recovery_exercise_verified": False,
                         "fleet_open": False, "fresh_install_open": False, "cutover_enabled": False,
                         "deployment_authorized": False})
    print("CLOSED_STANDARD_1251=" + ("PASS" if args.apply else "PREFLIGHT_PASS_NO_MUTATION")
          + "; DEPLOYMENT_AUTHORIZED=NO", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Preserve the sanitized failure contract of the earlier rotation.
        reason = str(exc) if isinstance(exc, RotationDenied) else type(exc).__name__
        print("CLOSED_STANDARD_STOP=" + reason, file=sys.stderr, flush=True)
        raise SystemExit(2)
