"""63D-17: explicit, one-shot Viborg1/1248 pilot through the admin UI.

There is deliberately no fleet switch, fresh-install path, rollback path,
background timer, or environment-variable authorization. All decisions and
writes happen in one client-serialized transaction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..audit import add_audit_log
from ..auth import get_current_superadmin_user
from ..client_domain_models import ClientDomainCredential, ClientDomainStatus
from ..clientflow_deployments import (
    ClientFlowDeploymentConflict, create_authorized_deployment,
    unacknowledged_recovery_failure,
)
from ..clientflow_pilot_1248 import (
    ClientFlowPilot1248Denied, PILOT_RELEASE_ID,
)
from ..clientflow_pilot_1248_db_authorization import (
    DatabasePilot1248Denied, require_database_pilot_1248,
)
from ..clientflow_release_pilot_stage_1248 import PilotStage1248Denied
from ..clientflow_release_security_policy import (
    ClientFlowReleaseSecurityDenied, require_centrally_eligible_release,
)
from ..clientflow_releases import (
    ClientFlowArtifactUnavailable, ClientFlowCatalogError,
    deployment_release_snapshot, load_catalog, resolve_release,
    validate_release_compatibility,
)
from ..clientflow_update_models import ClientFlowDeployment, ClientFlowUpdateCredential
from ..db import get_session
from ..models import Client
from ..system_control import lock_system_client
from .clientflow_deployments import _require_deployable_client
from .clientflow_release_administration import _bound_control, _reauth

router = APIRouter(prefix="/clientflow/release-pilot-1248", tags=["clientflow-release-pilot"])


class Pilot1248Request(BaseModel):
    client_id: int = Field(strict=True, ge=1, le=99999999)
    target_release_id: str = Field(min_length=1, max_length=160)
    expected_current_version: str = Field(pattern=r"^1\.3\.46$")
    expected_policy_revision: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=12, max_length=500)
    password: str = Field(min_length=1, max_length=256)
    confirmed_single_pilot: bool = False


def _fresh_status_version(session: Session, client: Client) -> str:
    """Require a current Status credential, not the legacy Client.version."""
    rows = session.exec(
        select(ClientDomainStatus, ClientDomainCredential)
        .join(ClientDomainCredential, ClientDomainStatus.credential_id == ClientDomainCredential.id)
        .where(
            ClientDomainStatus.client_id == client.id,
            ClientDomainStatus.domain == "status",
            ClientDomainCredential.client_id == client.id,
            ClientDomainCredential.domain == "status",
            ClientDomainCredential.revoked_at.is_(None),
        ).with_for_update()
    ).all()
    if len(rows) != 1:
        raise HTTPException(status_code=409, detail="Aktiv Status-identitet mangler eller er tvetydig")
    status, credential = rows[0]
    observed = status.reported_at
    if observed is None:
        raise HTTPException(status_code=409, detail="Status mangler frisk rapportering")
    now = datetime.now(timezone.utc)
    reported = observed.replace(tzinfo=timezone.utc) if observed.tzinfo is None else observed.astimezone(timezone.utc)
    age = now - reported
    version = status.agent_version
    if (
        status.credential_id != credential.id
        or status.observed_state != "online"
        or age < timedelta(seconds=-5) or age > timedelta(seconds=90)
        or version != "1.3.46"
    ):
        raise HTTPException(status_code=409, detail="Frisk, godkendt Status-version for Viborg1 mangler")
    return version


@router.post("/authorize", status_code=201)
def authorize_viborg1_1248_pilot(
    body: Pilot1248Request, request: Request, response: Response,
    session: Session = Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    # The client must remain the one *physically* inspected for this pilot.
    if (body.client_id != 3 or body.target_release_id != PILOT_RELEASE_ID
            or body.confirmed_single_pilot is not True):
        raise HTTPException(status_code=409, detail="Kun udtrykkelig Viborg1/1248-pilot er tilladt")
    reason = " ".join(body.reason.split()).strip()
    if len(reason) < 12:
        raise HTTPException(status_code=400, detail="En konkret pilotbegrundelse er påkrævet")
    # Import and reuse the established superadmin reauthentication, anti-
    # impersonation, rate limit and failed-password audit boundary.
    _reauth(request, session, user, body.password)
    try:
        # Stable lock order: client -> release-control -> deployment. A
        # concurrent System producer or second admin cannot authorize twice.
        lock_system_client(session, 3)
        client = session.get(Client, 3)
        if client is None or client.name != "Viborg1":
            raise HTTPException(status_code=409, detail="Pilotklientens identitet er ændret")
        _require_deployable_client(session, client)
        # Keep all three database-wide rollout holds closed. The bootstrap
        # singleton cannot be used to infer a fleet permission.
        control = _bound_control(session, lock=True)
        if control.revision != body.expected_policy_revision:
            raise HTTPException(status_code=409, detail="Releasepolitikken er ændret – opdater oversigten")
        if unacknowledged_recovery_failure(session, client_id=3) is not None:
            raise HTTPException(status_code=409, detail="Uafklaret recoveryfejl på Viborg1")
        prior = session.exec(select(ClientFlowDeployment.id).where(
            ClientFlowDeployment.client_id == 3,
            ClientFlowDeployment.target_release_id == PILOT_RELEASE_ID,
        ).limit(1)).first()
        if prior is not None:
            raise HTTPException(status_code=409, detail="1248-piloten er allerede bestilt én gang – manuel revurdering kræves")
        # Ordering must not silently succeed when the client updater has no
        # active cryptographic credential to read its one-shot deployment.
        credentials = session.exec(select(ClientFlowUpdateCredential.id).where(
            ClientFlowUpdateCredential.client_id == 3,
            ClientFlowUpdateCredential.revoked_at.is_(None),
        ).limit(2)).all()
        if len(credentials) != 1:
            raise HTTPException(status_code=409, detail="Klientens aktive Update-identitet mangler eller er tvetydig")
        version = _fresh_status_version(session, client)
        catalog = load_catalog()
        release = resolve_release("1.3.47")
        validate_release_compatibility(
            release, current_version=version, ubuntu_version=client.ubuntu_version,
        )
        require_centrally_eligible_release(release_id=PILOT_RELEASE_ID, release_sequence=1248)
        # The store reader verifies the *physical* file bytes, size and pinned
        # approval before any authorization is inserted.
        artifact = deployment_release_snapshot(release)
        require_database_pilot_1248(
            client_id=3, client_name=client.name, current_version=version,
            expected_current_version=body.expected_current_version,
            ubuntu_version=str(client.ubuntu_version), release=release,
            artifact=artifact, catalog=catalog, reason=reason,
            policy=control.model_dump(), expected_revision=body.expected_policy_revision,
        )
        deployment = create_authorized_deployment(
            session, client_id=3, requested_by_user_id=int(user.id),
            target_release_id=artifact["target_release_id"],
            target_version="1.3.47", target_release_sequence=1248,
            bundle_sha256=artifact["bundle_sha256"],
            bundle_size=artifact["bundle_size"],
            release_approval_reference=artifact["release_approval_reference"],
            release_candidate_sha256=artifact["release_candidate_sha256"],
            source_commit=artifact["source_commit"],
            allow_downgrade=False, reason=reason,
        )
        add_audit_log(
            session, action="clientflow_1248_db_pilot_authorized",
            request=request, actor=user, target_organization_id=client.organization_id,
            entity_type="clientflow_deployment", entity_id=3,
            entity_label="Viborg1 → ClientFlow 1.3.47/1248",
            severity="critical", is_critical=True,
            details={
                "client_id": 3, "deployment_id": deployment.id,
                "release_id": PILOT_RELEASE_ID, "source_version": version,
                "bundle_sha256": artifact["bundle_sha256"],
                "approval_reference": artifact["release_approval_reference"],
                "policy_revision": control.revision,
                "authorization_mode": "single_use_db_admin_reauth",
                "fleet_authorized": False, "fresh_install_authorized": False,
                "rollback_authorized": False, "reason": reason,
            },
        )
        session.commit()
        return {
            "deployment_id": deployment.id, "client_id": 3,
            "target_release_id": PILOT_RELEASE_ID,
            "source_version": version, "state": "authorized",
            "fleet_authorized": False,
            "rollback_authorized": False,
        }
    except (ClientFlowCatalogError, ClientFlowPilot1248Denied,
            PilotStage1248Denied, DatabasePilot1248Denied,
            ClientFlowReleaseSecurityDenied) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ClientFlowArtifactUnavailable as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ClientFlowDeploymentConflict, IntegrityError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Der er allerede en autoriseret klientdeployment") from exc
