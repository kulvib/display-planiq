"""Explicit superadmin forward-update orders for the physically accepted 1.4 baseline.

This lane never arms a pilot, promotes a catalog, opens a control flag, runs
historical plans, performs fresh installation or authorizes a downgrade.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..audit import add_audit_log
from ..auth import get_current_superadmin_user
from ..clientflow_deployments import (
    ClientFlowDeploymentConflict, active_deployment, create_authorized_deployment,
    unacknowledged_recovery_failure,
)
from ..clientflow_release_admin_models import ClientFlowPhysicalAcceptance, ClientFlowReleaseControl
from ..clientflow_release_security_policy import ClientFlowReleaseSecurityDenied
from ..clientflow_releases import (
    ClientFlowArtifactUnavailable, ClientFlowCatalogError, deployment_release_snapshot,
    load_catalog, resolve_release, validate_release_compatibility,
)
from ..clientflow_standard_release import (
    BASELINE_ID, BASELINE_VERSION, BASELINE_SEQUENCE, MAX_REQUEST_CLIENTS,
    StandardReleaseDenied, require_cutover_authority, validate_baseline_catalog, validate_selection,
)
from ..clientflow_update_models import ClientFlowDeployment, ClientFlowUpdateCredential
from ..db import get_session
from ..models import Client
from ..system_control import lock_system_client
from .clientflow_deployments import _canonical_runtime_version, _require_deployable_client
from .clientflow_release_administration import _reauth, _require_actor, _no_store

router = APIRouter(prefix="/clientflow/standard-deployments", tags=["clientflow-standard-deployments"])


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: int = Field(strict=True, gt=0)
    expected_source_version: str = Field(min_length=5, max_length=40)


class StandardOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_release_id: str = Field(min_length=1, max_length=160)
    expected_bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: int = Field(strict=True, ge=1)
    targets: list[Target] = Field(min_length=1, max_length=MAX_REQUEST_CLIENTS)
    confirmed: bool = Field(strict=True)
    password: str = Field(min_length=1, max_length=256)


def _control(session: Session, *, lock: bool) -> ClientFlowReleaseControl:
    query = select(ClientFlowReleaseControl).where(ClientFlowReleaseControl.id == 1)
    if lock:
        query = query.with_for_update()
    row = session.exec(query).first()
    if row is None:
        raise StandardReleaseDenied("Releasekontrol mangler")
    return row


def _verified_acceptance(session: Session, *, control: ClientFlowReleaseControl, lock: bool):
    query = select(ClientFlowPhysicalAcceptance).where(
        ClientFlowPhysicalAcceptance.release_id == control.stable_release_id,
        ClientFlowPhysicalAcceptance.bundle_sha256 == control.stable_bundle_sha256,
    ).order_by(ClientFlowPhysicalAcceptance.id).limit(2)
    if lock:
        query = query.with_for_update()
    rows = session.exec(query).all()
    if len(rows) != 1:
        raise StandardReleaseDenied("Fysisk pilotaccept mangler eller er tvetydig")
    return rows[0]


def _require_physical_success(session: Session, acceptance, artifact):
    verified = session.exec(select(ClientFlowDeployment.id).where(
        ClientFlowDeployment.client_id == acceptance.client_id,
        ClientFlowDeployment.target_release_id == BASELINE_ID,
        ClientFlowDeployment.bundle_sha256 == artifact["bundle_sha256"],
        ClientFlowDeployment.bundle_size == artifact["bundle_size"],
        ClientFlowDeployment.release_approval_reference == artifact["release_approval_reference"],
        ClientFlowDeployment.release_candidate_sha256 == artifact["release_candidate_sha256"],
        ClientFlowDeployment.source_commit == artifact["source_commit"],
        ClientFlowDeployment.state == "succeeded",
    ).limit(1)).first()
    if verified is None or unacknowledged_recovery_failure(session, client_id=acceptance.client_id) is not None:
        raise StandardReleaseDenied("Succesfuld fysisk deployment af samme releasebytes mangler")


def _require_authority(session: Session, *, catalog, artifact, control, expected_revision,
                       expected_release_id, expected_bundle_sha256, lock: bool):
    acceptance = _verified_acceptance(session, control=control, lock=lock)
    require_cutover_authority(
        catalog=catalog, control=control.model_dump(), artifact=artifact,
        acceptance=acceptance.model_dump(), expected_revision=expected_revision,
        expected_release_id=expected_release_id, expected_bundle_sha256=expected_bundle_sha256,
        now=datetime.now(timezone.utc),
    )
    _require_physical_success(session, acceptance, artifact)


@router.get("/availability")
def standard_deployment_availability(
    request: Request, response: Response, session: Session = Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    """Explicit capability read; never polled by ordinary client traffic."""
    _require_actor(request, user)
    _no_store(response)
    try:
        catalog = load_catalog()
        validate_baseline_catalog(catalog)
        control = _control(session, lock=False)
        if control.cutover_enabled is not True or control.fleet_open is not True:
            raise StandardReleaseDenied("Udrulning afventer godkendt cutover")
        release = resolve_release(BASELINE_VERSION)
        artifact = deployment_release_snapshot(release)
        _require_authority(
            session, catalog=catalog, artifact=artifact, control=control,
            expected_revision=control.revision, expected_release_id=BASELINE_ID,
            expected_bundle_sha256=control.stable_bundle_sha256, lock=False,
        )
        return {"available": True, "target_release_id": BASELINE_ID, "target_version": BASELINE_VERSION,
                "bundle_sha256": artifact["bundle_sha256"], "revision": control.revision,
                "max_clients": MAX_REQUEST_CLIENTS, "rollback_available": False}
    except (StandardReleaseDenied, ClientFlowCatalogError, ClientFlowReleaseSecurityDenied):
        return {"available": False, "reason": "Standardrelease, publicering eller fysisk accept er ikke godkendt",
                "rollback_available": False}


@router.post("", status_code=201)
def authorize_standard_deployments(
    body: StandardOrder, request: Request, response: Response,
    session: Session = Depends(get_session), user=Depends(get_current_superadmin_user),
):
    _require_actor(request, user)
    _no_store(response)
    try:
        if body.confirmed is not True or body.target_release_id != BASELINE_ID:
            raise StandardReleaseDenied("Bekræft den konkrete standardrelease")
        selected = validate_selection([(target.client_id, target.expected_source_version) for target in body.targets])
        catalog = load_catalog()
        validate_baseline_catalog(catalog)
        # Reject the default-closed control before expensive artifact reads.
        initial = _control(session, lock=False)
        if (initial.revision != body.expected_revision
                or initial.stable_release_id != body.target_release_id
                or initial.stable_bundle_sha256 != body.expected_bundle_sha256
                or initial.cutover_enabled is not True or initial.fleet_open is not True):
            raise StandardReleaseDenied("Releasekontrol er lukket eller ændret")
        _reauth(request, session, user, body.password)
        release = resolve_release(BASELINE_VERSION)
        artifact = deployment_release_snapshot(release)

        # One bounded atomic order: all client locks in deterministic order,
        # then release-control lock. No network downloads under these locks.
        for client_id, _ in selected:
            lock_system_client(session, client_id)
        control = _control(session, lock=True)
        session.refresh(control)
        _require_authority(
            session, catalog=catalog, artifact=artifact, control=control,
            expected_revision=body.expected_revision, expected_release_id=body.target_release_id,
            expected_bundle_sha256=body.expected_bundle_sha256, lock=True,
        )
        verified_clients = []
        for client_id, expected_version in selected:
            client = session.get(Client, client_id)
            if client is None:
                raise StandardReleaseDenied(f"Klient #{client_id} findes ikke")
            session.refresh(client)
            _require_deployable_client(session, client)
            version = _canonical_runtime_version(session, client)
            if version != expected_version:
                raise StandardReleaseDenied(f"Klient #{client_id} har ændret kildeversion")
            validate_release_compatibility(release, current_version=version, ubuntu_version=client.ubuntu_version)
            if not isinstance(client.ubuntu_version, str) or not client.ubuntu_version.startswith("26.04"):
                raise StandardReleaseDenied(f"Klient #{client_id} mangler godkendt Ubuntu-version")
            credentials = session.exec(select(ClientFlowUpdateCredential.id).where(
                ClientFlowUpdateCredential.client_id == client_id,
                ClientFlowUpdateCredential.revoked_at.is_(None),
            ).limit(2)).all()
            if len(credentials) != 1:
                raise StandardReleaseDenied(f"Klient #{client_id} mangler entydig Update-identitet")
            if (active_deployment(session, client_id=client_id, for_update=True) is not None
                    or unacknowledged_recovery_failure(session, client_id=client_id) is not None):
                raise StandardReleaseDenied(f"Klient #{client_id} har aktiv deployment eller uafklaret recovery")
            verified_clients.append((client, version))

        rows = []
        for client, version in verified_clients:
            reason = f"ClientFlow-opdatering {version} → {BASELINE_VERSION}"
            deployment = create_authorized_deployment(
                session, client_id=int(client.id), requested_by_user_id=int(user.id),
                target_release_id=artifact["target_release_id"], target_version=BASELINE_VERSION,
                target_release_sequence=BASELINE_SEQUENCE, bundle_sha256=artifact["bundle_sha256"],
                bundle_size=artifact["bundle_size"], release_approval_reference=artifact["release_approval_reference"],
                release_candidate_sha256=artifact["release_candidate_sha256"], source_commit=artifact["source_commit"],
                allow_downgrade=False, reason=reason,
            )
            add_audit_log(
                session, action="clientflow_standard_deployment_authorized", request=request,
                actor=user, target_organization_id=client.organization_id, entity_type="clientflow_deployment",
                entity_id=client.id, entity_label=f"{client.name} → {BASELINE_VERSION}",
                severity="warning", details={"deployment_id": deployment.id, "client_id": client.id,
                    "source_version": version, "target_release_id": BASELINE_ID,
                    "bundle_sha256": artifact["bundle_sha256"], "policy_revision": control.revision,
                    "reason": reason, "allow_downgrade": False},
            )
            rows.append({"deployment_id": deployment.id, "client_id": int(client.id), "state": "authorized"})
        session.commit()
        return {"target_release_id": BASELINE_ID, "deployments": rows}
    except HTTPException:
        session.rollback()
        raise
    except ClientFlowArtifactUnavailable as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (StandardReleaseDenied, ClientFlowCatalogError, ClientFlowReleaseSecurityDenied,
            ClientFlowDeploymentConflict, IntegrityError, ValueError) as exc:
        session.rollback()
        detail = str(exc) if isinstance(exc, (StandardReleaseDenied, ClientFlowCatalogError,
            ClientFlowReleaseSecurityDenied, ClientFlowDeploymentConflict)) else "Bestillingen kunne ikke gennemføres sikkert"
        raise HTTPException(status_code=409, detail=detail) from exc
