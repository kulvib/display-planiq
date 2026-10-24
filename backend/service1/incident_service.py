"""Periodic, low-cost reconciliation of canonical agent evidence to durable faults.

The scanner reads batched already-persisted reports. It does not add polls to
clients or treat an absent/offline report as a recovery. On PostgreSQL its
transaction-scoped advisory lock serializes concurrent backend workers.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, text
from sqlmodel import Session, select

from .client_domain_models import ClientDomainStatus
from .incident_models import OperationalIncident, OperationalIncidentEvent
from .incident_policy import signals_for_report, observed_codes_for_report
from .models import Client, utcnow

_LOCK_KEY = -2718850013462
_FRESH_SECONDS = 180
_BOOT_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.I)


def _boot_id(value: object) -> str | None:
    return value if isinstance(value, str) and _BOOT_RE.fullmatch(value) else None


def _event(session: Session, row: OperationalIncident, kind: str, when: datetime, boot: str | None) -> None:
    session.add(OperationalIncidentEvent(
        id=str(uuid.uuid4()), incident_id=row.id, kind=kind,
        observed_at=when, boot_id=boot,
    ))


def reconcile_observation(
    session: Session, *, client_id: int, domain: str, observed_state: str,
    payload: dict, boot_id: str | None, reported_at: datetime,
    active: list[OperationalIncident],
) -> tuple[int, int]:
    """Reconcile *one fresh verified domain observation* atomically in caller tx.

    The result counts opened and recovered incidents, never raw heartbeats.
    Existing active rows are passed in by the batch caller (no per-client query).
    """
    signals = signals_for_report(domain, observed_state, payload)
    if signals is None:
        return 0, 0
    evidenced = observed_codes_for_report(domain, payload)
    boot = _boot_id(boot_id)
    current = {row.code: row for row in active if row.client_id == client_id and row.domain == domain and row.resolved_at is None}
    opened = recovered = 0
    for code, signal in signals.items():
        old = current.get(code)
        if old is None:
            row = OperationalIncident(
                id=str(uuid.uuid4()), client_id=client_id, domain=domain,
                code=signal.code, title=signal.title, severity=signal.severity,
                started_at=reported_at, last_observed_at=reported_at,
                first_boot_id=boot, last_boot_id=boot,
            )
            session.add(row)
            _event(session, row, "opened", reported_at, boot)
            active.append(row)
            opened += 1
        else:
            if boot and old.last_boot_id and boot != old.last_boot_id:
                _event(session, old, "reboot_observed", reported_at, boot)
                old.last_boot_id = boot
            elif boot and old.last_boot_id is None:
                old.last_boot_id = boot
            if reported_at - old.last_observed_at >= timedelta(minutes=5):
                old.last_observed_at = reported_at
                session.add(old)
    for code, old in current.items():
        if code not in signals and code in evidenced:
            if boot and old.last_boot_id and boot != old.last_boot_id:
                _event(session, old, "reboot_observed", reported_at, boot)
            old.resolved_at = reported_at
            old.resolution_evidence = (
                "healthy_after_reboot" if boot and old.last_boot_id and boot != old.last_boot_id
                else "healthy_report"
            )
            old.last_boot_id = boot or old.last_boot_id
            old.last_observed_at = reported_at
            session.add(old)
            _event(session, old, "recovered", reported_at, boot)
            recovered += 1
    return opened, recovered


def scan_incidents_once(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Read status and active episodes in two batched queries; write transitions only."""
    now = now or utcnow()
    if session.get_bind().dialect.name == "postgresql":
        acquired = session.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _LOCK_KEY}).scalar()
        if not acquired:
            return {"locked": 1, "observations": 0, "opened": 0, "recovered": 0}

    statuses = session.exec(
        select(ClientDomainStatus)
        .join(Client, Client.id == ClientDomainStatus.client_id)
        .where(
            Client.status == "approved", Client.deleted_at.is_(None),
            ClientDomainStatus.reported_at >= now - timedelta(seconds=_FRESH_SECONDS),
            ClientDomainStatus.reported_at <= now + timedelta(seconds=5),
        )
    ).all()
    if not statuses:
        return {"locked": 0, "observations": 0, "opened": 0, "recovered": 0}
    client_ids = sorted({int(status.client_id) for status in statuses})
    active = list(session.exec(select(OperationalIncident).where(
        OperationalIncident.client_id.in_(client_ids), OperationalIncident.resolved_at.is_(None)
    )).all())
    opened = recovered = 0
    for status in statuses:
        new, cleared = reconcile_observation(
            session, client_id=int(status.client_id), domain=status.domain,
            observed_state=status.observed_state, payload=status.status_payload,
            boot_id=status.boot_id, reported_at=status.reported_at, active=active,
        )
        opened += new
        recovered += cleared
    return {"locked": 0, "observations": len(statuses), "opened": opened, "recovered": recovered}


def prune_resolved_incidents(session: Session, *, now: datetime | None = None) -> int:
    """Bound history costs; never prune active faults, and retain at least 90 days."""
    raw = os.getenv("OPERATIONAL_INCIDENT_RETENTION_DAYS", "365")
    try:
        days = min(3650, max(90, int(raw)))
    except ValueError:
        days = 365
    cutoff = (now or utcnow()) - timedelta(days=days)
    result = session.execute(delete(OperationalIncident).where(
        OperationalIncident.resolved_at.is_not(None), OperationalIncident.resolved_at < cutoff
    ))
    return int(result.rowcount or 0)
