"""Executable read budgets for the always-on Livestream and RD auth paths.

Every request must still check persisted credential revocation, token version,
client approval and (for Livestream) deletion. Only the duplicate SELECT is
removed; the security recheck cadence must not change.
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

from service1 import livestream_v2, remote_desktop_v2
from service1.livestream_v2_models import LivestreamV2Credential
from service1.models import Client
from service1.remote_desktop_v2_models import RemoteDesktopClient, RemoteDesktopCredential
from service1.routers import livestream_v2 as ls_router
from service1.routers import remote_desktop_v2 as rd_router


def _selects_during(engine, callback):
    reads = []

    def observe(_conn, _cursor, sql, _parameters, _context, _executemany):
        if sql.lstrip().upper().startswith("SELECT"):
            reads.append(sql)

    event.listen(engine, "before_cursor_execute", observe)
    failure = None
    result = None
    try:
        result = callback()
    except Exception as exc:
        failure = exc
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(reads) == 1, f"Expected one lifecycle+credential SELECT, got {len(reads)}"
    assert "JOIN" in reads[0].upper()
    if failure is not None:
        raise failure
    return result


@pytest.fixture()
def domain_database(monkeypatch):
    monkeypatch.setenv(
        "CLIENTFLOW_REMOTE_DESKTOP_AUTH_KEY_B64",
        base64.urlsafe_b64encode(b"k" * 32).decode("ascii").rstrip("="),
    )
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    ls_id, rd_id = 71, 72
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(engine) as session:
        client = Client(id=ls_id, name="LS cost test", status="approved")
        ls = LivestreamV2Credential(
            id=str(uuid.uuid4()), client_id=ls_id, secret_digest="test-only",
            domain="livestream", token_version=1,
        )
        rd_client = RemoteDesktopClient(id=rd_id, display_name="RD cost test", status="approved", created_at=now)
        rd = RemoteDesktopCredential(
            id=str(uuid.uuid4()), client_id=rd_id, secret_hash="test-only",
            token_version=1, created_at=now,
        )
        session.add_all([client, ls, rd_client, rd])
        session.commit()
        ls_token, _ = livestream_v2.create_client_token(ls)
        rd_token, _ = remote_desktop_v2.create_remote_desktop_domain_token(rd)
        ls_credential_id = ls.id
        rd_credential_id = rd.id
    monkeypatch.setattr(rd_router, "engine", engine)
    monkeypatch.setattr(ls_router, "engine", engine)
    try:
        yield engine, ls_id, ls_credential_id, ls_token, rd_id, rd_credential_id, rd_token
    finally:
        engine.dispose()


@pytest.mark.parametrize("state", ["approved", "disabled", "deleted", "revoked", "version"])
def test_livestream_token_rechecks_client_and_credential_in_one_select(domain_database, state):
    engine, client_id, credential_id, token, *_ = domain_database
    with Session(engine) as session:
        client = session.get(Client, client_id)
        credential = session.get(LivestreamV2Credential, credential_id)
        if state == "disabled":
            client.status = "disabled"
        elif state == "deleted":
            client.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
        elif state == "revoked":
            credential.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        elif state == "version":
            credential.token_version += 1
        session.commit()

    with Session(engine) as session:
        def verify():
            return livestream_v2.require_agent_token(session, f"Bearer {token}", client_id=client_id)

        if state == "approved":
            assert _selects_during(engine, verify).id == credential_id
        else:
            with pytest.raises(HTTPException) as exc:
                _selects_during(engine, verify)
            assert exc.value.status_code == 401


def test_livestream_idle_presence_route_revalidates_without_status_write(domain_database):
    engine, client_id, credential_id, token, *_ = domain_database
    assert _selects_during(
        engine,
        lambda: ls_router.livestream_agent_presence(client_id, f"Bearer {token}"),
    ) == {"ok": True, "client_id": client_id}

    with Session(engine) as session:
        credential = session.get(LivestreamV2Credential, credential_id)
        credential.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()
    with pytest.raises(HTTPException) as error:
        _selects_during(
            engine,
            lambda: ls_router.livestream_agent_presence(client_id, f"Bearer {token}"),
        )
    assert error.value.status_code == 401


@pytest.mark.parametrize("state", ["approved", "disabled", "revoked", "version"])
def test_rd_token_and_websocket_checks_use_one_select(domain_database, state):
    engine, *_ls, client_id, credential_id, token = domain_database
    with Session(engine) as session:
        client = session.get(RemoteDesktopClient, client_id)
        credential = session.get(RemoteDesktopCredential, credential_id)
        if state == "disabled":
            client.status = "disabled"
        elif state == "revoked":
            credential.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        elif state == "version":
            credential.token_version += 1
        session.commit()

    with Session(engine) as session:
        def verify():
            return remote_desktop_v2.verify_remote_desktop_agent_token(session, token, client_id=client_id)

        if state == "approved":
            assert _selects_during(engine, verify).id == credential_id
        else:
            with pytest.raises(HTTPException) as exc:
                _selects_during(engine, verify)
            assert exc.value.status_code == 401

    channel = rd_router.AgentChannel(
        client_id=client_id, credential_id=credential_id, token_version=1, websocket=None
    )
    assert _selects_during(engine, lambda: rd_router._remote_desktop_agent_channel_valid(channel)) is (state == "approved")


def test_rd_credential_token_login_is_one_select_and_still_validates_secret(domain_database, monkeypatch):
    engine, *_ls, client_id, credential_id, _token = domain_database
    monkeypatch.setattr(remote_desktop_v2, "verify_password", lambda raw, stored: raw == "correct-secret")
    with Session(engine) as session:
        assert _selects_during(
            engine,
            lambda: remote_desktop_v2.authenticate_remote_desktop_credential(
                session, client_id=client_id, credential_id=credential_id, client_secret="correct-secret"
            ),
        ).id == credential_id
    with Session(engine) as session:
        with pytest.raises(HTTPException) as exc:
            _selects_during(
                engine,
                lambda: remote_desktop_v2.authenticate_remote_desktop_credential(
                    session, client_id=client_id, credential_id=credential_id, client_secret="wrong"
                ),
            )
        assert exc.value.status_code == 401
