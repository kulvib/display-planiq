"""Default-closed ClientFlow release administration foundation (phase A).

The controls are deliberately NOT wired into deployment/fresh-install routes yet.
No HTTP endpoint approves a rollout, flips cutover, or records physical acceptance.
An existing Render pilot flag is still needed until the separately audited cutover.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from ..audit import add_audit_log, commit_audit_log
from ..auth import get_current_superadmin_user, verify_password
from ..clientflow_pilot_1245 import _approved_lock, ClientFlowPilot1245Denied
from ..clientflow_release_admin_models import (
    ClientFlowReleaseControl,
    ClientFlowRolloutTarget,
    ClientFlowRolloutWave,
)
from ..clientflow_releases import ClientFlowCatalogError, load_catalog
from ..db import get_session
from ..models import Client, User
from ..rate_limit import assert_key_not_limited, clear_key_rate_limit, record_key_attempt

router = APIRouter(prefix="/clientflow/release-administration", tags=["clientflow-release-administration"])
_BUNDLE_SHA256 = "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
_RELEASE_ID = "clientflow-1.3.44-seq-1245"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    source_version: str = Field(min_length=5, max_length=40)
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


class CancelDraft(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    expected_revision: int = Field(ge=1)


def _wave_json(row: ClientFlowRolloutWave, client_ids: list[int]) -> dict:
    return {
        "id": row.id, "kind": row.kind, "state": row.state,
        "release_id": row.release_id, "bundle_sha256": row.bundle_sha256,
        "source_version": row.source_version, "client_ids": client_ids,
        "reason": row.reason, "created_at": row.created_at,
        "expires_at": row.expires_at, "revision": row.revision,
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
    return {
        "phase": "additive_draft_only",
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
    # Drafts never authorize deployment. Before physical acceptance the only
    # permissible draft pilot is Viborg1 1244->1245; fleet plans may be drafted
    # but cannot be approved or consumed in this phase.
    if payload.kind == "pilot" and payload.client_ids != [3]:
        raise HTTPException(status_code=409, detail="Første pilot er låst til Viborg1 (klient-ID 3)")
    if payload.kind == "pilot" and payload.source_version != "1.3.43":
        raise HTTPException(status_code=409, detail="Viborg1-pilot kræver kilderelease 1244")
    if payload.kind == "controlled" and len(payload.client_ids) > 25:
        raise HTTPException(status_code=400, detail="Maksimalt 25 klienter per bølge")
    for client_id in payload.client_ids:
        client = session.get(Client, client_id)
        if client is None or client.status != "approved" or client.deleted_at is not None:
            raise HTTPException(status_code=409, detail="En klient er ikke aktiv og godkendt")
    now = _utcnow()
    wave = ClientFlowRolloutWave(
        id=str(uuid4()), kind=payload.kind, state="draft",
        release_id=control.stable_release_id, bundle_sha256=control.stable_bundle_sha256,
        source_version=payload.source_version, reason=payload.reason,
        created_by_user_id=int(user.id), created_at=now,
        expires_at=now + timedelta(hours=payload.expires_in_hours), revision=1,
    )
    session.add(wave)
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


@router.post("/drafts/{wave_id}/cancel")
def cancel_rollout_draft(
    wave_id: str, payload: CancelDraft, request: Request, response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_superadmin_user),
):
    _no_store(response)
    _reauth(request, session, user, payload.password)
    _bound_control(session, lock=True)
    wave = session.exec(
        select(ClientFlowRolloutWave).where(ClientFlowRolloutWave.id == wave_id).with_for_update()
    ).first()
    if wave is None:
        raise HTTPException(status_code=404, detail="Udrulningskladde findes ikke")
    if wave.state != "draft" or wave.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Kun en uændret kladde kan annulleres")
    targets = session.exec(select(ClientFlowRolloutTarget).where(ClientFlowRolloutTarget.wave_id == wave.id)).all()
    if any(target.state != "draft" for target in targets):
        raise HTTPException(status_code=409, detail="Kladde indeholder ikke-draft autorisationer")
    wave.state = "cancelled"
    wave.revision += 1
    for target in targets:
        target.state = "revoked"
    add_audit_log(
        session, action="clientflow_rollout_draft_cancelled", request=request,
        actor=user, entity_type="clientflow_rollout_wave", entity_label=wave.id,
        severity="warning", details={"wave_id": wave.id, "new_state": "cancelled"},
    )
    session.commit()
    return {"id": wave.id, "state": "cancelled", "revision": wave.revision}
