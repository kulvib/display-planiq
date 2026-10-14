"""Executable Terminal live-socket revocation + one-SELECT query budget.

The control plane must keep checking the database every 15 seconds; only the
credential/client duplicate read is consolidated, never cached across checks.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import uuid

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from service1 import db_hotpath_telemetry as telemetry
from service1.db import install_database_request_metrics
from service1.routers import terminal as terminal_router
from service1.terminal_v2_models import TerminalClient, TerminalCredential


@pytest.fixture()
def terminal_ws_database(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    install_database_request_metrics(engine)
    client_id = 73
    credential_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(engine) as session:
        session.add_all([
            TerminalClient(id=client_id, display_name="WS recheck", status="approved", created_at=now),
            TerminalCredential(id=credential_id, client_id=client_id, secret_hash="test", token_version=5, created_at=now),
        ])
        session.commit()
    monkeypatch.setattr(terminal_router, "engine", engine)
    clock = [0.0]
    captured: list[str] = []
    monitor = telemetry.HotpathDatabaseTelemetry(
        clock=lambda: clock[0], interval_seconds=900, emit=captured.append
    )
    monkeypatch.setattr(telemetry, "hotpath_database_telemetry", monitor)
    conn = terminal_router.DomainClientConnection(
        connection_id="test", client_id=client_id, credential_id=credential_id,
        token_version=5, websocket=None,
    )
    try:
        yield engine, conn, clock, captured, monitor
    finally:
        engine.dispose()


@pytest.mark.parametrize("state", ["approved", "disabled", "revoked", "version", "missing_credential", "other_client"])
def test_terminal_ws_recheck_uses_exactly_one_join_select(terminal_ws_database, state):
    engine, conn, clock, captured, monitor = terminal_ws_database
    with Session(engine) as session:
        client = session.get(TerminalClient, conn.client_id)
        credential = session.get(TerminalCredential, conn.credential_id)
        if state == "disabled":
            client.status = "disabled"
        elif state == "revoked":
            credential.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        elif state == "version":
            credential.token_version += 1
        elif state == "missing_credential":
            session.delete(credential)
        elif state == "other_client":
            conn.client_id += 1
        session.commit()

    reads: list[str] = []
    def on_sql(_conn, _cursor, sql, _params, _context, _executemany):
        if sql.lstrip().upper().startswith("SELECT"):
            reads.append(sql)
    event.listen(engine, "before_cursor_execute", on_sql)
    try:
        assert terminal_router._terminal_agent_connection_valid(conn) is (state == "approved")
    finally:
        event.remove(engine, "before_cursor_execute", on_sql)
    assert len(reads) == 1, f"Expected one persisted check, got {len(reads)}"
    assert "JOIN" in reads[0].upper()
    assert "terminal_client" in reads[0] and "terminal_credential" in reads[0]

    # Force a 15-minute aggregate flush; it must not reveal credential/client IDs.
    clock[0] = 900.0
    monitor.record_websocket_recheck(
        "terminal_ws_recheck", True,
        telemetry_metrics(statements=0, selects=0, checkouts=0),
    )
    assert len(captured) == 1
    import json
    category = json.loads(captured[0])["categories"]["terminal_ws_recheck"]
    assert category["websocket_rechecks"] == 1
    assert category["failed_websocket_rechecks"] == int(state != "approved")
    assert category["statements"] == 1
    assert category["selects"] == 1
    assert category["checkouts"] == 1
    assert str(conn.credential_id) not in captured[0]


def telemetry_metrics(*, statements: int, selects: int, checkouts: int):
    from types import SimpleNamespace
    return SimpleNamespace(
        statement_count=statements, select_count=selects,
        checkout_count=checkouts, duration_ms=0.0,
    )
