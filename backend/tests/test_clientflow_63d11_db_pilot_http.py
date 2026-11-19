"""63D-11 isolated in-process HTTP and transaction integration checks.

The full test executes in GitHub CI with locked SQLModel/SQLAlchemy versions.
Never points at Neon, Render or physical client 3.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
pytest.importorskip("sqlmodel")

from fastapi import FastAPI
from sqlmodel import SQLModel, select

from service1.auth import get_current_superadmin_user
from service1.client_domain_models import ClientCommand, ClientDomainStatus
from service1.clientflow_pilot_1247 import (
    APPROVED_BUNDLE_SHA256, APPROVED_BUNDLE_SIZE, APPROVAL_REFERENCE,
    CANDIDATE_SHA256, SOURCE_COMMIT, PILOT_RELEASE_ID,
)
from service1.clientflow_update_models import (
    ClientFlowDeployment, ClientFlowDeploymentEvent, ClientFlowUpdateCredential,
)
from service1.db import get_session
from service1.routers import clientflow_release_pilot_63d11 as pilot_route
from .test_clientflow_release_admin_61a_http import environment, _ASGITestClient


@pytest.fixture()
def pilot_client(environment, monkeypatch):
    _, session = environment
    SQLModel.metadata.create_all(session.get_bind(), tables=[
        ClientCommand.__table__, ClientFlowUpdateCredential.__table__,
        ClientFlowDeployment.__table__, ClientFlowDeploymentEvent.__table__,
    ])
    status = session.exec(select(ClientDomainStatus).where(ClientDomainStatus.client_id == 3)).one()
    status.reported_at = datetime.now(timezone.utc).replace(tzinfo=None)
    status.agent_version = "1.3.45"
    status.observed_state = "online"
    credential = ClientFlowUpdateCredential(
        id=str(uuid4()), client_id=3, key_id="63d11-ci-test-update-key",
        public_key_pem="CI synthetic test key, never used by production",
        algorithm="Ed25519", created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(credential)
    session.commit()

    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    from service1.clientflow_pilot_1247_db_authorization import CONFLICTING_FLAGS
    for flag in CONFLICTING_FLAGS:
        monkeypatch.delenv(flag, raising=False)
    # Mock only the immutable local 223 MB TAR reader; the exact hash,
    # signature contract and all DB/credential/role checks remain real.
    monkeypatch.setattr(pilot_route, "deployment_release_snapshot", lambda release: {
        "target_release_id": PILOT_RELEASE_ID,
        "bundle_sha256": APPROVED_BUNDLE_SHA256,
        "bundle_size": APPROVED_BUNDLE_SIZE,
        "release_approval_reference": APPROVAL_REFERENCE,
        "release_candidate_sha256": CANDIDATE_SHA256,
        "source_commit": SOURCE_COMMIT,
    })

    # Test the future exact stage without changing active main. The source-pinned
    # staged catalog is never written to the live catalog by this test.
    from service1 import clientflow_releases
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / 'service1/clientflow_release_catalog_1247_pilot.stage.json'
    monkeypatch.setattr(clientflow_releases, 'CATALOG_PATH', source)
    clientflow_releases.load_catalog.cache_clear()

    # Existing admin fixture overrides auth for a dedicated test user, and
    # uses a monkeypatched password validator inside release administration.
    from service1.models import User
    user = session.get(User, 1)
    app = FastAPI()
    app.include_router(pilot_route.router, prefix="/api")
    app.dependency_overrides[get_current_superadmin_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session
    yield _ASGITestClient(app), session
    clientflow_releases.load_catalog.cache_clear()


def payload(**changes):
    body = {
        "client_id": 3, "target_release_id": PILOT_RELEASE_ID,
        "expected_current_version": "1.3.45", "expected_policy_revision": 1,
        "reason": "Kontrolleret fysisk pilot Viborg1 med lokal recovery",
        "password": "correct-password", "confirmed_single_pilot": True,
    }
    body.update(changes)
    return body


def post(http, data):
    return http.post("/api/clientflow/release-pilot-1247/authorize", json=data)


def test_single_authenticated_pilot_creates_atomic_authorization_and_audit(pilot_client):
    http, session = pilot_client
    response = post(http, payload())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "authorized"
    assert body["client_id"] == 3
    assert body["fleet_authorized"] is False
    deployment = session.get(ClientFlowDeployment, body["deployment_id"])
    assert deployment is not None
    assert deployment.target_release_id == PILOT_RELEASE_ID
    assert deployment.bundle_sha256 == APPROVED_BUNDLE_SHA256
    assert deployment.allow_downgrade is False
    assert deployment.reason == payload()["reason"]
    events = session.exec(select(ClientFlowDeploymentEvent).where(
        ClientFlowDeploymentEvent.deployment_id == deployment.id)).all()
    assert any(event.event_type == "authorized" for event in events)
    # No policy, wave, target, physical acceptance or fleet state was changed.
    from service1.clientflow_release_admin_models import ClientFlowReleaseControl
    control = session.get(ClientFlowReleaseControl, 1)
    assert control.cutover_enabled is False
    assert control.fleet_open is False
    assert control.fresh_install_open is False
    assert post(http, payload()).status_code == 409  # one-shot, never replay
    assert len(session.exec(select(ClientFlowDeployment)).all()) == 1


@pytest.mark.parametrize('changes', [
    {"client_id": 4}, {"target_release_id": "clientflow-1.3.44-seq-1245"},
    {"expected_current_version": "1.3.44"}, {"expected_policy_revision": 2},
    {"confirmed_single_pilot": False}, {"reason": "short"},
    {"password": "wrong"},
])
def test_denies_wrong_client_release_revision_password_and_reason(pilot_client, changes):
    http, session = pilot_client
    result = post(http, payload(**changes))
    assert result.status_code in (400, 403, 409, 422), result.text
    assert session.exec(select(ClientFlowDeployment)).all() == []


def test_stale_or_revoked_status_denies_before_any_write(pilot_client):
    http, session = pilot_client
    row = session.exec(select(ClientDomainStatus)).one()
    row.reported_at = datetime(2026, 11, 17, 9, 0)
    session.commit()
    response = post(http, payload())
    assert response.status_code == 409, response.text
    assert session.exec(select(ClientFlowDeployment)).all() == []


def test_environment_pilot_and_fleet_flags_cannot_grant_new_path(pilot_client, monkeypatch):
    http, session = pilot_client
    monkeypatch.setenv("CLIENTFLOW_1246_PILOT_CLIENT_ID", "3")
    result = post(http, payload())
    assert result.status_code == 409, result.text
    assert session.exec(select(ClientFlowDeployment)).all() == []


def test_mismatched_approved_artifact_denied(pilot_client, monkeypatch):
    http, session = pilot_client
    monkeypatch.setattr(pilot_route, "deployment_release_snapshot", lambda _: {
        "target_release_id": PILOT_RELEASE_ID, "bundle_sha256": "f"*64,
        "bundle_size": APPROVED_BUNDLE_SIZE,
        "release_approval_reference": APPROVAL_REFERENCE,
        "release_candidate_sha256": CANDIDATE_SHA256, "source_commit": SOURCE_COMMIT,
    })
    result = post(http, payload())
    assert result.status_code == 409, result.text
    assert session.exec(select(ClientFlowDeployment)).all() == []
