"""One persisted Terminal credential/lifecycle read per authorization check.

Every check continues to validate approval, binding, revocation and version.
The 15-second recheck cadence and terminal isolation are unchanged.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import os
import uuid

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from service1 import terminal_v2
from service1.terminal_v2_models import TerminalClient, TerminalCredential


@pytest.fixture()
def terminal_db(monkeypatch):
    monkeypatch.setenv(
        "CLIENTFLOW_TERMINAL_AUTH_KEY_B64",
        base64.urlsafe_b64encode(b"t" * 32).decode("ascii").rstrip("="),
    )
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    client_id = 73
    credential_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(engine) as session:
        session.add_all([
            TerminalClient(id=client_id, display_name="Terminal cost test", status="approved", created_at=now),
            TerminalCredential(id=credential_id, client_id=client_id, secret_hash="test-only", token_version=1, created_at=now),
        ])
        session.commit()
        credential = session.get(TerminalCredential, credential_id)
        token, _ = terminal_v2.create_terminal_domain_token(credential)
    try:
        yield engine, client_id, credential_id, token
    finally:
        engine.dispose()


def _one_join_select(engine, callback):
    sql_reads: list[str] = []

    def observe(_connection, _cursor, statement, _params, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            sql_reads.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    result = None
    caught = None
    try:
        result = callback()
    except Exception as exc:
        caught = exc
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(sql_reads) == 1, f"Terminal authority must use one SELECT, got {len(sql_reads)}"
    assert "JOIN" in sql_reads[0].upper()
    assert "terminal_client" in sql_reads[0]
    assert "terminal_credential" in sql_reads[0]
    if caught is not None:
        raise caught
    return result


@pytest.mark.parametrize("state", ["approved", "disabled", "revoked", "version", "missing_client"])
def test_token_revalidates_persisted_authority_in_one_select(terminal_db, state):
    engine, client_id, credential_id, token = terminal_db
    with Session(engine) as session:
        client = session.get(TerminalClient, client_id)
        credential = session.get(TerminalCredential, credential_id)
        if state == "disabled":
            client.status = "disabled"
        elif state == "revoked":
            credential.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        elif state == "version":
            credential.token_version += 1
        elif state == "missing_client":
            session.delete(credential)
            session.delete(client)
        session.commit()
    with Session(engine) as session:
        check = lambda: terminal_v2.verify_terminal_agent_token(session, token, client_id=client_id)
        if state == "approved":
            assert _one_join_select(engine, check).id == credential_id
        else:
            with pytest.raises(HTTPException) as exc:
                _one_join_select(engine, check)
            assert exc.value.status_code == 401


def test_login_validates_secret_with_single_join_select(terminal_db, monkeypatch):
    engine, client_id, credential_id, _token = terminal_db
    monkeypatch.setattr(terminal_v2, "verify_password", lambda raw, _stored: raw == "correct")
    for secret, accepted in (("correct", True), ("incorrect", False)):
        with Session(engine) as session:
            verify = lambda: terminal_v2.authenticate_terminal_credential(
                session, client_id=client_id, credential_id=credential_id, client_secret=secret
            )
            if accepted:
                assert _one_join_select(engine, verify).id == credential_id
            else:
                with pytest.raises(HTTPException) as exc:
                    _one_join_select(engine, verify)
                assert exc.value.status_code == 401


@pytest.mark.parametrize("state", ["disabled", "revoked", "missing_client"])
def test_login_rejects_inactive_authority_in_one_read(terminal_db, monkeypatch, state):
    engine, client_id, credential_id, _token = terminal_db
    monkeypatch.setattr(terminal_v2, "verify_password", lambda _raw, _stored: True)
    with Session(engine) as session:
        client = session.get(TerminalClient, client_id)
        credential = session.get(TerminalCredential, credential_id)
        if state == "disabled":
            client.status = "disabled"
        elif state == "revoked":
            credential.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            session.delete(credential)
            session.delete(client)
        session.commit()
    with Session(engine) as session:
        with pytest.raises(HTTPException) as exc:
            _one_join_select(
                engine,
                lambda: terminal_v2.authenticate_terminal_credential(
                    session, client_id=client_id, credential_id=credential_id, client_secret="any"
                ),
            )
        assert exc.value.status_code == 401
