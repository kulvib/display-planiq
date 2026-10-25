"""Deterministic end-to-end incident persistence using the real SQLModel schema."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine, select

from service1.client_domain_models import ClientDomainCredential, ClientDomainStatus
from service1.incident_models import OperationalIncident, OperationalIncidentEvent
from service1.incident_service import scan_incidents_once
from service1.models import Client

T0 = datetime(2026, 10, 24, 12, 0, 0)
BOOT_A = "11111111-1111-4111-8111-111111111111"
BOOT_B = "22222222-2222-4222-8222-222222222222"


def _seed():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        client = Client(name="test-display", status="approved")
        s.add(client)
        s.flush()
        credential = ClientDomainCredential(
            id=str(uuid.uuid4()), client_id=int(client.id),
            domain="status", secret_hash="not-a-real-secret", created_at=T0,
        )
        s.add(credential)
        s.flush()
        row = ClientDomainStatus(
            id=str(uuid.uuid4()), client_id=int(client.id), domain="status",
            schema_version=1, observed_state="online", status_payload={
                "services": {"clientflow-browser-guard.service": "failed"},
                "private_error_message": "WIFI_PSK_MUST_NOT_BE_RECORDED",
            },
            boot_id=BOOT_A, credential_id=credential.id, reported_at=T0,
        )
        s.add(row)
        s.commit()
        return engine, int(client.id), row.id


def test_scanner_records_one_episode_and_no_duplicate_heartbeats():
    engine, cid, status_id = _seed()
    with Session(engine) as s:
        observed = {"selects": 0}
        def counter(_conn, _cursor, statement, _parameters, _ctx, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                observed["selects"] += 1
        event.listen(engine, "before_cursor_execute", counter)
        try:
            assert scan_incidents_once(s, now=T0 + timedelta(seconds=1)) == {
                "locked": 0, "observations": 1, "opened": 1, "recovered": 0,
            }
        finally:
            event.remove(engine, "before_cursor_execute", counter)
        assert observed["selects"] == 2
        s.commit()
    with Session(engine) as s:
        row = s.exec(select(OperationalIncident)).one()
        assert row.client_id == cid and row.resolved_at is None
        assert row.code == "service_clientflow_browser_guard_service"
        assert "WIFI_PSK_MUST_NOT_BE_RECORDED" not in repr(row)
        assert [e.kind for e in s.exec(select(OperationalIncidentEvent)).all()] == ["opened"]
        assert scan_incidents_once(s, now=T0 + timedelta(seconds=2))["opened"] == 0
        s.commit()
        assert len(s.exec(select(OperationalIncidentEvent)).all()) == 1


def test_offline_does_not_recover_and_fresh_post_reboot_success_does():
    engine, cid, status_id = _seed()
    with Session(engine) as s:
        scan_incidents_once(s, now=T0 + timedelta(seconds=1))
        s.commit()
        # Last persisted report has aged out. The mere passage of time and a
        # later reboot without a complete healthy payload cannot close it.
        assert scan_incidents_once(s, now=T0 + timedelta(minutes=8))["recovered"] == 0
        assert s.exec(select(OperationalIncident)).one().resolved_at is None
        row = s.get(ClientDomainStatus, status_id)
        row.boot_id = BOOT_B
        row.status_payload = {"services": {"clientflow-browser-guard.service": "active"}}
        row.reported_at = T0 + timedelta(minutes=8)
        s.add(row)
        s.commit()
        assert scan_incidents_once(s, now=T0 + timedelta(minutes=8, seconds=1))["recovered"] == 1
        s.commit()
        incident = s.exec(select(OperationalIncident)).one()
        assert incident.resolved_at is not None
        assert incident.resolution_evidence == "healthy_after_reboot"
        assert [e.kind for e in s.exec(select(OperationalIncidentEvent)).all()] == [
            "opened", "reboot_observed", "recovered",
        ]


def test_incomplete_heartbeat_does_not_clear_active_incident():
    engine, _cid, status_id = _seed()
    with Session(engine) as s:
        scan_incidents_once(s, now=T0 + timedelta(seconds=1))
        row = s.get(ClientDomainStatus, status_id)
        row.status_payload = {"memory_available_bytes": 123}
        row.reported_at = T0 + timedelta(minutes=1)
        s.add(row)
        s.commit()
        assert scan_incidents_once(s, now=T0 + timedelta(minutes=1, seconds=1))["recovered"] == 0
        assert s.exec(select(OperationalIncident)).one().resolved_at is None


def test_one_batch_handles_100_clients_without_per_client_queries_or_duplicate_events():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        for i in range(100):
            client = Client(name=f"fleet-{i}", status="approved")
            s.add(client)
            s.flush()
            credential = ClientDomainCredential(
                id=str(uuid.uuid4()), client_id=int(client.id),
                domain="status", secret_hash="test-only", created_at=T0,
            )
            s.add(credential)
            s.flush()
            s.add(ClientDomainStatus(
                id=str(uuid.uuid4()), client_id=int(client.id), domain="status",
                schema_version=1, observed_state="online",
                status_payload={"services": {"clientflow-browser-guard.service": "inactive"}},
                boot_id=BOOT_A, credential_id=credential.id, reported_at=T0,
            ))
        s.commit()

    with Session(engine) as s:
        selects = []
        def count_select(_conn, _cursor, statement, _args, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)
        event.listen(engine, "before_cursor_execute", count_select)
        try:
            summary = scan_incidents_once(s, now=T0 + timedelta(seconds=1))
            assert summary == {"locked": 0, "observations": 100, "opened": 100, "recovered": 0}
            assert len(selects) == 2
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        s.commit()
        assert scan_incidents_once(s, now=T0 + timedelta(seconds=2))["opened"] == 0
        s.commit()
    with Session(engine) as s:
        assert len(s.exec(select(OperationalIncident)).all()) == 100
        assert len(s.exec(select(OperationalIncidentEvent)).all()) == 100


def test_coverage_endpoint_uses_two_projected_queries_without_status_payload_or_writes():
    from fastapi import Response
    from service1.models import utcnow
    from service1.routers.operational_incidents import operational_report_coverage

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    now = utcnow()
    with Session(engine) as s:
        for i in range(2):
            client = Client(name=f"coverage-{i}", status="approved")
            s.add(client)
            s.flush()
            credential = ClientDomainCredential(
                id=str(uuid.uuid4()), client_id=int(client.id),
                domain="status", secret_hash="test-only", created_at=now,
            )
            s.add(credential)
            s.flush()
            s.add(ClientDomainStatus(
                id=str(uuid.uuid4()), client_id=int(client.id), domain="status",
                schema_version=1, observed_state="online",
                status_payload={"wifi_password": "DO_NOT_SELECT_ME"},
                boot_id=BOOT_A, credential_id=credential.id,
                reported_at=now if i == 0 else now - timedelta(hours=3),
            ))
        s.commit()

    with Session(engine) as s:
        sql = []
        def capture(_conn, _cursor, statement, _args, _ctx, _executemany):
            sql.append(statement)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            response = Response()
            result = operational_report_coverage(response=response, session=s, _user=object())
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert response.headers["Cache-Control"] == "no-store"
        assert len([s for s in sql if s.lstrip().upper().startswith("SELECT")]) == 2
        assert not any("status_payload" in statement.lower() for statement in sql)
        assert result["approved_clients"] == 2
        assert result["domains"][0] == {"domain": "status", "fresh": 1, "stale": 1, "missing": 0}
        assert result["domains"][1] == {"domain": "display", "fresh": 0, "stale": 0, "missing": 2}
