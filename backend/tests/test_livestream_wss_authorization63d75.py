"""Real isolated database, signed credentials and browser-session checks.

This complements the ASGI test-double transport tests; never uses live data.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from service1 import auth, livestream_presence, livestream_v2, maintenance_state
from service1.livestream_v2_models import LivestreamV2Credential, LivestreamV2Generation
from service1.livestream_wss_admission import ViewerBinding
from service1.models import Client, Organization, RefreshToken, User
from service1.routers import livestream_media, livestream_wss

CID = 73075
UID = 75003
GEN = "13b8539d-0f3d-4b68-9446-64f004d72730"
CREDENTIAL = "f27c4790-5573-41fa-8346-09e2a0d1486d"
VIEWER = "63d75-real-auth"
ORIGIN = "https://display.planiq.dk"


@pytest.fixture
def isolated(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(livestream_wss, "engine", engine)
    monkeypatch.setattr(livestream_media, "engine", engine)
    # Prevent a cached maintenance result from another test entering this
    # isolated database; keep the real maintenance query and decision.
    snapshot = maintenance_state.get_maintenance_snapshot
    monkeypatch.setattr(auth, "get_maintenance_snapshot", lambda session: snapshot(session, force_refresh=True))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expiry = now + timedelta(minutes=30)
    with Session(engine) as session:
        session.add(Organization(id=1, name="WSS tenant A"))
        session.add(Organization(id=2, name="WSS tenant B"))
        session.add(Client(id=CID, name="WSS test client", status="approved", organization_id=1))
        session.add(User(id=UID, username="wss-viewer", email="wss@example.invalid",
                         hashed_password="not-a-login-password", role="viewer",
                         organization_id=1, must_change_password=False, token_version=2))
        session.add(RefreshToken(id=1, user_id=UID, token_hash="a" * 64,
                                 session_id="b" * 32, created_at=now,
                                 expires_at=expiry, session_expires_at=expiry))
        session.add(LivestreamV2Generation(id=GEN, client_id=CID, state="running", requested_action="start"))
        session.add(LivestreamV2Credential(id=CREDENTIAL, client_id=CID, secret_digest="c" * 64,
                                          domain="livestream", token_version=1))
        session.commit()
        user = session.get(User, UID)
        token = auth.create_access_token({"sub": user.username, "uid": UID, "sid": "b" * 32,
                                          "role": user.role, "token_version": 2}, session_expires_at=expiry)
        binding = ViewerBinding(CID, GEN, VIEWER, UID, 2,
                                auth.require_active_browser_auth_session_binding(session, token=token, user=user),
                                ORIGIN)
        agent, _ = livestream_v2.create_client_token(session.get(LivestreamV2Credential, CREDENTIAL))
    livestream_presence.touch(CID, VIEWER, f"viewer:{UID}")
    try:
        yield engine, binding, "Bearer " + agent
    finally:
        livestream_presence.leave(CID, VIEWER, f"viewer:{UID}")
        engine.dispose()


def deny(call, code):
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == code


def test_real_tenant_access_and_revoked_parent_session(isolated):
    engine, binding, _ = isolated
    livestream_wss._check_viewer(binding)
    with Session(engine) as session:
        user = session.get(User, UID)
        user.organization_id = 2
        session.add(user)
        session.commit()
    deny(lambda: livestream_wss._check_viewer(binding), 403)
    with Session(engine) as session:
        user = session.get(User, UID)
        user.organization_id = 1
        session.add(user)
        session.commit()
    livestream_wss._check_viewer(binding)
    with Session(engine) as session:
        row = session.get(RefreshToken, 1)
        row.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(row)
        session.commit()
    deny(lambda: livestream_wss._check_viewer(binding), 401)


def test_real_agent_credential_and_generation_stop(isolated):
    engine, binding, agent = isolated
    livestream_wss._check_publisher(CID, GEN, agent)
    deny(lambda: livestream_wss._check_publisher(CID, GEN, "Bearer invalid"), 401)
    deny(lambda: livestream_wss._check_publisher(CID + 1, GEN, agent), 403)
    with Session(engine) as session:
        client = session.get(Client, CID)
        client.livestream_stop_reason = "explicit_stop:browser_manual_stop"
        session.add(client)
        session.commit()
    deny(lambda: livestream_wss._check_viewer(binding), 409)
    deny(lambda: livestream_wss._check_publisher(CID, GEN, agent), 409)
    with Session(engine) as session:
        client = session.get(Client, CID)
        client.livestream_stop_reason = None
        credential = session.get(LivestreamV2Credential, CREDENTIAL)
        credential.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(client)
        session.add(credential)
        session.commit()
    deny(lambda: livestream_wss._check_publisher(CID, GEN, agent), 401)


def test_real_viewer_lease_and_stale_generation(isolated):
    engine, binding, agent = isolated
    livestream_presence.leave(CID, VIEWER, f"viewer:{UID}")
    deny(lambda: livestream_wss._check_viewer(binding), 403)
    deny(lambda: livestream_wss._check_publisher(CID, GEN, agent), 403)
    livestream_presence.touch(CID, VIEWER, f"viewer:{UID}")
    with Session(engine) as session:
        generation = session.get(LivestreamV2Generation, GEN)
        generation.state = "stopped"
        session.add(generation)
        session.commit()
    deny(lambda: livestream_wss._check_viewer(binding), 409)
    deny(lambda: livestream_wss._check_publisher(CID, GEN, agent), 409)
