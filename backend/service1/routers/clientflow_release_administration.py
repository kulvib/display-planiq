"""Default-closed ClientFlow planning (61B-1).

Review, pause and cancellation are strictly PLAN intentions: target rows are
never approved or consumed here, and no deployment/fresh-install handler
reads these decisions as authorization. Gates stay closed until a separately
reviewed physical pilot and cutover.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_
from sqlmodel import Session, select

from ..audit import add_audit_log, commit_audit_log
from ..auth import get_current_superadmin_user, verify_password
from ..clientflow_pilot_1245 import _approved_lock, ClientFlowPilot1245Denied
from ..clientflow_release_readiness import planning_readiness
from ..clientflow_release_pilot_stage_1246 import staged_pilot_summary, PilotStageDenied
from ..clientflow_pilot_1246 import ClientFlowPilot1246Denied
from ..clientflow_release_admin_models import (
    ClientFlowReleaseControl,
    ClientFlowRolloutTarget,
    ClientFlowRolloutWave,
    ClientFlowPhysicalAcceptance,
)
from ..clientflow_releases import ClientFlowCatalogError, load_catalog, compare_versions
from ..db import get_session
from ..client_domain_models import ClientDomainCredential, ClientDomainStatus
from ..models import Client, Organization, User
from ..rate_limit import assert_key_not_limited, clear_key_rate_limit, record_key_attempt

router = APIRouter(prefix="/clientflow/release-administration", tags=["clientflow-release-administration"])
_BUNDLE_SHA256 = "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
_RELEASE_ID = "clientflow-1.3.44-seq-1245"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _canonical_status_version(raw_version: str | None, active_credential_id: str | None) -> str | None:
    """Accept only versions reported by an active, matching Status credential.

    Keep this aligned with the deploy controller's benign v/V normalization;
    never synthesize a version from the legacy Client table.
    """
    if active_credential_id is None or not isinstance(raw_version, str):
        return None
    version = raw_version.strip().lstrip("vV")
    return version if re.fullmatch(r"\d+\.\d+\.\d+", version) else None


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _bound_control(session: Session, *, lock: bool = False) -> ClientFlowReleaseControl:
    query = select(ClientFlowReleaseControl).where(ClientFlowReleaseControl.id == 1)
    if lock:
        query = query.with_for_update()
    row = session.exec(query).first()
    if row is None:
        raise HTTPException(status_code=503, detail="Releaseadministrationens sikkerhedspolitik mangler")
    try:
        catalog = load_catalog()
        approval = _approved_lock()
    except (ClientFlowCatalogError, ClientFlowPilot1245Denied) as exc:
        raise HTTPException(status_code=503, detail="Releasekatalogets kryptografiske autoritet er utilgængelig") from exc
    stable = catalog.get("releases")
    if (
        not isinstance(stable, list)
        or len(stable) != 1
        or catalog.get("latest_stable") != catalog.get("default_install_version")
        or stable[0].get("status") != "stable"
        or stable[0].get("install_modes") != ["fresh_install", "in_place_update"]
        or stable[0].get("rollback_allowed") is not False
        or row.stable_release_id != stable[0].get("release_id")
        or row.stable_bundle_sha256 != approval.get("approved_bundle_sha256")
        or row.stable_bundle_sha256 != _BUNDLE_SHA256
        or row.stable_release_id != _RELEASE_ID
        or _SHA256.fullmatch(row.stable_bundle_sha256) is None
        or row.revision < 1
        or row.cutover_enabled is not False
        or row.fresh_install_open is not False
        or row.fleet_open is not False
    ):
        raise HTTPException(status_code=503, detail="Releaseadministrationen er endnu ikke godkendt til cutover")
    # Do not conceal a drifted/authorized state behind a hardcoded false in
    # the admin UI. This remains a strictly inert planning control plane.
    if (
        session.exec(select(ClientFlowRolloutTarget.id).where(
            ClientFlowRolloutTarget.state.in_(["approved", "consumed"])
        ).limit(1)).first() is not None
        or session.exec(select(ClientFlowRolloutWave.id).where(
            ClientFlowRolloutWave.state.in_(["approved", "running", "completed", "failed"])
        ).limit(1)).first() is not None
        or session.exec(select(ClientFlowPhysicalAcceptance.id).limit(1)).first() is not None
    ):
        raise HTTPException(status_code=503, detail="Uventet udrulningsautorisation eller pilotaccept; planlægning spærret")
    return row


def _require_actor(request: Request, user: User) -> None:
    actor = getattr(request.state, "real_actor", None) or user
    if getattr(request.state, "impersonation_active", False) or actor.id != user.id:
        raise HTTPException(status_code=409, detail="Afslut bruger-skift før releaseadministration")
    if not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Kun superadministrator")


def _reauth(request: Request, session: Session, user: User, password: str) -> None:
    _require_actor(request, user)
    key = f"user:{int(user.id)}"
    assert_key_not_limited(
        bucket="clientflow-release-admin-password", key=key,
        max_attempts=5, window_seconds=300,
        detail="For mange mislykkede godkendelser; prøv senere",
    )
    if not verify_password(password, user.hashed_password):
        record_key_attempt(bucket="clientflow-release-admin-password", key=key, window_seconds=300)
        commit_audit_log(
            session, action="clientflow_release_admin_reauthentication_failed",
            request=request, actor=user, target_user=user,
            entity_type="clientflow_release_control", entity_id=1,
            status="failed", severity="warning", details={"reason": "wrong_password"},
        )
        raise HTTPException(status_code=403, detail="Adgangskoden er forkert")
    clear_key_rate_limit(bucket="clientflow-release-admin-password", key=key)


class RolloutDraftCreate(BaseModel):
    kind: str = Field(pattern="^(pilot|controlled)$")
    client_ids: list[int] = Field(min_length=1, max_length=25)
    source_version: str = Field(min_length=5, max_length=40, pattern=r"^\d+\.\d+\.\d+$")
    reason: str = Field(min_length=12, max_length=500)
    expires_in_hours: int = Field(ge=1, le=168)
    expected_revision: int = Field(ge=1)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        clean = " ".join(value.split()).strip()
        if len(clean) < 12:
            raise ValueError("Begrundelse skal være mindst 12 tegn")
        return clean

    @field_validator("client_ids")
    @classmethod
    def unique_clients(cls, values: list[int]) -> list[int]:
        if any(type(v) is not int or v <= 0 for v in values) or len(values) != len(set(values)):
            raise ValueError("Klient-ID'er skal være positive, entydige heltal")
        return values


class PlanDecision(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    expected_revision: int = Field(ge=1)



class RolloutPreviewRequest(BaseModel):
    """Read-only plan validation. Never an installation or a release approval."""

    client_ids: list[int] = Field(min_length=1, max_length=25)
    source_version: str = Field(min_length=5, max_length=40, pattern=r"^\d+\.\d+\.\d+$")
    target_release_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=1)

    @field_validator("client_ids")
    @classmethod
    def unique_clients(cls, values: list[int]) -> list[int]:
        if any(type(v) is not int or v <= 0 for v in values) or len(values) != len(set(values)):
            raise ValueError("Klient-ID'er skal være positive, entydige heltal")
        return values


def _verify_live_planning_sources(session: Session, client_ids: list[int], source_version: str) -> None:
    """One bounded Status-domain query. No legacy version fallback or client writes.

    The proof is valid ONLY for creating an inert plan. A future installation
    must perform a separate, fresh client/credential/version attestation.
    """
    if compare_versions(source_version, "1.3.44") >= 0:
        raise HTTPException(status_code=409, detail="Kildeversionen skal være ældre end den stabile release")
    rows = session.exec(
        select(
            Client.id, Client.status, Client.deleted_at,
            ClientDomainStatus.agent_version, ClientDomainCredential.id,
        )
        .join(
            ClientDomainStatus,
            and_(ClientDomainStatus.client_id == Client.id,
                 ClientDomainStatus.domain == "status"),
            isouter=True,
        )
        .join(
            ClientDomainCredential,
            and_(ClientDomainCredential.id == ClientDomainStatus.credential_id,
                 ClientDomainCredential.client_id == Client.id,
                 ClientDomainCredential.domain == "status",
                 ClientDomainCredential.revoked_at.is_(None)),
            isouter=True,
        )
        .where(Client.id.in_(client_ids))
    ).all()
    if len(rows) != len(client_ids):
        raise HTTPException(status_code=409, detail="En eller flere valgte klienter findes ikke længere")
    for client_id, state, deleted_at, version, credential_id in rows:
        if state != "approved" or deleted_at is not None:
            raise HTTPException(status_code=409, detail="En valgt klient er ikke længere aktiv og godkendt")
        if _canonical_status_version(version, credential_id) != source_version:
            raise HTTPException(status_code=409, detail="Klientens senest rapporterede version har ændret sig; opdater listen")


@router.post("/preview")
def preview_rollout_plan(
    payload: RolloutPreviewRequest, request: Request, response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_superadmin_user),
):
    """Bounded server-side preview; cannot create an approval, plan or command."""
    _require_actor(request, user)
    _no_store(response)
    control = _bound_control(session)
    if control.revision != payload.expected_revision or control.stable_release_id != payload.target_release_id:
        raise HTTPException(status_code=409, detail="Releasepolitikken har ændret sig; hent den igen")
    _verify_live_planning_sources(session, payload.client_ids, payload.source_version)
    return {
        "planning_eligible": True,
        "deployment_authorized": False,
        "release_approved_for_deployment": False,
        "client_ids": sorted(payload.client_ids),
        "source_version": payload.source_version,
        "target_release_id": control.stable_release_id,
        "policy_revision": control.revision,
        "kind": "pilot" if len(payload.client_ids) == 1 else "controlled",
    }


def _wave_json(row: ClientFlowRolloutWave, client_ids: list[int]) -> dict:
    return {
        "id": row.id, "kind": row.kind, "state": row.state,
        "release_id": row.release_id, "bundle_sha256": row.bundle_sha256,
        "source_version": row.source_version, "client_ids": client_ids,
        "reason": row.reason, "created_at": row.created_at,
        "expires_at": row.expires_at, "revision": row.revision,
        "reviewed_for_planning": row.approved_at is not None,
        "reviewed_at": row.approved_at,
        # A reviewed plan is NEVER deployment authorization (target stays draft).
        "deployment_authorized": False,
    }


@router.get("")
def read_release_administration(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_superadmin_user),
):
    _require_actor(request, user)
    _no_store(response)
    control = _bound_control(session)
    # A read-only, fail-closed gate matrix reuses the already verified
    # singleton/catalog; it never creates an extra DB query on kiosk hotpaths.
    release_readiness = planning_readiness(
        release_id=control.stable_release_id,
        bundle_sha256=control.stable_bundle_sha256,
        catalog=load_catalog(),
        approval_bundle_sha256=_approved_lock()["approved_bundle_sha256"],
        control_revision=control.revision,
        cutover_enabled=control.cutover_enabled,
        fleet_open=control.fleet_open,
        fresh_install_open=control.fresh_install_open,
        physical_acceptance=False,
    )
    try:
        staged_pilot = staged_pilot_summary(active_catalog=load_catalog())
    except (PilotStageDenied, ClientFlowPilot1246Denied) as exc:
        raise HTTPException(status_code=503, detail="1246-kandidatens godkendte kildestatus kan ikke verificeres") from exc
    waves = session.exec(
        select(ClientFlowRolloutWave)
        .order_by(ClientFlowRolloutWave.created_at.desc())
        .limit(50)
    ).all()
    if waves:
        targets = session.exec(
            select(ClientFlowRolloutTarget)
            .where(ClientFlowRolloutTarget.wave_id.in_([w.id for w in waves]))
            .order_by(ClientFlowRolloutTarget.client_id)
        ).all()
    else:
        targets = []
    ids: dict[str, list[int]] = {}
    for target in targets:
        ids.setdefault(target.wave_id, []).append(target.client_id)
    # One bounded, read-only inventory query on explicit superadmin refresh.
    # Client.client_version is a legacy column. The Status agent writes the
    # canonical version to client_domain_status; other Client pages project it
    # only in-memory. Never persist that projection or infer it from a wave.
    # Also verify that the status row belongs to an active, matching credential
    # so revoked or cross-client telemetry cannot appear as a selectable version.
    inventory_rows = session.exec(
        select(
            Client.id, Client.name, Client.locality, Client.organization_id,
            ClientDomainStatus.agent_version, ClientDomainStatus.reported_at,
            Organization.name.label("organization_name"),
            ClientDomainCredential.id.label("active_status_credential_id"),
        )
        .join(Organization, Client.organization_id == Organization.id, isouter=True)
        .join(
            ClientDomainStatus,
            and_(ClientDomainStatus.client_id == Client.id,
                 ClientDomainStatus.domain == "status"),
            isouter=True,
        )
        .join(
            ClientDomainCredential,
            and_(ClientDomainCredential.id == ClientDomainStatus.credential_id,
                 ClientDomainCredential.client_id == Client.id,
                 ClientDomainCredential.domain == "status",
                 ClientDomainCredential.revoked_at.is_(None)),
            isouter=True,
        )
        .where(Client.status == "approved", Client.deleted_at.is_(None))
        .order_by(Organization.name, Client.name, Client.id)
        .limit(1001)
    ).all()
    available_clients = [
        {
            "id": row[0], "name": row[1], "locality": row[2],
            "organization_id": row[3], "organization_name": row[6],
            "reported_version": _canonical_status_version(row[4], row[7]),
            "version_reported_at": row[5] if row[7] is not None else None,
        }
        for row in inventory_rows[:1000]
    ]
    return {
        "available_clients": available_clients,
        "client_inventory_complete": len(inventory_rows) <= 1000,
        "available_releases": [{
            "release_id": control.stable_release_id,
            "version": "1.3.44", "status": "stable",
            "bundle_sha256": control.stable_bundle_sha256,
            "deployment_authorized": False,
        }],
        "phase": "additive_draft_only",  # 61A compatibility: all targets remain drafts.
        "planning_review_available": True,
        "authorization_active": False,
        "stable_release_id": control.stable_release_id,
        "stable_version": "1.3.44",
        "bundle_sha256": control.stable_bundle_sha256,
        "fresh_install_open": False,
        "fleet_open": False,
        "cutover_enabled": False,
        "physical_pilot_accepted": False,
        "revision": control.revision,
        "waves": [_wave_json(w, ids.get(w.id, [])) for w in waves],
        "release_readiness": release_readiness,
        "staged_pilot_candidate": staged_pilot,
    }


@router.post("/drafts", status_code=201)
def create_rollout_draft(
    payload: RolloutDraftCreate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_superadmin_user),
):
    _no_store(response)
    _reauth(request, session, user, payload.password)
    control = _bound_control(session, lock=True)
    if control.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Releasepolitikken har ændret sig; hent den igen")
    # All candidates are only PLANS. No hard-coded pilot identity: operators
    # must verify the actual physical device at the separate pilot gate.
    if payload.kind == "pilot" and len(payload.client_ids) != 1:
        raise HTTPException(status_code=409, detail="En pilotplan må kun have én klient")
    if payload.kind == "controlled" and len(payload.client_ids) < 2:
        raise HTTPException(status_code=409, detail="En kontrolleret bølge kræver mindst to klienter")
    # Identical authoritative verification is repeated under the locked policy,
    # even if the UI preview passed earlier. A preview is never authorization.
    _verify_live_planning_sources(session, payload.client_ids, payload.source_version)
    now = _utcnow()
    wave = ClientFlowRolloutWave(
        id=str(uuid4()), kind=payload.kind, state="draft",
        release_id=control.stable_release_id, bundle_sha256=control.stable_bundle_sha256,
        source_version=payload.source_version, reason=payload.reason,
        created_by_user_id=int(user.id), created_at=now,
        expires_at=now + timedelta(hours=payload.expires_in_hours), revision=1,
    )
    session.add(wave)
    # The target rows reference this wave through a non-deferrable FK.  Without
    # an ORM relationship SQLAlchemy may flush targets before their parent,
    # which SQLite (FK checks off by default) misses but PostgreSQL rejects.
    # Flush ONLY the parent now; the transaction still commits atomically below.
    session.flush()
    for client_id in payload.client_ids:
        session.add(ClientFlowRolloutTarget(
            id=str(uuid4()), wave_id=wave.id, client_id=client_id,
            state="draft", created_at=now, expires_at=wave.expires_at,
        ))
    add_audit_log(
        session, action="clientflow_rollout_draft_created", request=request,
        actor=user, entity_type="clientflow_rollout_wave", entity_label=wave.id,
        severity="warning", details={
            "wave_id": wave.id, "kind": wave.kind,
            "release_id": wave.release_id, "bundle_sha256": wave.bundle_sha256,
            "client_ids": payload.client_ids, "expiry": wave.expires_at.isoformat(),
            "phase": "inert_draft_only",
        },
    )
    session.commit()
    return _wave_json(wave, payload.client_ids)


def _locked_plan(session: Session, wave_id: str, expected_revision: int, control: ClientFlowReleaseControl):
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", wave_id):
        raise HTTPException(status_code=404, detail="Udrulningsplanen findes ikke")
    wave = session.exec(
        select(ClientFlowRolloutWave).where(ClientFlowRolloutWave.id == wave_id).with_for_update()
    ).first()
    if wave is None:
        raise HTTPException(status_code=404, detail="Udrulningsplanen findes ikke")
    if wave.revision != expected_revision:
        raise HTTPException(status_code=409, detail="Udrulningsplanen er ændret; hent den igen")
    if wave.release_id != control.stable_release_id or wave.bundle_sha256 != control.stable_bundle_sha256:
        raise HTTPException(status_code=409, detail="Planens release afviger fra låst stabil version")
    targets = session.exec(
        select(ClientFlowRolloutTarget)
        .where(ClientFlowRolloutTarget.wave_id == wave.id)
        .order_by(ClientFlowRolloutTarget.client_id)
        .with_for_update()
    ).all()
    if not targets or any(t.state != "draft" or t.consumed_deployment_id is not None for t in targets):
        raise HTTPException(status_code=409, detail="Planmålene er ikke længere inaktive kladder")
    return wave, targets


def _plan_audit(session: Session, request: Request, user: User, wave: ClientFlowRolloutWave, action: str, targets: list[ClientFlowRolloutTarget]):
    add_audit_log(
        session, action=action, request=request,
        actor=user, entity_type="clientflow_rollout_wave", entity_label=wave.id,
        severity="warning", details={
            "wave_id": wave.id, "revision": wave.revision,
            "state": wave.state, "client_ids": [t.client_id for t in targets],
            "release_id": wave.release_id, "bundle_sha256": wave.bundle_sha256,
            "planning_only": True, "deployment_authorized": False,
        },
    )


@router.post("/drafts/{wave_id}/review")
def review_rollout_plan(
    wave_id: str, payload: PlanDecision, request: Request, response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_superadmin_user),
):
    """Record review intent without creating approved targets or permissions."""
    _no_store(response)
    _reauth(request, session, user, payload.password)
    control = _bound_control(session, lock=True)
    wave, targets = _locked_plan(session, wave_id, payload.expected_revision, control)
    if wave.state != "draft" or wave.approved_at is not None or wave.expires_at <= _utcnow():
        raise HTTPException(status_code=409, detail="Kun en aktiv, ikke-gennemgået kladde kan gennemgås")
    for target in targets:
        client = session.get(Client, target.client_id)
        if client is None or client.status != "approved" or client.deleted_at is not None:
            raise HTTPException(status_code=409, detail="Klientens godkendelse eller status er ændret")
    # Deliberately keep wave.state='draft' and target.state='draft'.
    # Existing 61A cutover and live deployments never authorize this review.
    wave.approved_at = _utcnow()
    wave.approved_by_user_id = int(user.id)
    wave.revision += 1
    _plan_audit(session, request, user, wave, "clientflow_rollout_plan_reviewed", targets)
    session.commit()
    return {"id": wave.id, "state": wave.state, "revision": wave.revision,
            "reviewed_for_planning": True, "deployment_authorized": False}


@router.post("/drafts/{wave_id}/pause")
def pause_rollout_plan(
    wave_id: str, payload: PlanDecision, request: Request, response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_superadmin_user),
):
    _no_store(response)
    _reauth(request, session, user, payload.password)
    control = _bound_control(session, lock=True)
    wave, targets = _locked_plan(session, wave_id, payload.expected_revision, control)
    if wave.state != "draft" or wave.approved_at is None or wave.expires_at <= _utcnow():
        raise HTTPException(status_code=409, detail="Kun en gennemgået, aktiv plan kan sættes på pause")
    wave.state = "paused"
    wave.revision += 1
    _plan_audit(session, request, user, wave, "clientflow_rollout_plan_paused", targets)
    session.commit()
    return {"id": wave.id, "state": "paused", "revision": wave.revision, "deployment_authorized": False}


@router.post("/drafts/{wave_id}/resume")
def resume_rollout_plan(
    wave_id: str, payload: PlanDecision, request: Request, response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_superadmin_user),
):
    _no_store(response)
    _reauth(request, session, user, payload.password)
    control = _bound_control(session, lock=True)
    wave, targets = _locked_plan(session, wave_id, payload.expected_revision, control)
    if wave.state != "paused" or wave.approved_at is None or wave.expires_at <= _utcnow():
        raise HTTPException(status_code=409, detail="Kun en gyldig, pauset plan kan genoptages")
    for target in targets:
        client = session.get(Client, target.client_id)
        if client is None or client.status != "approved" or client.deleted_at is not None:
            raise HTTPException(status_code=409, detail="Klientens godkendelse eller status er ændret")
    wave.state = "draft"  # NEVER approved: this is still an inert reviewed plan.
    wave.revision += 1
    _plan_audit(session, request, user, wave, "clientflow_rollout_plan_resumed", targets)
    session.commit()
    return {"id": wave.id, "state": "draft", "revision": wave.revision,
            "reviewed_for_planning": True, "deployment_authorized": False}


@router.post("/drafts/{wave_id}/cancel")
def cancel_rollout_draft(
    wave_id: str, payload: PlanDecision, request: Request, response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_superadmin_user),
):
    _no_store(response)
    _reauth(request, session, user, payload.password)
    control = _bound_control(session, lock=True)
    wave, targets = _locked_plan(session, wave_id, payload.expected_revision, control)
    if wave.state not in ("draft", "paused"):
        raise HTTPException(status_code=409, detail="Kun en inaktiv, uforbrugt plan kan annulleres")
    wave.state = "cancelled"
    wave.revision += 1
    for target in targets:
        target.state = "revoked"
    _plan_audit(session, request, user, wave, "clientflow_rollout_draft_cancelled", targets)
    session.commit()
    return {"id": wave.id, "state": "cancelled", "revision": wave.revision,
            "deployment_authorized": False}
