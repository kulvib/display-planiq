"""Superadministrator-only paginated operational fault history.

Read-only, never exposes raw status payload, browser URLs, tokens or errors.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from ..auth import get_current_superadmin_user
from ..db import get_session
from ..incident_models import OperationalIncident, OperationalIncidentEvent
from ..incident_coverage import coverage_summary
from ..client_domain_models import ClientDomainStatus
from ..models import Client, Organization, utcnow

router = APIRouter(prefix="/superadmin/operational-incidents", tags=["operational-incidents"])


def _utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


class IncidentItem(BaseModel):
    id: str
    client_id: int
    client_name: str
    organization_name: str | None = None
    domain: str
    code: str
    title: str
    severity: str
    started_at: datetime
    last_observed_at: datetime
    resolved_at: datetime | None
    resolution_evidence: str | None
    verification: str


class IncidentEventItem(BaseModel):
    kind: str
    observed_at: datetime
    boot_id_changed: bool = False


@router.get("/report-coverage")
def operational_report_coverage(
    response: Response,
    session: Session = Depends(get_session),
    _user=Depends(get_current_superadmin_user),
):
    """Aggregate data coverage, not a new client poll or background scan.

    Two bounded SELECT statements, no raw JSON status payload, no client IDs,
    no secrets and no reclassification of offline/missing reports as healthy.
    """
    response.headers["Cache-Control"] = "no-store"
    approved_filter = (Client.status == "approved", Client.deleted_at.is_(None))
    approved = session.exec(
        select(func.count(Client.id)).where(*approved_filter)
    ).one()
    report_rows = session.exec(
        select(ClientDomainStatus.domain, ClientDomainStatus.reported_at)
        .join(Client, Client.id == ClientDomainStatus.client_id)
        .where(*approved_filter, ClientDomainStatus.domain.in_(("status", "display", "system")))
    ).all()
    return coverage_summary(int(approved), report_rows, now=utcnow())


@router.get("")
def list_operational_incidents(
    response: Response,
    status: str = Query(default="all", pattern="^(all|active|resolved)$"),
    severity: str | None = Query(default=None, pattern="^(error|critical)$"),
    client_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
    session: Session = Depends(get_session),
    _user=Depends(get_current_superadmin_user),
):
    response.headers["Cache-Control"] = "no-store"
    filters = []
    if status == "active":
        filters.append(OperationalIncident.resolved_at.is_(None))
    elif status == "resolved":
        filters.append(OperationalIncident.resolved_at.is_not(None))
    if severity:
        filters.append(OperationalIncident.severity == severity)
    if client_id:
        filters.append(OperationalIncident.client_id == client_id)

    count = session.exec(select(func.count(OperationalIncident.id)).where(*filters)).one()
    # Current agent verification is correlated to the exact source domain; no
    # active incident is shown as "resolved" merely because a client rebooted.
    statement = (
        select(OperationalIncident, Client.name, Organization.name, ClientDomainStatus.reported_at)
        .join(Client, Client.id == OperationalIncident.client_id)
        .outerjoin(Organization, Organization.id == Client.organization_id)
        .outerjoin(ClientDomainStatus, (
            (ClientDomainStatus.client_id == OperationalIncident.client_id)
            & (ClientDomainStatus.domain == OperationalIncident.domain)
        ))
        .where(*filters)
        .order_by(OperationalIncident.started_at.desc(), OperationalIncident.id.desc())
        .offset(offset).limit(limit)
    )
    recent = utcnow() - timedelta(seconds=180)
    items = []
    for row, name, org_name, reported_at in session.exec(statement).all():
        items.append(IncidentItem(
            id=row.id, client_id=row.client_id, client_name=name,
            organization_name=org_name, domain=row.domain, code=row.code,
            title=row.title, severity=row.severity, started_at=_utc(row.started_at),
            last_observed_at=_utc(row.last_observed_at), resolved_at=_utc(row.resolved_at),
            resolution_evidence=row.resolution_evidence,
            verification="resolved" if row.resolved_at else (
                "fresh" if reported_at and reported_at >= recent else "stale"
            ),
        ).model_dump(mode="json"))
    return {"items": items, "total": count, "limit": limit, "offset": offset}


@router.get("/{incident_id}/events")
def list_operational_incident_events(
    incident_id: str, response: Response,
    session: Session = Depends(get_session),
    _user=Depends(get_current_superadmin_user),
):
    from fastapi import HTTPException
    response.headers["Cache-Control"] = "no-store"
    row = session.get(OperationalIncident, incident_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Hændelse findes ikke")
    events = session.exec(select(OperationalIncidentEvent).where(
        OperationalIncidentEvent.incident_id == incident_id
    ).order_by(OperationalIncidentEvent.observed_at.asc()).limit(500)).all()
    return {"items": [IncidentEventItem(
        kind=event.kind, observed_at=_utc(event.observed_at),
        boot_id_changed=(event.kind == "reboot_observed"),
    ).model_dump(mode="json") for event in events]}


@router.get("/operation-outcomes")
def recent_operational_outcomes(
    response: Response,
    session: Session = Depends(get_session),
    _user=Depends(get_current_superadmin_user),
):
    """Read-only projection of existing immutable update/rollback audit events.

    No duplicate authority: a failed historical outcome is not silently
    converted into a resolved incident merely because another update succeeded.
    Freeform updater messages, reason and event details are excluded.
    """
    from ..clientflow_update_models import ClientFlowDeployment
    from ..clientflow_rollback_models import ClientFlowRollbackEvent

    response.headers["Cache-Control"] = "no-store"
    cutoff = utcnow() - timedelta(days=90)
    deployments = session.exec(
        select(ClientFlowDeployment, Client.name)
        .join(Client, Client.id == ClientFlowDeployment.client_id)
        .where(
            ClientFlowDeployment.completed_at >= cutoff,
            ClientFlowDeployment.state.in_(("succeeded", "failed", "recovery_failed", "rolled_back")),
        )
        .order_by(ClientFlowDeployment.completed_at.desc()).limit(50)
    ).all()
    rollbacks = session.exec(
        select(ClientFlowRollbackEvent, Client.name)
        .join(Client, Client.id == ClientFlowRollbackEvent.client_id)
        .where(
            ClientFlowRollbackEvent.received_at >= cutoff,
            ClientFlowRollbackEvent.event_type.in_(("succeeded", "failed")),
        )
        .order_by(ClientFlowRollbackEvent.received_at.desc()).limit(50)
    ).all()
    items = [
        {
            "id": item.id,
            "client_id": item.client_id,
            "client_name": name,
            "category": "clientflow_update",
            "outcome": item.state,
            "occurred_at": _utc(item.completed_at).isoformat(),
        }
        for item, name in deployments
    ] + [
        {
            "id": item.id,
            "client_id": item.client_id,
            "client_name": name,
            "category": "signed_rollback",
            "outcome": item.event_type,
            "occurred_at": _utc(item.received_at).isoformat(),
        }
        for item, name in rollbacks
    ]
    items.sort(key=lambda item: item["occurred_at"], reverse=True)
    return {"items": items[:50], "window_days": 90}
