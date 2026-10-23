"""Superadmin issuance, revocation and DPoP-authenticated outcome of signed manual rollbacks.

Feature is OFF by default; no unprovisioned host or old release is activated.
"""
from __future__ import annotations

from datetime import datetime, timezone
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError

from clientflow_release_format.rollback_permit import (
    PURPOSE,
    RELEASE_RE,
    SIGNED_ROLLBACK_MIN_SOURCE_SEQUENCE,
    RollbackPermitError,
    reason_hash,
)
from ..audit import add_audit_log
from ..auth import get_current_superadmin_user, _require_session_security_password
from ..client_presence import load_client_presence
from ..clientflow_deployments import active_deployment
from ..clientflow_release_security_policy import (
    ClientFlowReleaseSecurityDenied, read_release_security_policy,
    require_centrally_eligible_release,
)
from ..clientflow_releases import load_catalog
from ..clientflow_rollback_models import ClientFlowRollbackEvent, ClientFlowRollbackPermit
from ..clientflow_rollback_signing import RollbackSigningUnavailable, _signing_key, enabled, sign_permit
from ..clientflow_update_auth import active_update_credential, authenticate_update_request, ClientFlowUpdateAuthError, http_auth_error
from ..db import get_session
from ..models import AuditLog, Client
from ..system_control import active_system_command, lock_system_client

router = APIRouter(tags=["clientflow-rollbacks"])


class PermitRequest(BaseModel):
    from_release_id: str = PydanticField(min_length=18, max_length=160)
    to_release_id: str = PydanticField(min_length=18, max_length=160)
    reason: str = PydanticField(min_length=3, max_length=500)
    password: str = PydanticField(min_length=1, max_length=256)


class PermitIssued(BaseModel):
    permit_id: str
    signed_permit: str
    expires_at: datetime


class RollbackReport(BaseModel):
    event_id: str = PydanticField(min_length=36, max_length=36)
    outcome: str
    occurred_at: datetime | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sequence(release_id: str) -> int:
    m = RELEASE_RE.fullmatch(release_id)
    if m is None:
        raise HTTPException(status_code=400, detail="Rollback release-id er ugyldigt")
    return int(m.group(1))


def _provenance(session: Session, client_id: int, release_id: str) -> tuple[str, str] | None:
    """Only previously backend-verified, client-specific immutable provenance."""
    from ..clientflow_update_models import ClientFlowDeployment
    deployments = session.exec(
        select(ClientFlowDeployment).where(
            ClientFlowDeployment.client_id == client_id,
            ClientFlowDeployment.target_release_id == release_id,
            ClientFlowDeployment.state == "succeeded",
        ).order_by(ClientFlowDeployment.completed_at.desc())
    ).all()
    if deployments:
        d = deployments[0]
        return d.release_approval_reference, d.bundle_sha256
    rows = session.exec(
        select(AuditLog).where(
            AuditLog.action == "client_enrolled",
            AuditLog.entity_type == "client",
            AuditLog.entity_id == client_id,
        ).order_by(AuditLog.created_at.desc())
    ).all()
    for row in rows:
        details = row.details or {}
        if details.get("fresh_install_release_id") == release_id:
            approval = details.get("fresh_install_approval_reference")
            sha = details.get("fresh_install_bundle_sha256")
            if isinstance(approval, str) and approval and isinstance(sha, str) and len(sha) == 64:
                return approval, sha
    return None


def _event(session: Session, row: ClientFlowRollbackPermit, event_type: str, *, actor_id=None,
           credential_id=None, event_id=None, occurred_at=None, details=None) -> None:
    session.add(ClientFlowRollbackEvent(
        id=event_id or str(uuid.uuid4()), permit_id=row.id, client_id=row.client_id,
        event_type=event_type, actor_user_id=actor_id, credential_id=credential_id,
        occurred_at=occurred_at, received_at=_utcnow(), details=details or {},
    ))


@router.post("/clients/{client_id}/clientflow-rollback-permits", response_model=PermitIssued, status_code=201)
def issue_rollback_permit(
    client_id: int, body: PermitRequest, request: Request, response: Response,
    session: Session = Depends(get_session), user=Depends(get_current_superadmin_user),
):
    response.headers["Cache-Control"] = "no-store"
    if getattr(request.state, "impersonation_active", False):
        raise HTTPException(status_code=409, detail="Afslut bruger-skift før rollback")
    if not enabled():
        raise HTTPException(status_code=503, detail="Central rollback er ikke aktiveret")
    _require_session_security_password(request=request, session=session, actor=user, password=body.password)
    try:
        reason = body.reason.strip()
        reason_digest = reason_hash(reason)
        from_seq, to_seq = _sequence(body.from_release_id), _sequence(body.to_release_id)
        if from_seq <= to_seq:
            raise HTTPException(status_code=409, detail="Rollback kræver en ældre release")
        # Existing 1.3.40 and earlier immutable clients have no pinned
        # rollback trust root. Never issue a permit to a host that cannot
        # verify it. First eligible source is the NEXT separately approved
        # ClientFlow release, not the current Heidi1 development baseline.
        if from_seq < SIGNED_ROLLBACK_MIN_SOURCE_SEQUENCE:
            raise HTTPException(status_code=409, detail="Klientens release kan endnu ikke verificere signerede rollback-tilladelser")
        # Check signer readiness before taking the per-client transaction lock.
        _, issuer_key_id = _signing_key()
        if session.get(Client, client_id) is None:
            raise HTTPException(status_code=404, detail="Klienten findes ikke")
        lock_system_client(session, client_id)
        client = session.get(Client, client_id)
        if client is None or client.deleted_at is not None or client.status != "approved":
            raise HTTPException(status_code=409, detail="Rollback kræver en aktiv godkendt klient")
        if active_system_command(session, client_id) is not None or active_deployment(session, client_id=client_id, for_update=True) is not None:
            raise HTTPException(status_code=409, detail="Klienten har allerede en aktiv System-/deployment-handling")
        presence = load_client_presence(session, client)
        if not presence.status.is_online or presence.status.agent_version != body.from_release_id.removeprefix("clientflow-").split("-seq-")[0]:
            raise HTTPException(status_code=409, detail="Klientens friske Status matcher ikke rollback-kilden")
        credential = active_update_credential(session, client_id=client_id, for_update=True)
        if credential is None:
            raise HTTPException(status_code=409, detail="Klienten mangler aktiv Update-credential")
        catalog = load_catalog()
        known = {str(r.get("release_id")): r for r in catalog["releases"]}
        if body.from_release_id not in known or body.to_release_id not in known:
            raise HTTPException(status_code=409, detail="Rollback-release er ikke i det godkendte katalog")
        if int(known[body.from_release_id]["release_sequence"]) != from_seq or int(known[body.to_release_id]["release_sequence"]) != to_seq:
            raise HTTPException(status_code=409, detail="Rollback-release og katalogsekvens matcher ikke")
        require_centrally_eligible_release(release_id=body.to_release_id, release_sequence=to_seq)
        provenance = _provenance(session, client_id, body.to_release_id)
        source = _provenance(session, client_id, body.from_release_id)
        if not provenance or not source:
            raise HTTPException(status_code=409, detail="Rollback kræver to tidligere verificerede klient-releases")
        # The server cannot attest local predecessor state. The signed client
        # barrier below additionally verifies exact local predecessor + hashes.
        active_permits = session.exec(select(ClientFlowRollbackPermit).where(
            ClientFlowRollbackPermit.client_id == client_id,
            ClientFlowRollbackPermit.state == "issued",
            ClientFlowRollbackPermit.expires_at > _utcnow(),
        )).all()
        if active_permits:
            raise HTTPException(status_code=409, detail="Klienten har allerede en gyldig rollback-tilladelse")
        policy = read_release_security_policy()
        now = int(time.time())
        permit_id = str(uuid.uuid4())
        payload = {
            "schema_version": 1, "purpose": PURPOSE, "algorithm": "Ed25519",
            "issuer_key_id": issuer_key_id, "permit_id": permit_id,
            "client_id": client_id, "update_credential_id": credential.id,
            "from_release_id": body.from_release_id, "from_sequence": from_seq,
            "to_release_id": body.to_release_id, "to_sequence": to_seq,
            "release_approval_reference": provenance[0], "bundle_sha256": provenance[1],
            "reason_sha256": reason_digest, "policy_revision": policy["revision"],
            "minimum_safe_release_sequence": policy["minimum_safe_release_sequence"],
            "issued_at": now, "not_before": now, "expires_at": now + 300,
        }
        signed, key_id = sign_permit(payload)
        if key_id != issuer_key_id:
            raise HTTPException(status_code=503, detail="Rollback-signeringens identitet ændrede sig")
        row = ClientFlowRollbackPermit(
            id=permit_id, client_id=client_id, credential_id=credential.id,
            admin_id=user.id, from_release_id=body.from_release_id, from_sequence=from_seq,
            to_release_id=body.to_release_id, to_sequence=to_seq,
            release_approval_reference=provenance[0], bundle_sha256=provenance[1],
            reason_sha256=reason_digest, reason=reason, policy_revision=policy["revision"],
            signing_key_id=key_id, signed_envelope=signed,
            issued_at=datetime.fromtimestamp(now, timezone.utc).replace(tzinfo=None),
            expires_at=datetime.fromtimestamp(now + 300, timezone.utc).replace(tzinfo=None),
            state="issued",
        )
        session.add(row)
        _event(session, row, "issued", actor_id=user.id, details={"policy_revision": policy["revision"]})
        add_audit_log(
            session, action="clientflow_rollback_permit_issued", request=request, actor=user,
            target_organization_id=client.organization_id, entity_type="clientflow_rollback_permit",
            entity_id=client_id, severity="critical", is_critical=True,
            details={"permit_id": permit_id, "source": body.from_release_id,
                     "target": body.to_release_id, "reason": reason, "policy_revision": policy["revision"]},
        )
        session.commit()
        return PermitIssued(permit_id=permit_id, signed_permit=signed, expires_at=row.expires_at)
    except (RollbackPermitError, ClientFlowReleaseSecurityDenied) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RollbackSigningUnavailable as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Rollback-autorisationen blev ændret samtidigt") from exc


@router.post("/clientflow-rollback-permits/{permit_id}/revoke", status_code=200)
def revoke_rollback_permit(
    permit_id: str, request: Request, session: Session = Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    if getattr(request.state, "impersonation_active", False):
        raise HTTPException(status_code=409, detail="Afslut bruger-skift før rollback-revokation")
    row = session.exec(select(ClientFlowRollbackPermit).where(ClientFlowRollbackPermit.id == permit_id).with_for_update()).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Tilladelsen findes ikke")
    if row.state != "issued":
        raise HTTPException(status_code=409, detail="Kun ikke-forbrugte permits kan tilbagekaldes")
    row.state = "revoked"
    row.revoked_at = _utcnow()
    session.add(row)
    _event(session, row, "revoked", actor_id=user.id)
    add_audit_log(session, action="clientflow_rollback_permit_revoked", request=request,
                  actor=user, entity_type="clientflow_rollback_permit", entity_id=row.client_id,
                  severity="critical", is_critical=True, details={"permit_id": row.id})
    session.commit()
    return {"status": "revoked", "permit_id": row.id}


@router.post("/clientflow-update/rollback-permits/{permit_id}/events")
def report_rollback_result(
    permit_id: str, body: RollbackReport, request: Request,
    session: Session = Depends(get_session),
):
    try:
        principal = authenticate_update_request(session, request=request, required_scope="deployment:report")
        session.commit()  # Consume the authenticated DPoP replay even on rejection.
    except ClientFlowUpdateAuthError as exc:
        session.rollback()
        raise http_auth_error(exc) from exc
    if body.outcome not in {"succeeded", "failed"}:
        raise HTTPException(status_code=400, detail="Ukendt rollback-resultat")
    try:
        event_id = str(uuid.UUID(body.event_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Rollback-event-ID er ugyldigt") from exc
    row = session.exec(select(ClientFlowRollbackPermit).where(
        ClientFlowRollbackPermit.id == permit_id,
        ClientFlowRollbackPermit.client_id == principal.client.id,
        ClientFlowRollbackPermit.credential_id == principal.credential.id,
    ).with_for_update()).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Rollback-operationen findes ikke")
    previous = session.get(ClientFlowRollbackEvent, event_id)
    if previous is not None:
        if previous.permit_id == row.id and previous.event_type == body.outcome and previous.credential_id == principal.credential.id:
            return {"status": row.state, "replayed": True}
        raise HTTPException(status_code=409, detail="Rollback-event-ID er allerede brugt")
    if row.state not in {"issued", "revoked"}:
        raise HTTPException(status_code=409, detail="Rollback har allerede et terminalt resultat")
    if body.outcome == "succeeded":
        status = load_client_presence(session, principal.client).status
        if not status.is_online or status.agent_version != row.to_release_id.removeprefix("clientflow-").split("-seq-")[0]:
            raise HTTPException(status_code=409, detail="Klientens canonical Status bekræfter ikke rollbackmålet")
    # An offline execution after central revocation is still recorded as an
    # observed outcome, but the report cannot retroactively authorize it.
    was_revoked = row.state == "revoked"
    row.state = body.outcome
    row.reported_at = _utcnow()
    session.add(row)
    _event(session, row, body.outcome, credential_id=principal.credential.id,
           event_id=event_id, occurred_at=body.occurred_at,
           details={"was_revoked": was_revoked})
    session.commit()
    return {"status": row.state, "replayed": False, "was_revoked": was_revoked}
