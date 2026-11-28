"""Explicit superadmin forward-update orders for the physically accepted 1.4 baseline.

Standard orders never promote a catalog, open a control flag, run historical
plans, perform fresh installation or authorize a downgrade. The separate
pre-cutover pilot endpoints can authorize exactly one approved Viborg1 update.
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
from ..clientflow_release_security_policy import ClientFlowReleaseSecurityDenied, require_centrally_eligible_release
from ..clientflow_pilot_1250 import (
    Pilot1250Denied, approval_lock_1250, require_pilot_holds, pilot_release, match_approved_artifact,
)
from ..clientflow_pilot_1251 import (
    Pilot1251Denied, SUCCESSOR_ID, SUCCESSOR_SEQUENCE,
    require_closed_baseline, require_retained_store, successor_release,
    approval_lock_1251, successor_snapshot,
)
from ..clientflow_release_admin_models import ClientFlowRolloutTarget, ClientFlowRolloutWave
from ..native_rdp_admission import matches_completed_update
from ..clientflow_releases import (
    ClientFlowArtifactUnavailable, ClientFlowCatalogError, deployment_release_snapshot,
    load_catalog, resolve_release, validate_release_compatibility,
)
from ..clientflow_standard_release import (
    BASELINE_ID, BASELINE_VERSION, BASELINE_SEQUENCE, MAX_REQUEST_CLIENTS,
    StandardReleaseDenied, require_cutover_authority, validate_baseline_catalog, validate_selection,
)
from ..clientflow_update_models import ClientFlowDeployment, ClientFlowUpdateCredential
from ..clientflow_rollout_scope import RolloutScope, require_organization_binding
from ..db import get_session
from ..models import Client
from ..system_control import lock_system_client
from .clientflow_deployments import _canonical_runtime_version, _require_deployable_client
from .clientflow_release_administration import _reauth, _require_actor, _no_store, _bound_control

router = APIRouter(prefix="/clientflow/standard-deployments", tags=["clientflow-standard-deployments"])


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: int = Field(strict=True, gt=0)
    expected_source_version: str = Field(min_length=5, max_length=40)
    expected_organization_id: int | None = Field(default=None, strict=True, gt=0)


class StandardOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_release_id: str = Field(min_length=1, max_length=160)
    expected_bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: int = Field(strict=True, ge=1)
    targets: list[Target] = Field(min_length=1, max_length=MAX_REQUEST_CLIENTS)
    organization_scope: RolloutScope | None = None
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
        target_by_id = {target.client_id: target for target in body.targets}
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
            require_organization_binding(body.organization_scope, target_by_id[client_id], client)
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
                    "reason": reason, "allow_downgrade": False,
                    "organization_scope": body.organization_scope.model_dump() if body.organization_scope else None,
                    "organization_id": client.organization_id},
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


class BaselinePilotOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: int = Field(strict=True, gt=0)
    target_release_id: str = Field(min_length=1, max_length=160)
    expected_source_version: str
    expected_bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: int = Field(strict=True, ge=1)
    confirmed_prepared: bool = Field(strict=True)
    password: str = Field(min_length=1, max_length=256)


def _pilot_client(session: Session):
    client = session.get(Client, 3)
    if client is None or client.name != "Viborg1":
        raise Pilot1250Denied("Pilotklientens identitet er ændret")
    session.refresh(client)
    _require_deployable_client(session, client)
    version = _canonical_runtime_version(session, client)
    if version != "1.3.47" or client.ubuntu_version != "26.04":
        raise Pilot1250Denied("Viborg1 skal rapportere frisk 1.3.47 og Ubuntu 26.04")
    if session.exec(select(ClientFlowDeployment.id).where(
        ClientFlowDeployment.target_release_id == BASELINE_ID
    ).limit(1)).first() is not None:
        raise Pilot1250Denied("1250-piloten er allerede bestilt; manuel revurdering kræves")
    if (active_deployment(session, client_id=3) is not None
            or unacknowledged_recovery_failure(session, client_id=3) is not None):
        raise Pilot1250Denied("Aktiv deployment eller uafklaret recovery")
    credentials = session.exec(select(ClientFlowUpdateCredential.id).where(
        ClientFlowUpdateCredential.client_id == 3,
        ClientFlowUpdateCredential.revoked_at.is_(None),
    ).limit(2)).all()
    if len(credentials) != 1:
        raise Pilot1250Denied("Entydig Update-identitet mangler")
    return client


def _pilot_snapshot(approval):
    require_centrally_eligible_release(release_id=BASELINE_ID, release_sequence=BASELINE_SEQUENCE)
    artifact = deployment_release_snapshot(pilot_release())
    match_approved_artifact(approval, artifact)
    return artifact


@router.get("/pilot/availability")
def baseline_pilot_availability(
    request: Request, response: Response, session: Session = Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    _require_actor(request, user)
    _no_store(response)
    try:
        approval = approval_lock_1250()
        control = _bound_control(session)
        require_pilot_holds(load_catalog(), control.model_dump(), control.revision)
        _pilot_client(session)
        artifact = _pilot_snapshot(approval)
        return {"available": True, "client_id": 3, "target_release_id": BASELINE_ID,
                "source_version": "1.3.47", "bundle_sha256": artifact["bundle_sha256"],
                "revision": control.revision, "fleet_authorized": False,
                "fresh_install_authorized": False, "rollback_authorized": False}
    except (Pilot1250Denied, ClientFlowCatalogError, ClientFlowReleaseSecurityDenied, HTTPException):
        return {"available": False, "reason": "1250-pilot afventer godkendt pakke, lukket releasepolitik eller frisk klientstatus"}


@router.post("/pilot/authorize", status_code=201)
def authorize_baseline_pilot(
    body: BaselinePilotOrder, request: Request, response: Response,
    session: Session = Depends(get_session), user=Depends(get_current_superadmin_user),
):
    _require_actor(request, user)
    _no_store(response)
    try:
        if (body.client_id != 3 or body.target_release_id != BASELINE_ID
                or body.expected_source_version != "1.3.47" or body.confirmed_prepared is not True):
            raise Pilot1250Denied("Kun udtrykkeligt forberedt Viborg1/1248 → 1250 er tilladt")
        approval = approval_lock_1250()
        if body.expected_bundle_sha256 != approval["approved_bundle_sha256"]:
            raise Pilot1250Denied("Godkendt bundle er ændret")
        initial = _bound_control(session)
        require_pilot_holds(load_catalog(), initial.model_dump(), body.expected_revision)
        _reauth(request, session, user, body.password)
        artifact = _pilot_snapshot(approval)
        lock_system_client(session, 3)
        control = _bound_control(session, lock=True)
        session.refresh(control)
        require_pilot_holds(load_catalog(), control.model_dump(), body.expected_revision)
        client = _pilot_client(session)
        validate_release_compatibility(pilot_release(), current_version="1.3.47", ubuntu_version=client.ubuntu_version)
        # Local preparation is an explicit operator attestation, not remote
        # proof. The actual host activation retains all transaction guards.
        reason = "Fysisk engangspilot Viborg1: ClientFlow 1.3.47 → 1.4.0"
        deployment = create_authorized_deployment(
            session, client_id=3, requested_by_user_id=int(user.id),
            target_release_id=BASELINE_ID, target_version=BASELINE_VERSION,
            target_release_sequence=BASELINE_SEQUENCE, bundle_sha256=artifact["bundle_sha256"],
            bundle_size=artifact["bundle_size"], release_approval_reference=artifact["release_approval_reference"],
            release_candidate_sha256=artifact["release_candidate_sha256"], source_commit=artifact["source_commit"],
            allow_downgrade=False, reason=reason,
        )
        add_audit_log(
            session, action="clientflow_1250_pilot_authorized", request=request,
            actor=user, target_organization_id=client.organization_id, entity_type="clientflow_deployment",
            entity_id=3, entity_label="Viborg1 → ClientFlow 1.4.0/1250",
            severity="critical", is_critical=True, details={
                "deployment_id": deployment.id, "release_id": BASELINE_ID,
                "bundle_sha256": artifact["bundle_sha256"], "source_commit": artifact["source_commit"],
                "approval_reference": artifact["release_approval_reference"], "policy_revision": control.revision,
                "local_preparation_attested_by_operator": True, "physical_acceptance": False,
                "fleet_authorized": False, "fresh_install_authorized": False, "rollback_authorized": False,
            },
        )
        session.commit()
        return {"deployment_id": deployment.id, "client_id": 3, "target_release_id": BASELINE_ID,
                "state": "authorized", "fleet_authorized": False, "fresh_install_authorized": False,
                "rollback_authorized": False}
    except HTTPException:
        session.rollback()
        raise
    except ClientFlowArtifactUnavailable as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (Pilot1250Denied, ClientFlowCatalogError, ClientFlowReleaseSecurityDenied,
            ClientFlowDeploymentConflict, IntegrityError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="1250-pilotbestillingen kunne ikke verificeres") from exc



class SuccessorPilotOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: int = Field(strict=True, gt=0)
    target_release_id: str = Field(min_length=1, max_length=160)
    expected_source_version: str
    expected_bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: int = Field(strict=True, ge=1)
    confirmed_prepared: bool = Field(strict=True)
    password: str = Field(min_length=1, max_length=256)


def _successor_client(session: Session):
    if list(session.exec(select(Client.id).order_by(Client.id).limit(2)).all()) != [3]:
        raise Pilot1251Denied("1251 kræver den verificerede en-klient-installation")
    client = session.get(Client, 3)
    if client is None or client.name != "Viborg1" or client.ubuntu_version != "26.04":
        raise Pilot1251Denied("Pilotklientens identitet eller Ubuntu-platform er ændret")
    session.refresh(client)
    _require_deployable_client(session, client)
    if _canonical_runtime_version(session, client) != BASELINE_VERSION:
        raise Pilot1251Denied("Viborg1 skal rapportere frisk ClientFlow 1.4.0")
    credentials = session.exec(select(ClientFlowUpdateCredential.id).where(
        ClientFlowUpdateCredential.client_id == 3,
        ClientFlowUpdateCredential.revoked_at.is_(None),
    ).limit(2)).all()
    if len(credentials) != 1:
        raise Pilot1251Denied("Entydig Update-identitet mangler")
    if (session.exec(select(ClientFlowDeployment.id).where(
            ClientFlowDeployment.completed_at.is_(None)).limit(1)).first() is not None
            or unacknowledged_recovery_failure(session, client_id=3) is not None
            or session.exec(select(ClientFlowDeployment.id).where(
                ClientFlowDeployment.target_release_id == SUCCESSOR_ID).limit(1)).first() is not None):
        raise Pilot1251Denied("Aktiv deployment, tidligere 1251-bestilling eller uafklaret recovery")
    if (session.exec(select(ClientFlowRolloutTarget.id).where(
            ClientFlowRolloutTarget.state.in_(["approved", "consumed"])).limit(1)).first() is not None
            or session.exec(select(ClientFlowRolloutWave.id).where(
                ClientFlowRolloutWave.state.in_(["approved", "running", "completed", "failed"])).limit(1)).first() is not None):
        raise Pilot1251Denied("Uventet udrulningsautorisation")
    prior = session.exec(select(ClientFlowDeployment).where(
        ClientFlowDeployment.client_id == 3,
    ).order_by(ClientFlowDeployment.requested_at.desc(), ClientFlowDeployment.id.desc()).limit(1)).first()
    approved = approval_lock_1250()
    baseline = {"target_release_id": BASELINE_ID, "target_version": BASELINE_VERSION,
                "target_release_sequence": BASELINE_SEQUENCE,
                "bundle_sha256": approved["approved_bundle_sha256"],
                "bundle_size": approved["approved_bundle_size"],
                "release_approval_reference": approved["approval_reference"],
                "release_candidate_sha256": approved["candidate_sha256"],
                "source_commit": approved["source_commit"]}
    if not matches_completed_update(prior, client_id=3, artifact=baseline):
        raise Pilot1251Denied("Eksakt gennemført 1250-deployment mangler")
    return client


def _successor_authority(session: Session, *, revision: int, lock: bool):
    control = _control(session, lock=lock)
    if lock:
        session.refresh(control)
    require_closed_baseline(load_catalog(), control.model_dump(), revision)
    require_centrally_eligible_release(release_id=BASELINE_ID, release_sequence=BASELINE_SEQUENCE)
    require_centrally_eligible_release(release_id=SUCCESSOR_ID, release_sequence=SUCCESSOR_SEQUENCE)
    return control


@router.get("/successor-pilot/availability")
def successor_pilot_availability(
    request: Request, response: Response, session: Session = Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    _require_actor(request, user)
    _no_store(response)
    try:
        revision = _control(session, lock=False).revision
        _successor_authority(session, revision=revision, lock=False)
        _successor_client(session)
        artifact = require_retained_store()
        return {"available": True, "client_id": 3, "target_release_id": SUCCESSOR_ID,
                "source_version": BASELINE_VERSION, "bundle_sha256": artifact["bundle_sha256"],
                "revision": revision, "fleet_authorized": False,
                "fresh_install_authorized": False, "rollback_authorized": False}
    except (Pilot1251Denied, Pilot1250Denied, StandardReleaseDenied, ClientFlowCatalogError,
            ClientFlowReleaseSecurityDenied, HTTPException, OSError):
        return {"available": False, "reason": "1251 afventer lukket 1250-reference, tre verificerede TAR-filer og frisk klientstatus"}


@router.post("/successor-pilot/authorize", status_code=201)
def authorize_successor_pilot(
    body: SuccessorPilotOrder, request: Request, response: Response,
    session: Session = Depends(get_session), user=Depends(get_current_superadmin_user),
):
    _require_actor(request, user)
    _no_store(response)
    try:
        if (body.client_id != 3 or body.target_release_id != SUCCESSOR_ID
                or body.expected_source_version != BASELINE_VERSION or body.confirmed_prepared is not True
                or body.expected_bundle_sha256 != approval_lock_1251()["approved_bundle_sha256"]):
            raise Pilot1251Denied("Kun udtrykkeligt forberedt Viborg1/1250 → 1251 er tilladt")
        _successor_authority(session, revision=body.expected_revision, lock=False)
        _reauth(request, session, user, body.password)
        artifact = require_retained_store()
        lock_system_client(session, 3)
        control = _successor_authority(session, revision=body.expected_revision, lock=True)
        client = _successor_client(session)
        validate_release_compatibility(successor_release(), current_version=BASELINE_VERSION,
                                       ubuntu_version=client.ubuntu_version)
        # Recheck the exact approved order after the client/control locks.
        if artifact != successor_snapshot() or body.expected_bundle_sha256 != artifact["bundle_sha256"]:
            raise Pilot1251Denied("Godkendt bundle er ændret")
        deployment = create_authorized_deployment(
            session, client_id=3, requested_by_user_id=int(user.id), **artifact,
            allow_downgrade=False, reason="Fysisk engangspilot Viborg1: ClientFlow 1.4.0 → 1.4.1",
        )
        add_audit_log(
            session, action="clientflow_1251_pilot_authorized", request=request,
            actor=user, target_organization_id=client.organization_id, entity_type="clientflow_deployment",
            entity_id=3, entity_label="Viborg1 → ClientFlow 1.4.1/1251",
            severity="critical", is_critical=True, details={
                "client_id": 3, "deployment_id": deployment.id, **artifact,
                "policy_revision": control.revision, "local_preparation_attested_by_operator": True,
                "physical_acceptance": False, "fleet_authorized": False,
                "fresh_install_authorized": False, "rollback_authorized": False,
            },
        )
        session.commit()
        return {"deployment_id": deployment.id, "client_id": 3, "target_release_id": SUCCESSOR_ID,
                "state": "authorized", "fleet_authorized": False, "fresh_install_authorized": False,
                "rollback_authorized": False}
    except HTTPException:
        session.rollback()
        raise
    except ClientFlowArtifactUnavailable as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (Pilot1251Denied, Pilot1250Denied, StandardReleaseDenied, ClientFlowCatalogError,
            ClientFlowReleaseSecurityDenied, ClientFlowDeploymentConflict, IntegrityError, OSError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="1251-pilotbestillingen kunne ikke verificeres") from exc


# Version-independent managed forward order. The existing closed standard
# remains the rollback predecessor until the reviewed policy transition.
@router.get("/managed/availability")
def managed_deployment_availability(
    request: Request, response: Response, session: Session = Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    from .. import clientflow_managed_rollout as managed
    _require_actor(request, user)
    _no_store(response)
    try:
        policy = managed.current_policy()
        control = managed.require_control(session, policy)
        artifact = managed.require_store(policy)
        return {"available": True, "target_release_id": artifact["target_release_id"],
                "target_version": artifact["target_version"], "source_version": policy.source["target_version"],
                "bundle_sha256": artifact["bundle_sha256"], "revision": control.revision,
                "max_clients": MAX_REQUEST_CLIENTS, "rollback_available": False}
    except (ValueError, RuntimeError, OSError):
        return {"available": False, "reason": "Managed releaseautorisation eller lager afventer verificering",
                "rollback_available": False}


@router.post("/managed", status_code=201)
def authorize_managed_deployments(
    body: StandardOrder, request: Request, response: Response,
    session: Session = Depends(get_session), user=Depends(get_current_superadmin_user),
):
    from .. import clientflow_managed_rollout as managed
    _require_actor(request, user)
    _no_store(response)
    try:
        policy = managed.current_policy()
        managed.require(body.confirmed is True and body.target_release_id == policy.target["target_release_id"]
                        and body.expected_bundle_sha256 == policy.target["bundle_sha256"]
                        and body.expected_revision == policy.revision, "Releasebestilling matcher ikke politik")
        selected = managed.select_targets(policy, body.targets)
        managed.require_control(session, policy)
        _reauth(request, session, user, body.password)
        artifact = managed.require_store(policy)
        for target in selected:
            lock_system_client(session, target.client_id)
        control = managed.require_control(session, policy, lock=True)
        verified = []
        for target in selected:
            client = managed.require_client(session, target.client_id, policy)
            require_organization_binding(body.organization_scope, target, client)
            verified.append(client)
        rows = []
        for client in verified:
            reason = f"ClientFlow-opdatering {policy.source['target_version']} → {artifact['target_version']}"
            deployment = create_authorized_deployment(session, client_id=client.id,
                requested_by_user_id=int(user.id), **artifact, allow_downgrade=False,
                reason=reason, managed_authority=managed.MANAGED_AUTHORITY)
            add_audit_log(session, action="clientflow_managed_deployment_authorized", request=request,
                actor=user, target_organization_id=client.organization_id, entity_type="clientflow_deployment",
                entity_id=client.id, entity_label=f"{client.name} → {artifact['target_version']}",
                severity="warning", details={"deployment_id": deployment.id, **artifact,
                    "source_release_id": policy.source["target_release_id"], "policy_revision": control.revision,
                    "organization_scope": body.organization_scope.model_dump() if body.organization_scope else None,
                    "organization_id": client.organization_id, "allow_downgrade": False})
            rows.append({"deployment_id": deployment.id, "client_id": client.id, "state": "authorized"})
        session.commit()
        return {"target_release_id": artifact["target_release_id"], "deployments": rows}
    except HTTPException:
        session.rollback()
        raise
    except (ValueError, RuntimeError, IntegrityError, OSError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Managed bestilling kunne ikke verificeres") from exc
