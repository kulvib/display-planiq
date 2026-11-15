"""Isolated default-closed release-administration HTTP + transaction tests.

No production database, Render flags, binary releases or client agents are used.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import pytest

pytest.importorskip("sqlmodel")
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from service1.clientflow_release_admin_models import (
    ClientFlowReleaseControl, ClientFlowRolloutTarget, ClientFlowRolloutWave,
    ClientFlowPhysicalAcceptance,
)
from service1.db import get_session
from service1.auth import get_current_superadmin_user
from service1.models import User, Client, AuditLog
from service1.routers import clientflow_release_administration as route

SHA = "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
RELEASE_ID = "clientflow-1.3.44-seq-1245"


# Match the repository's dependency-free ASGI HTTP integration test pattern.
class _ASGIResponse:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self._body = body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self._body.decode("utf-8"))


class _ASGITestClient:
    """Minimal in-process ASGI client using only the runtime's existing stack."""

    def __init__(self, app: FastAPI):
        self.app = app

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
    ) -> _ASGIResponse:
        body = b"" if json_body is None else json.dumps(json_body).encode("utf-8")
        header_items = [(b"host", b"testserver")]
        if json_body is not None:
            header_items.extend(
                [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ]
            )
        if headers:
            header_items.extend(
                (name.lower().encode("latin-1"), value.encode("latin-1"))
                for name, value in headers.items()
            )

        async def invoke() -> _ASGIResponse:
            messages: list[dict[str, Any]] = []
            request_sent = False

            async def receive() -> dict[str, Any]:
                nonlocal request_sent
                if not request_sent:
                    request_sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}

            async def send(message: dict[str, Any]) -> None:
                messages.append(message)

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": method.upper(),
                "scheme": "http",
                "path": path,
                "raw_path": path.encode("ascii"),
                "query_string": b"",
                "root_path": "",
                "headers": header_items,
                "client": ("127.0.0.1", 50000),
                "server": ("testserver", 80),
            }
            await self.app(scope, receive, send)
            starts = [message for message in messages if message["type"] == "http.response.start"]
            assert len(starts) == 1, messages
            response_body = b"".join(
                message.get("body", b"")
                for message in messages
                if message["type"] == "http.response.body"
            )
            return _ASGIResponse(int(starts[0]["status"]), response_body)

        return asyncio.run(invoke())

    def get(self, path: str, *, headers: dict[str, str] | None = None) -> _ASGIResponse:
        return self.request("GET", path, headers=headers)

    def post(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
    ) -> _ASGIResponse:
        return self.request("POST", path, headers=headers, json_body=json)

    def put(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
    ) -> _ASGIResponse:
        return self.request("PUT", path, headers=headers, json_body=json)



@pytest.fixture()
def environment(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine, tables=[
        User.__table__, Client.__table__, AuditLog.__table__,
        ClientFlowReleaseControl.__table__, ClientFlowRolloutWave.__table__, ClientFlowRolloutTarget.__table__,
        ClientFlowPhysicalAcceptance.__table__,
    ])
    with Session(engine) as session:
        admin = User(id=1, username="admin-test", email="admin@example.com", hashed_password="stored", role="superadmin", is_active=True)
        client = Client(id=3, name="Viborg1", status="approved", ubuntu_version="26.04")
        control = ClientFlowReleaseControl(id=1, stable_release_id=RELEASE_ID, stable_bundle_sha256=SHA,
                                           fresh_install_open=False, fleet_open=False, cutover_enabled=False,
                                           revision=1, updated_at=datetime(2026, 11, 15, 12, 0))
        session.add(admin)
        session.add(client)
        session.add(control)
        session.commit()
        session.refresh(admin)

        monkeypatch.setattr(route, "verify_password", lambda password, hashed: password == "correct-password")
        monkeypatch.setattr(route, "_approved_lock", lambda: {"approved_bundle_sha256": SHA})
        monkeypatch.setattr(route, "load_catalog", lambda: {
            "latest_stable": "1.3.44", "default_install_version": "1.3.44",
            "releases": [{"release_id": RELEASE_ID, "status": "stable", "install_modes": ["fresh_install", "in_place_update"],
                           "rollback_allowed": False}],
        })

        app = FastAPI()
        app.include_router(route.router, prefix="/api")
        app.dependency_overrides[get_current_superadmin_user] = lambda: admin
        app.dependency_overrides[get_session] = lambda: session
        yield _ASGITestClient(app), session


def _payload(**overrides):
    data = {
        "kind": "pilot", "client_ids": [3], "source_version": "1.3.43",
        "reason": "Physical pilot Viborg1", "expires_in_hours": 24,
        "expected_revision": 1, "password": "correct-password",
    }
    data.update(overrides)
    return data


def test_default_closed_status_and_draft_does_not_create_deployment(environment):
    http, session = environment
    before = http.get("/api/clientflow/release-administration")
    assert before.status_code == 200, before.text
    policy = before.json()
    assert policy["phase"] == "additive_draft_only"
    assert policy["authorization_active"] is False
    assert policy["fleet_open"] is False
    assert policy["fresh_install_open"] is False
    assert policy["physical_pilot_accepted"] is False
    assert policy["stable_release_id"] == RELEASE_ID
    created = http.post("/api/clientflow/release-administration/drafts", json=_payload())
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["state"] == "draft" and row["client_ids"] == [3]
    assert len(session.exec(select(ClientFlowRolloutTarget)).all()) == 1
    assert session.exec(select(ClientFlowRolloutTarget)).one().state == "draft"
    assert len(session.exec(select(AuditLog).where(AuditLog.action == "clientflow_rollout_draft_created")).all()) == 1
    assert http.get("/api/clientflow/release-administration").json()["waves"][0]["state"] == "draft"
    assert http.post("/api/clientflow/release-administration/drafts/invalid/approve").status_code == 404
    assert session.get(ClientFlowReleaseControl, 1).cutover_enabled is False


def test_pilot_mismatch_and_wrong_password_do_not_create_draft(environment):
    http, session = environment
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload(client_ids=[4])).status_code == 409
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload(password="wrong-password")).status_code == 403
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload(expected_revision=3)).status_code == 409
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload(client_ids=[3, 3])).status_code == 422
    assert len(session.exec(select(ClientFlowRolloutWave)).all()) == 0
    assert session.get(ClientFlowReleaseControl, 1).fleet_open is False


def test_cancel_draft_is_audited_and_cannot_be_reused(environment):
    http, session = environment
    response = http.post("/api/clientflow/release-administration/drafts", json=_payload())
    assert response.status_code == 201, response.text
    wave_id = response.json()["id"]
    url = f"/api/clientflow/release-administration/drafts/{wave_id}/cancel"
    assert http.post(url, json={"password": "correct-password", "expected_revision": 1}).status_code == 200
    assert session.get(ClientFlowRolloutWave, wave_id).state == "cancelled"
    assert session.exec(select(ClientFlowRolloutTarget)).one().state == "revoked"
    assert http.post(url, json={"password": "correct-password", "expected_revision": 1}).status_code == 409
    assert len(session.exec(select(AuditLog).where(AuditLog.action == "clientflow_rollout_draft_cancelled")).all()) == 1


def test_control_drift_fails_closed(environment):
    http, session = environment
    control = session.get(ClientFlowReleaseControl, 1)
    control.fresh_install_open = True
    session.add(control)
    session.commit()
    res = http.get("/api/clientflow/release-administration")
    assert res.status_code == 503
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload()).status_code == 503
    assert not session.exec(select(ClientFlowRolloutWave)).all()


# 61B-1: Planning review and pause are deliberately inert. Existing 61A
# database gates and deployment handlers remain unchanged.
def _plan_action(http, wave_id, action, revision, password="correct-password"):
    return http.post(f"/api/clientflow/release-administration/drafts/{wave_id}/{action}", json={
        "expected_revision": revision, "password": password,
    })


def test_61b_plan_review_pause_resume_cancel_never_authorizes_deployments(environment):
    http, session = environment
    created = http.post("/api/clientflow/release-administration/drafts", json=_payload())
    assert created.status_code == 201, created.text
    wave_id = created.json()["id"]
    reviewed = _plan_action(http, wave_id, "review", 1)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json() == {
        "id": wave_id, "state": "draft", "revision": 2,
        "reviewed_for_planning": True, "deployment_authorized": False,
    }
    wave = session.get(ClientFlowRolloutWave, wave_id)
    assert wave.approved_at is not None and wave.approved_by_user_id == 1
    assert wave.state == "draft"
    targets = session.exec(select(ClientFlowRolloutTarget)).all()
    assert len(targets) == 1 and targets[0].state == "draft"
    assert targets[0].consumed_deployment_id is None
    assert _plan_action(http, wave_id, "review", 2).status_code == 409
    paused = _plan_action(http, wave_id, "pause", 2)
    assert paused.status_code == 200, paused.text
    assert paused.json()["state"] == "paused" and paused.json()["revision"] == 3
    assert _plan_action(http, wave_id, "pause", 3).status_code == 409
    assert _plan_action(http, wave_id, "resume", 2).status_code == 409  # stale revision
    resumed = _plan_action(http, wave_id, "resume", 3)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["state"] == "draft" and resumed.json()["revision"] == 4
    assert _plan_action(http, wave_id, "resume", 4).status_code == 409
    cancelled = _plan_action(http, wave_id, "cancel", 4)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled" and cancelled.json()["revision"] == 5
    assert _plan_action(http, wave_id, "review", 5).status_code == 409
    assert session.get(ClientFlowReleaseControl, 1).cutover_enabled is False
    assert session.get(ClientFlowReleaseControl, 1).fleet_open is False
    assert session.get(ClientFlowReleaseControl, 1).fresh_install_open is False
    assert session.exec(select(ClientFlowRolloutTarget)).one().state == "revoked"
    assert len(session.exec(select(AuditLog).where(AuditLog.action == "clientflow_rollout_plan_reviewed")).all()) == 1
    assert len(session.exec(select(AuditLog).where(AuditLog.action == "clientflow_rollout_plan_paused")).all()) == 1
    assert len(session.exec(select(AuditLog).where(AuditLog.action == "clientflow_rollout_plan_resumed")).all()) == 1
    assert len(session.exec(select(AuditLog).where(AuditLog.action == "clientflow_rollout_draft_cancelled")).all()) == 1
    policy = http.get("/api/clientflow/release-administration").json()
    assert policy["planning_review_available"] is True
    assert policy["authorization_active"] is False
    assert policy["physical_pilot_accepted"] is False
    assert policy["waves"][0]["deployment_authorized"] is False


def test_61b_review_wrong_password_or_revision_never_changes_plan(environment):
    http, session = environment
    wave_id = http.post("/api/clientflow/release-administration/drafts", json=_payload()).json()["id"]
    assert _plan_action(http, wave_id, "review", 1, password="wrong-password").status_code == 403
    assert _plan_action(http, wave_id, "review", 2).status_code == 409
    assert _plan_action(http, wave_id, "pause", 1).status_code == 409
    wave = session.get(ClientFlowRolloutWave, wave_id)
    assert wave.revision == 1 and wave.approved_at is None and wave.state == "draft"
    assert not session.exec(select(AuditLog).where(AuditLog.action == "clientflow_rollout_plan_reviewed")).all()


def test_61b_expired_or_corrupted_targets_fail_closed(environment, monkeypatch):
    http, session = environment
    wave_id = http.post("/api/clientflow/release-administration/drafts", json=_payload()).json()["id"]
    target = session.exec(select(ClientFlowRolloutTarget)).one()
    # An unexpectedly authorized target is GLOBAL security drift, not an
    # ordinary per-plan conflict: _bound_control must fail closed with 503.
    for unexpected_state in ("approved", "consumed"):
        target.state = unexpected_state
        session.add(target)
        session.commit()
        refused = _plan_action(http, wave_id, "review", 1)
        assert refused.status_code == 503, refused.text
        assert http.get("/api/clientflow/release-administration").status_code == 503
        wave = session.get(ClientFlowRolloutWave, wave_id)
        assert wave.revision == 1 and wave.approved_at is None
        assert not session.exec(select(AuditLog).where(
            AuditLog.action == "clientflow_rollout_plan_reviewed"
        )).all()
    # After the drift is corrected, the read-only administration view works;
    # expired plans must still be rejected as ordinary 409 conflicts.
    target.state = "draft"
    session.add(target)
    session.commit()
    assert http.get("/api/clientflow/release-administration").status_code == 200
    from datetime import timedelta
    wave = session.get(ClientFlowRolloutWave, wave_id)
    # Advance the application clock beyond the real expiry without writing an
    # invalid interval to SQLite/PostgreSQL (expires_at must exceed created_at).
    after_expiry = wave.expires_at + timedelta(seconds=1)
    monkeypatch.setattr(route, "_utcnow", lambda: after_expiry)
    refused = _plan_action(http, wave_id, "review", 1)
    assert refused.status_code == 409, refused.text
    wave = session.get(ClientFlowRolloutWave, wave_id)
    assert wave.state == "draft" and wave.revision == 1 and wave.approved_at is None
    assert not session.exec(select(AuditLog).where(
        AuditLog.action == "clientflow_rollout_plan_reviewed"
    )).all()


def test_61b_any_active_client_can_be_a_proposed_pilot_without_hardcoded_id(environment):
    http, session = environment
    session.add(Client(id=4, name="Ny testklient", status="approved", ubuntu_version="26.04"))
    session.commit()
    proposed = http.post("/api/clientflow/release-administration/drafts", json=_payload(
        client_ids=[4], source_version="1.3.42",
    ))
    assert proposed.status_code == 201, proposed.text
    assert proposed.json()["client_ids"] == [4]
    assert proposed.json()["source_version"] == "1.3.42"
    assert session.exec(select(ClientFlowRolloutTarget)).one().state == "draft"
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload(client_ids=[3, 4])).status_code == 409
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload(source_version="invalid")).status_code == 422


def test_61b_paused_plan_can_be_cancelled_without_resuming(environment):
    http, session = environment
    wave_id = http.post("/api/clientflow/release-administration/drafts", json=_payload()).json()["id"]
    assert _plan_action(http, wave_id, "review", 1).status_code == 200
    assert _plan_action(http, wave_id, "pause", 2).status_code == 200
    assert _plan_action(http, wave_id, "cancel", 3).status_code == 200
    assert session.exec(select(ClientFlowRolloutTarget)).one().state == "revoked"
    assert _plan_action(http, wave_id, "resume", 4).status_code == 409


def test_61b_gates_remain_fail_closed_during_planning(environment):
    http, session = environment
    wave_id = http.post("/api/clientflow/release-administration/drafts", json=_payload()).json()["id"]
    policy = session.get(ClientFlowReleaseControl, 1)
    policy.cutover_enabled = True
    session.add(policy)
    session.commit()
    assert _plan_action(http, wave_id, "review", 1).status_code == 503
    assert _plan_action(http, wave_id, "cancel", 1).status_code == 503
    assert http.get("/api/clientflow/release-administration").status_code == 503
    assert session.get(ClientFlowRolloutWave, wave_id).state == "draft"


def test_61b_non_superadmin_rejected(environment):
    http, session = environment
    ordinary = User(id=6, username="regular", email="regular@example.com", hashed_password="stored", role="user", is_active=True)
    http.app.dependency_overrides[get_current_superadmin_user] = lambda: ordinary
    assert http.get("/api/clientflow/release-administration").status_code == 403
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload()).status_code == 403


def test_61b_unexpected_physical_acceptance_fails_closed(environment):
    http, session = environment
    from service1.clientflow_release_admin_models import ClientFlowPhysicalAcceptance
    row = ClientFlowPhysicalAcceptance(
        id="00000000-0000-4000-8000-000000000001", release_id=RELEASE_ID,
        bundle_sha256=SHA, client_id=3, actor_user_id=1,
        decision="accepted", evidence={"test_only": True},
        created_at=datetime(2026, 11, 15, 13, 0),
    )
    session.add(row)
    session.commit()
    assert http.get("/api/clientflow/release-administration").status_code == 503
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload()).status_code == 503


def test_61b_impersonation_and_real_actor_mismatch_rejected(environment):
    from fastapi import HTTPException
    from starlette.requests import Request
    _http, session = environment
    user = session.get(User, 1)
    request = Request({"type": "http", "headers": []})
    request.state.impersonation_active = True
    with pytest.raises(HTTPException) as denied:
        route._require_actor(request, user)
    assert denied.value.status_code == 409
    request.state.impersonation_active = False
    request.state.real_actor = User(id=42, username="not-admin", email="other@example.com",
                                    hashed_password="stored", role="superadmin", is_active=True)
    with pytest.raises(HTTPException) as denied:
        route._require_actor(request, user)
    assert denied.value.status_code == 409
